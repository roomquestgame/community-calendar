"""Synthetic public-widget contract fixtures; no copied event narratives."""
from copy import deepcopy
from datetime import datetime,timedelta,timezone
import json
import unittest
from unittest.mock import patch

from roomquest import raleigh_direct_additional as a

NOW=datetime(2026,11,15,12,tzinfo=timezone.utc)


def source():
    return dict(source_key=a.TIN_ROOF,feed_url=a.SOURCES[a.TIN_ROOF][0],kind='html',platform_adapter='html',timezone=a.ZONE)


def calendar():
    return '<link rel="canonical" href="https://tinroofraleigh.com/calendar/"><main><gigwell-gigstream agency="315647" identity-id="315632" settings="b8txja"></gigwell-gigstream><script src="https://connect.gigwell.com/gigstream/gigstream.js"></script></main><footer>300 Glenwood Ave Raleigh, NC 27603</footer>'


def settings():
    return json.dumps(dict(data=dict(gigstreamSettings=dict(options=[dict(id='b8txja',value=dict(
        filter={'range':'custom','customRangeStart':{'relative':'before','unit':'weeks','value':0},
            'customRangeEnd':{'relative':'after','unit':'months','value':2},'limit':1000,
            'sorting':{'by':'eventDate','direction':'ASC'}},theme=dict(fields=[dict(path='description',enabled=True)])))]))))


def event(identity='1',description='<p>All native performance details.</p>'):
    return dict(id=identity,artistTitle='Music Program',description=description,venueTitle='Raleigh',
        venueEntityId='315647',agencyEntityIds=['315647'],artistEntityIds=['99'],
        startDateTime='2026-11-22T02:00:00.000Z',endDateTime=None,localDate='2026-11-21',localEndDate=None,
        eventTimeZone=a.ZONE,eventAddress=None,eventCity='Raleigh',eventState='NC',eventZipCode='27603',eventCountry='US',
        performanceDurationMinutes=300)


def listing(events=None,hits=None):
    values=events if events is not None else [event()]
    return json.dumps(dict(results=values,hits=len(values) if hits is None else hits,
        profiles=[dict(id='99',profileImageUrl='https://resources2.gigwell.com/prod/313679/images/artist.png')]))


