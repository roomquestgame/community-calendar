-- Keep geocoder submit on the critical path small and durable.
--
-- The provider result is validated and persisted by forward_geocoder_v1.
-- Event-coordinate application is intentionally handled separately so a
-- venue result cannot be lost because a broad event update timed out.

do $migration$
declare
  d text;
  old_fragment text := E'  n:=rq_curator_private.apply_udell_venue_cache();\n'
    || E'  return jsonb_build_object(''resolved'',true,''events_updated'',n);';
  new_fragment text := E'  -- Event-coordinate application is asynchronous.\n'
    || E'  return jsonb_build_object(''resolved'',true,''events_updated'',0);';
begin
  d := pg_get_functiondef(
    'rq_curator_gateway.forward_geocoder_v1(text,text,jsonb)'::regprocedure
  );

  if position(old_fragment in d) = 0 then
    raise exception 'Expected synchronous geocoder submit fragment was not found';
  end if;

  d := replace(d, old_fragment, new_fragment);
  execute d;
end
$migration$;

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

  return rq_curator_gateway.forward_geocoder_v1(p_token, p_action, p_payload);
end;
$function$;
