from datetime import datetime, timedelta, timezone
import json
from unittest.mock import Mock

import pytest

from roomquest import eventon


def test_eventon_preserves_occurrence_times_and_maps_reedy_creek():
    start = (datetime.now(timezone.utc) + timedelta(days=1)).replace(microsecond=0)
    end = start + timedelta(hours=3)
    html = f'''<div class="eventon_list_event" data-event_id="117532" data-time="1-2">
        <meta itemprop="eventStatus" content="https://schema.org/EventScheduled">
        <link itemprop="url" href="{eventon.CALENDAR}invasive-plant-removal-at-reedy-creek/">
        <meta itemprop="startDate" content="{start.isoformat()}">
        <meta itemprop="endDate" content="{end.isoformat()}">
        <span class="evcal_event_title">Invasive Plant Removal at Reedy Creek</span>
        </div>'''
    payload = json.dumps({'cals': {eventon.CALENDAR_ID: {'json': [{}], 'html': html}}})
    [row] = eventon.parse(payload)
    assert row['starts_at'] == start.isoformat()
    assert row['venue_address'] == eventon.REEDY_CREEK
    assert row['id'].startswith('117532:')


def test_generic_eventon_contract_and_collection_use_one_same_host_calendar():
    listing = 'https://nature.example.org/events-calendar/'
    calendar_id = 'evcal_calendar_696'
    start = (datetime.now(timezone.utc) + timedelta(days=2)).replace(microsecond=0)
    end = start + timedelta(hours=2)
    page = f'''<div id="evo_global_data" data-d='{{"calendars":[]}}'></div>
      <div id="{calendar_id}"><div class="evo_cal_data" data-sc='{{"fixed_month":"12"}}'></div></div>
      <script>var evo_general_params = {{"ajaxurl":"https://nature.example.org/wp-admin/admin-ajax.php","evo_ajax_url":"/?evo-ajax=%%endpoint%%","n":"49da3beaec"}};</script>'''
    occurrence = f'''<div class="eventon_list_event" data-event_id="88" data-time="1-2">
      <meta itemprop="eventStatus" content="https://schema.org/EventScheduled">
      <link itemprop="url" href="https://nature.example.org/program/winter-walk/">
      <meta itemprop="startDate" content="{start.isoformat()}">
      <meta itemprop="endDate" content="{end.isoformat()}">
      <span class="evcal_event_title">Winter Walk</span>
      <span itemprop="location"><span itemprop="name">Nature Center</span></span>
      <span itemprop="streetAddress">100 Forest Road, Example, MD 20000</span></div>'''
    payload = json.dumps({'cals': {calendar_id: {'json': [{}], 'html': occurrence}}})
    fetch = Mock(side_effect=[page, payload])
    source = {'source_key': 'municipal_test', 'feed_url': listing,
              'kind': 'json', 'platform_adapter': 'eventon'}
    [row] = eventon.collect(source, fetch)
    assert row['title'] == 'Winter Walk'
    assert row['event_url'] == 'https://nature.example.org/program/winter-walk/'
    fetch.assert_any_call('https://nature.example.org/?evo-ajax=eventon_init_load',
                          'application/json', calendar_form=eventon.contract(listing, page)['form'])
def test_eventon_nonce_failure_is_a_precise_provider_condition():
    with pytest.raises(ValueError, match='eventon_nonce_unavailable'):
        eventon.parse(json.dumps({'status': 'bad', 'msg': 'Nonce validation failed'}))
