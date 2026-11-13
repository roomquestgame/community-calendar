CREATE OR REPLACE FUNCTION rq_curator_private.reviewed_json_wordpress_source(p_key text)
 RETURNS boolean
 LANGUAGE sql
 IMMUTABLE
 SET search_path TO ''
AS $function$
  select coalesce(p_key in ('town_of_eutawville_sc','sc_works_trident_sc')
    or rq_curator_private.is_demand_park(p_key)
    or p_key in ('think_iowa_city_ia','howard_county_arts_md','municipal_mapsee_d99dc674be18efff44a15ab4','longwood_basketball_va','hurrdat_sports_bar_ne','reading_room_omaha_wordpress_ne')
    or rq_curator_private.hampton_roads_source_config(p_key)->>'provider' = 'json', false);
$function$
;

update public.municipal_event_sources
set approval='paused',health='disabled',intake_state='deactivated',
    intake_reason='invalid_calendar_payload',intake_checked_at=now(),updated_at=now()
where source_key='reading_room_omaha_ical_ne'
  and feed_url='https://readingroomomaha.com/events/list/?ical=1'
  and preview_error='invalid_calendar_payload'
  and approval='pending';

update rq_curator_private.source_coverage_registry r
set enabled=false,updated_at=now()
from public.municipal_event_sources s
where s.source_key='reading_room_omaha_ical_ne' and s.approval='paused'
  and s.health='disabled' and r.source_key=s.source_key and r.execution_path='community'
  and r.enabled;

insert into public.municipal_event_sources
(source_key,publisher_name,feed_url,kind,platform_adapter,state_code,timezone,
 source_class,approval,health,coverage_lat,coverage_lng,coverage_radius_miles,curator_note,catalog_origin)
values
('reading_room_omaha_wordpress_ne','The Reading Room',
 'https://readingroomomaha.com/wp-json/tribe/events/v1/events',
 'json','wordpress','NE','America/Chicago','event','approved','unchecked',
 41.257541092628,-95.935978077636,15,
 'Publisher Events Calendar API. Venue address verified at https://readingroomomaha.com/contact/.',
 'roomquest/metro-discovery')
on conflict(source_key) do nothing;

insert into rq_curator_private.community_source_coverage_seeds(source_id,lat_cell,lng_cell)
select id,floor(coverage_lat*4)::integer,floor(coverage_lng*4)::integer
from public.municipal_event_sources
where source_key='reading_room_omaha_wordpress_ne' and coverage_lat is not null
on conflict do nothing;

insert into rq_curator_private.udell_venue_resolution
(venue_key,query_text,status,latitude,longitude,evidence,checked_at,updated_at)
select md5(address),address,'resolved',41.257541092628,-95.935978077636,
 jsonb_build_object('provider','us_census_address_range','publisher_address_url',
                    'https://readingroomomaha.com/contact/'),now(),now()
from (select rq_curator_private.udell_address('1505 Farnam St, Omaha, NE 68102') address) a
where address is not null
on conflict(venue_key) do nothing;

-- Refresh the already verified occurrence inside its existing 30-day retention
-- window. This job targets one occurrence and removes itself after it runs.
select cron.schedule('eventquest-elleinad-winter-birds-expiration','0 12 1 12 *',$command$
do $refresh$
begin
  update public.external_events
  set last_checked_at=now(),expires_at=ends_at
  where provider='html' and source_key='elleinad_storytimes_ne'
    and provider_event_id='winter-birds-storytime'
    and external_url='https://calendar.outdoornebraska.gov/event/winter-birds-storytime/'
    and starts_at=timestamptz '2026-12-15 16:00:00+00'
    and ends_at=timestamptz '2026-12-15 16:30:00+00'
    and status='scheduled' and not hidden_for_review
    and provider_classification->>'publication_mode'='facts_only_manual'
    and now()>=ends_at-interval '30 days' and now()<starts_at
    and expires_at>now() and expires_at<ends_at;
  perform cron.unschedule('eventquest-elleinad-winter-birds-expiration');
end;
$refresh$;
$command$)
where now() < timestamptz '2026-12-01 12:00:00+00'
and exists(select 1 from public.external_events
 where source_key='elleinad_storytimes_ne' and provider_event_id='winter-birds-storytime'
   and starts_at=timestamptz '2026-12-15 16:00:00+00' and status='scheduled'
   and not hidden_for_review and expires_at<ends_at);
