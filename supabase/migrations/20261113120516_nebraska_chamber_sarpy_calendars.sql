CREATE OR REPLACE FUNCTION rq_curator_private.community_format_supported(p_kind text, p_adapter text, p_key text)
 RETURNS boolean
 LANGUAGE sql
 IMMUTABLE
 SET search_path TO ''
AS $function$
 select coalesce((p_kind='html' and p_adapter='html' and p_key in ('greater_omaha_chamber_growthzone_html_ne','sarpy_recurring_tourism_html_ne','sarpy_sports_tourism_html_ne')) or (p_kind='html' and p_adapter='html' and p_key='zoo_bar_lincoln_html_ne') or (p_kind='rss' and p_adapter='wordpress' and p_key in ('municipal_3ceeb945131a8a11d7e63495','municipal_dbc6ce3130dab2da69e6d57e','municipal_f6162b4f314aa6653cfeca92','municipal_4be969ccce374519948bcf61','municipal_f18b942eb3e39e3a547fd0d5'))
 or (p_kind='json' and p_adapter='library' and p_key in ('municipal_c91056bd80f24dd814016374','municipal_5d303aae26849421929219ee','municipal_0c023710af802e201c31e71b'))
 or (p_kind='rss' and p_adapter='library' and p_key in ('municipal_41dcfb1feff056779e0f0b42'))
 or (p_kind='html' and p_adapter='html' and p_key in ('omaha_public_library_biblioevents_ne','great_plains_trail_network_ne','plantnebraska_events_ne','conservation_nebraska_events_ne','omaha_reverb_lounge_events','omaha_admiral_events','omaha_henry_doorly_zoo_events','omaha_lauritzen_gardens_events','omaha_parks_webtrac_ne','pageturners_lounge_omaha_ne','blue_sky_bar_patio_omaha_ne','saro_cider_lincoln_ne','lincoln_chamber_weblink_ne','omaha_sydney_rockhouse_ne','thor_trails_squarespace_ne','omaha_kiewit_luminarium_ne','prairie_pines_events_ne','glacier_creek_preserve_events_ne','cellar_426_events_ne','omaha_first_united_methodist_mec_ne','friends_omaha_library_mec_ne','spielbound_meetup_ne','americas_pub_quiz_ne','spring_creek_prairie_audubon_ne','lincoln_parks_opencities_ne','omaha_running_club_eventon_ne','goatz_hitchcock_experience_ne','mana_games_topdeck_ne','sower_books_lit_circle_ne','hyde_observatory_programs_ne','mana_games_official_programs_ne','lincoln_city_libraries_localhop_ne','gretna_public_library_localhop_ne','skyybox_trivia_ne','postscript_elfsight_ne','elleinad_storytimes_ne')),false);
$function$
;
CREATE OR REPLACE FUNCTION rq_curator_private.udell_address_v1(p_text text)
 RETURNS text
 LANGUAGE plpgsql
 IMMUTABLE
 SET search_path TO ''
