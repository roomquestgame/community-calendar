-- Keep geocoder submit minimal and atomic.
--
-- The legacy submit function performs validation and work that can stall under
-- database contention. This path keeps only the essential provider checks,
-- request completion, and venue-resolution update. Event publication remains a
-- separate asynchronous operation.

create or replace function rq_curator_gateway.forward_geocoder_submit_fast(
  p_token text,
  p_payload jsonb
)
returns jsonb
language plpgsql
security definer
set search_path = ''
as $function$
declare
  t timestamptz := clock_timestamp();
  k text;
  lease uuid;
  r_id uuid;
  r jsonb;
  lat double precision;
  lng double precision;
  accuracy numeric;
  request_ok uuid;
  venue_ok text;
begin
  if not rq_curator_private.token_valid(p_token) then
    raise exception 'Invalid collector authorization' using errcode='42501';
  end if;

  if p_payload is null
     or jsonb_typeof(p_payload) <> 'object'
     or jsonb_typeof(p_payload#>'{response,results}') <> 'array'
     or jsonb_array_length(p_payload#>'{response,results}') not between 1 and 2 then
    raise exception 'Invalid provider response' using errcode='22023';
  end if;

  k := nullif(p_payload->>'venue_key','');
  lease := (p_payload->>'lease_id')::uuid;
  r_id := (p_payload->>'request_id')::uuid;
  r := p_payload#>'{response,results,0}';
  lat := (r#>>'{location,lat}')::double precision;
  lng := (r#>>'{location,lng}')::double precision;
  accuracy := coalesce((r->>'accuracy')::numeric,0);

  if k is null
     or lat is null or lng is null
     or lat not between -90 and 90
     or lng not between -180 and 180
     or accuracy not between 0.9 and 1
     or coalesce(r->>'accuracy_type','') not in ('rooftop','point')
     or coalesce(r#>>'{address_components,country}','') not in ('US','USA') then
    raise exception 'Unverified address' using errcode='22023';
  end if;

  update rq_curator_private.forward_geocoder_requests
     set outcome='resolved'
   where request_id=r_id
     and venue_key=k
     and lease_id=lease
     and outcome='reserved'
   returning request_id into request_ok;

  if request_ok is null then
    raise exception 'Unreserved geocoder result' using errcode='42501';
  end if;

  update rq_curator_private.udell_venue_resolution
     set status='resolved',
         latitude=lat,
         longitude=lng,
         evidence=jsonb_build_object(
           'provider','geocodio',
           'api_version','v2',
           'input_address',query_text,
           'request_id',r_id,
           'verified_at',t,
           'response',p_payload->'response'
         ),
         checked_at=t,
         lease_id=null,
         claimed_until=null,
         active_request=null,
         updated_at=t
   where venue_key=k
     and lease_id=lease
     and claimed_until>t
     and status='pending'
   returning venue_key into venue_ok;

  if venue_ok is null then
    raise exception 'Invalid or expired geocoder claim' using errcode='42501';
  end if;

  return jsonb_build_object('resolved',true,'events_updated',0);
end;
$function$;

create or replace function rq_curator_gateway.forward_geocoder(
  p_token text,
  p_action text,
  p_payload jsonb default '{}'::jsonb
)
returns jsonb
language plpgsql
security definer
set search_path = ''
as $function$
begin
  if not rq_curator_private.token_valid(p_token) then
    raise exception 'Invalid collector authorization' using errcode='42501';
  end if;

  if p_action = 'claim' then
    return rq_curator_private.forward_geocoder_claim_fast(p_payload);
  end if;

  if p_action = 'submit' then
    return rq_curator_gateway.forward_geocoder_submit_fast(p_token,p_payload);
  end if;

  return rq_curator_gateway.forward_geocoder_v1(p_token, p_action, p_payload);
end;
$function$;