class AdditionalContracts(unittest.TestCase):
    def setUp(self):
        p=patch('roomquest.preview_worker._future_datetime',side_effect=lambda v,**kw:v.astimezone(timezone.utc) if v else None)
        p.start();self.addCleanup(p.stop)

    def fetch(self,url,accept):
        if url==a.SOURCES[a.TIN_ROOF][0]:return calendar()
        if url==a.SETTINGS_URL:return settings()
        self.assertEqual(url,a._plans(NOW)[2])
        return listing()

    def test_complete_only_three_public_gets_and_valid_completed_resume(self):
        cp=None
        for i in range(3):
            r=a.collect_chunk(source(),self.fetch,checkpoint=cp,now=NOW,max_fetches=1)
            cp=json.loads(json.dumps(r['checkpoint']))
            self.assertEqual(a.checkpoint_complete(cp),i==2)
            self.assertEqual(r['complete'],i==2)
            if i<2:self.assertEqual(r['events'],[])
        self.assertEqual(len(r['events']),1)
        again=a.collect_chunk(source(),lambda *_:self.fail('must not fetch'),checkpoint=cp,now=NOW)
        self.assertEqual(again['events'],r['events'])
        self.assertIsNone(a._checkpoint(cp,NOW+timedelta(hours=4,seconds=1)))

    def test_source_widget_settings_and_agency_scope_are_exact(self):
        bad=source();bad['feed_url']=bad['feed_url'].rstrip('/')
        with self.assertRaisesRegex(ValueError,'source_unregistered'):a._source(bad)
        for original,changed in [('315647','315999'),('b8txja','another'),('300 Glenwood Ave','301 Glenwood Ave')]:
            with self.assertRaises(ValueError):a._calendar(calendar().replace(original,changed))
        v=json.loads(settings());v['data']['gigstreamSettings']['options'][0]['value']['filter']['limit']=100
        with self.assertRaisesRegex(ValueError,'calendar_changed'):a._settings(json.dumps(v))
        native=event();native['agencyEntityIds']=['1']
        with self.assertRaisesRegex(ValueError,'identity_changed'):a._listing(listing([native]))

    def test_manifest_must_equal_total_and_remain_bounded(self):
        with self.assertRaisesRegex(ValueError,'manifest_limit'):a._listing(listing(hits=2))
        with self.assertRaisesRegex(ValueError,'manifest_limit'):a._listing(listing([event(str(i+1)) for i in range(201)]))
        with self.assertRaisesRegex(ValueError,'identity_changed'):a._listing(listing([event('1'),event(1)]))

    def test_full_description_street_and_displayed_start_without_inferred_end(self):
        full='<p>'+('Complete program information and artist background. '*70)+'</p><p>Final native paragraph.</p>'
        item=a._listing(listing([event(description=full)]))[0]
        row=a._row(item,NOW)
        self.assertGreater(len(row['description']),2000)
        self.assertIn('Final native paragraph.',row['description'])
        self.assertEqual(row['venue_address'],'300 Glenwood Ave, Raleigh, NC 27603')
        self.assertEqual(row['starts_at'],'2026-11-22T02:00:00+00:00')
        self.assertIsNone(row['ends_at'])
        self.assertEqual(row['image_url'],'https://resources2.gigwell.com/prod/313679/images/artist.png')
        native=event(description='x'*12001)
        with self.assertRaisesRegex(ValueError,'description_limit'):a._row(a._listing(listing([native]))[0],NOW)

    def test_native_local_date_timezone_and_conflicting_street_hold(self):
        item=a._listing(listing())[0]
        for key,value,reason in [('localDate','2026-11-22','schedule_unresolved'),('eventTimeZone','UTC','schedule_unresolved'),('eventAddress','999 Elsewhere St','street_unresolved'),('eventCity','Cary','street_unresolved')]:
            changed=deepcopy(item);changed[key]=value
            with self.assertRaisesRegex(ValueError,reason):a._row(changed,NOW)
        item['startDateTime']='2026-11-15T02:00:00.000Z';item['localDate']='2026-11-14'
        with self.assertRaisesRegex(ValueError,'outside_window'):a._row(item,NOW)

    def test_checkpoint_tampering_and_arbitrary_request_plan_rejected(self):
        r=a.collect_chunk(source(),self.fetch,now=NOW);cp=r['checkpoint']
        for field,value in [('description','Changed narrative'),('starts_at','2026-11-22T04:00:00+00:00'),('venue_address','Foreign street'),('lat',35.8)]:
            bad=deepcopy(cp);bad['events'][0][field]=value
            with self.assertRaisesRegex(ValueError,'checkpoint_invalid'):a._checkpoint(bad,NOW)
        partial=a.collect_chunk(source(),self.fetch,now=NOW,max_fetches=1)['checkpoint'];partial['pending_pages'][0]='https://evil.example/'
        a._seal(partial)
        with self.assertRaisesRegex(ValueError,'checkpoint_invalid'):a._checkpoint(partial,NOW)

    def test_shared_calendar_url_still_preserves_parallel_event_identities(self):
        items=a._listing(listing([event('1'),event('2')]))
        rows=[a._row(v,NOW) for v in items]
        self.assertEqual(rows[0]['event_url'],rows[1]['event_url'])
        self.assertNotEqual(rows[0]['id'],rows[1]['id'])
        self.assertFalse(a.event_url(a.TIN_ROOF,rows[0]['event_url']+'?gig=1'))
        self.assertIsNone(a.photo_url('https://resources2.gigwell.com.evil/prod/313679/images/artist.png'))


if __name__=='__main__':unittest.main()
