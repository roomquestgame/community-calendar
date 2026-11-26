-- The submitted /events URL is a reviewed stale Events Manager shell.  Admit
-- only the independently verified first-party goo-calendar destination after
-- its bounded collector is deployed.
create or replace function rq_curator_private.reviewed_listing_url(url text)
returns boolean
language sql
immutable
set search_path = ''
as $$
 select url in ('https://www.boplex.com/events','https://www.broadwaycomedyclub.com/',
   'https://residentculturebrewing.com/events/','https://residentculturebrewing.com/events/?fwp_event_location=plaza-midwood',
   'https://www.indywinterfarmersmarket.org/',
   'https://www.mythichall.com/games',
   'https://www.gravegarden.org/occevents/',
   'https://www.forestfarmersmarket.com/',
   'https://events.liberty.edu/',
   'https://cambridgeppf.org/events-list/',
   'https://www.cambridgewineacademy.com/wine-tastings/',
   'https://theboxroombgc.co.uk/events-1',
   'https://www.miltoncountrypark.org/whats-on',
   'https://www.algonquinarts.org/calendar.php',
   'https://www.batterseabloem.com/workshop',
   'https://sustainableow.co.uk/feed/',
   'https://www.lynchburgparksandrec.com/programs-and-activities/',
   'https://statetheatreportland.com/calendar/')
$$;