AS $function$
declare v text; m text[]; k text; val text;
begin
 if p_text is null or length(p_text)>400 or p_text ~ '[[:cntrl:]]'
  or p_text ~* '(https?://|online|virtual|zoom|tbd|to be announced|p[.]?o[.]? box)' then return null;end if;
 v:=lower(btrim(p_text));
 v:=regexp_replace(v,',[[:space:]]*(united states( of america)?|usa|us)[[:space:]]*$','','i');
 v:=regexp_replace(v,'[,[:space:]]+[0-9]{5}(-[0-9]{4})?[[:space:]]*$','');
 k:=regexp_replace(substring(v from ',([^,]+)$'),'^[[:space:]]+','');
 val:='{"alabama":"al","alaska":"ak","arizona":"az","arkansas":"ar","california":"ca","colorado":"co","connecticut":"ct","delaware":"de","district of columbia":"dc","florida":"fl","georgia":"ga","hawaii":"hi","idaho":"id","illinois":"il","indiana":"in","iowa":"ia","kansas":"ks","kentucky":"ky","louisiana":"la","maine":"me","maryland":"md","massachusetts":"ma","michigan":"mi","minnesota":"mn","mississippi":"ms","missouri":"mo","montana":"mt","nebraska":"ne","nevada":"nv","new hampshire":"nh","new jersey":"nj","new mexico":"nm","new york":"ny","north carolina":"nc","north dakota":"nd","ohio":"oh","oklahoma":"ok","oregon":"or","pennsylvania":"pa","rhode island":"ri","south carolina":"sc","south dakota":"sd","tennessee":"tn","texas":"tx","utah":"ut","vermont":"vt","virginia":"va","washington":"wa","west virginia":"wv","wisconsin":"wi","wyoming":"wy"}'::jsonb->>k;
 if val is not null then
  v:=regexp_replace(v,',[[:space:]]*[^,]+$',','||val);
 end if;
 v:=regexp_replace(v,',[[:space:]]*([a-z]{2}),[[:space:]]*\1$',',\1');
 m:=regexp_match(v,'(?<![[:alnum:]-])([0-9]{1,6}(?:[a-z]|-(?:[0-9]{1,6}|[a-z]))?[[:space:]]+[^,]+),[[:space:]]*([a-z .''-]+),[[:space:]]*([a-z]{2})$');
 if m is null then
  -- A publisher's numbered building belongs to the street component. Fold
  -- only this otherwise-unparseable comma; never discard its identifier.
  v:=regexp_replace(v,',[[:space:]]*((?:building|bldg)[.]?[[:space:]]+(?:[0-9]+[a-z]?|[a-z][0-9]+)(?:-[a-z0-9]+)?),',' \1,','g');
  m:=regexp_match(v,'(?<![[:alnum:]-])([0-9]{1,6}(?:[a-z]|-(?:[0-9]{1,6}|[a-z]))?[[:space:]]+[^,]+),[[:space:]]*([a-z .''-]+),[[:space:]]*([a-z]{2})$');
 end if;
 if m is null or m[1] ~ '[/&@]' or length(btrim(m[2]))<2
  -- A separated hyphen must not become either street text or a discarded
  -- number prefix (1879 -3 / 1879- 3). Matching groups remain street/city/state.
  or m[1] ~ '^[0-9]{1,6}(?:[a-z]|-(?:[0-9]{1,6}|[a-z]))?[[:space:]]+-[[:space:]]*[0-9a-z]'
  or left(v,strpos(v,m[1])-1) ~ '(^|[^[:alnum:]])[0-9]+[a-z]?[[:space:]]*-[[:space:]]*$'
  or m[3] !~ '^(al|ak|az|ar|ca|co|ct|de|dc|fl|ga|hi|id|il|in|ia|ks|ky|la|me|md|ma|mi|mn|ms|mo|mt|ne|nv|nh|nj|nm|ny|nc|nd|oh|ok|or|pa|ri|sc|sd|tn|tx|ut|vt|va|wa|wv|wi|wy)$'
  or m[1] !~ '\m(street|st|road|rd|avenue|ave|boulevard|blvd|drive|dr|lane|ln|court|ct|way|parkway|pkwy|place|pl|plaza|plz|circle|cir|highway|hwy|terrace|ter|loop|trail|trl)\M'
 then return null;end if;
 v:=replace(m[1]||','||btrim(m[2])||','||m[3],'.','');
 select string_agg(coalesce('{"street":"st","road":"rd","avenue":"ave","boulevard":"blvd","drive":"dr","lane":"ln","court":"ct","parkway":"pkwy","place":"pl","plaza":"plz","circle":"cir","highway":"hwy","terrace":"ter","trail":"trl","north":"n","south":"s","east":"e","west":"w"}'::jsonb->>part[1],part[1]),'' order by ord) into v
 from regexp_matches(v,'([[:alnum:]_]+|[^[:alnum:]_]+)','g') with ordinality words(part,ord);
 return regexp_replace(btrim(v),'[[:space:]]+',' ','g');
end;
$function$
;
update public.municipal_event_sources
set approval='paused',health='disabled',intake_state='deactivated',
    intake_reason=case when id=5351 then 'publisher_http_403' when id=5344 then 'publisher_http_404' else 'robots_denied' end,
    intake_checked_at=now(),updated_at=now()
where (id between 5334 and 5340 and feed_url like 'https://calendar.google.com/calendar/ical/%')
   or (id in (5353,5354) and feed_url like 'https://www.sarpy.gov/common/modules/iCalendar/%')
   or (id=5351 and preview_error='publisher_http_403')
   or (id=5344 and preview_error='publisher_http_404');
update rq_curator_private.source_coverage_registry r set enabled=false,updated_at=now()
from public.municipal_event_sources s where r.source_key=s.source_key and r.execution_path='community'
and s.id in (5334,5335,5336,5337,5338,5339,5340,5344,5351,5353,5354) and s.health='disabled' and r.enabled;

insert into public.municipal_event_sources
(source_key,publisher_name,feed_url,kind,platform_adapter,state_code,timezone,source_class,approval,health,coverage_lat,coverage_lng,coverage_radius_miles,curator_note,catalog_origin)
values
('greater_omaha_chamber_growthzone_html_ne','Greater Omaha Chamber','https://your.omahachamber.org/events','html','html','NE','America/Chicago','event','approved','unchecked',41.26,-95.93,20,'Public GrowthZone listing and exact event details.','roomquest/metro-discovery'),
('sarpy_recurring_tourism_html_ne','Sarpy Tourism — Recurring Events','https://www.sarpy.gov/Calendar.aspx?CID=36&view=list','html','html','NE','America/Chicago','event','approved','unchecked',41.175,-96.107,15,'Public CivicPlus HTML recurring calendar.','roomquest/metro-discovery'),
('sarpy_sports_tourism_html_ne','Sarpy Tourism — Sporting Events','https://www.sarpy.gov/Calendar.aspx?CID=35&view=list','html','html','NE','America/Chicago','event','approved','unchecked',41.153,-95.923,15,'Public CivicPlus HTML sports calendar.','roomquest/metro-discovery')
on conflict(source_key) do nothing;

insert into rq_curator_private.community_source_coverage_seeds(source_id,lat_cell,lng_cell)
select id,floor(coverage_lat*4)::integer,floor(coverage_lng*4)::integer
from public.municipal_event_sources where source_key in ('greater_omaha_chamber_growthzone_html_ne','sarpy_recurring_tourism_html_ne','sarpy_sports_tourism_html_ne')
on conflict do nothing;
