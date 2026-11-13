"""Remove publisher layout shortcodes while preserving event prose."""
from datetime import datetime, timedelta, timezone
import json
from zoneinfo import ZoneInfo

from icalendar import Calendar, Event
import pytest

from roomquest.event_description import description


# Exact complete first section from source 5416's staged Sip & Shop description,
# captured 2026-11-13. The raw feed was unavailable to this workspace (DNS).
# Tests append explicitly synthetic prose; this is not a raw publisher replay.
_DOORWAYS_LAYOUT_PREFIX = (
    "[vc_section]"
    "[vc_row]"
    "[vc_column column_width_percent=”75″ position_vertical=”middle” align_horizontal=”align_center” gutter_size=”3″ overlay_alpha=”50″ shift_x=”0″ shift_y=”0″ shift_y_down=”0″ z_index=”0″ medium_width=”0″ mobile_width=”0″ width=”1/1″ uncode_shortcode_id=”144893″]"
    "[vc_custom_heading auto_text=”yes” uncode_shortcode_id=”183357″]"
    "[/vc_custom_heading]"
    "[/vc_column]"
    "[/vc_row]"
    "[vc_row row_height_percent=”0″ override_padding=”yes” h_padding=”2″ top_padding=”1″ bottom_padding=”1″ overlay_alpha=”50″ gutter_size=”3″ column_width_percent=”100″ shift_y=”0″ z_index=”0″ uncode_shortcode_id=”740637″]"
    "[vc_column column_width_percent=”75″ position_vertical=”middle” align_horizontal=”align_center” gutter_size=”3″ overlay_alpha=”50″ shift_x=”0″ shift_y=”0″ shift_y_down=”0″ z_index=”0″ medium_width=”0″ mobile_width=”0″ width=”1/1″ uncode_shortcode_id=”984963″]"
    "[vc_row_inner]"
    "[vc_column_inner width=”1/4″]"
    "[/vc_column_inner]"
    "[vc_column_inner column_width_percent=”100″ align_horizontal=”align_center” gutter_size=”1″ overlay_alpha=”50″ shift_x=”0″ shift_y=”0″ shift_y_down=”0″ z_index=”0″ medium_width=”0″ mobile_width=”0″ width=”1/4″ uncode_shortcode_id=”737580″]"
    "[vc_custom_heading text_size=”h6″ uncode_shortcode_id=”212679″]When[/vc_custom_heading]"
    "[vc_column_text uncode_shortcode_id=”739807″]December 1, 2026\n5:00pm to 7:00pm[/vc_column_text]"
    "[/vc_column_inner]"
    "[vc_column_inner column_width_percent=”100″ align_horizontal=”align_center” gutter_size=”1″ overlay_alpha=”50″ shift_x=”0″ shift_y=”0″ shift_y_down=”0″ z_index=”0″ medium_width=”0″ mobile_width=”0″ width=”1/4″ uncode_shortcode_id=”180633″]"
    "[vc_custom_heading text_size=”h6″ uncode_shortcode_id=”673094″]Where[/vc_custom_heading]"
    "[vc_column_text uncode_shortcode_id=”175872″]The Shops at 5807\n5807 Patterson Avenue\nRichmond, VA 23226[/vc_column_text]"
    "[/vc_column_inner]"
    "[vc_column_inner width=”1/4″]"
    "[/vc_column_inner]"
    "[/vc_row_inner]"
    "[/vc_column]"
    "[/vc_row]"
    "[/vc_section]"
)
_DOORWAYS_VISIBLE_PREFIX = (
    'When\nDecember 1, 2026\n5:00pm to 7:00pm\nWhere\n'
    'The Shops at 5807\n5807 Patterson Avenue\nRichmond, VA 23226'
)


def _doorways_fixture(narrative):
    # Extra layout ensures useful copy starts beyond the former 2,000-char cap.
    padding = (
        '[vc_row row_height_percent="0" override_padding="yes" h_padding="2" '
        'top_padding="1" bottom_padding="1"]'
        '[vc_column width="1/1"][/vc_column][/vc_row]'
    )
    raw = (
        _DOORWAYS_LAYOUT_PREFIX + padding + '[vc_column_text]'
        + narrative + '[/vc_column_text]'
    )
    assert raw.index(narrative) > 2000
    return raw, _DOORWAYS_VISIBLE_PREFIX + '\n' + narrative


@pytest.mark.parametrize('limit', [2000, 12000])
def test_observed_layout_is_removed_before_description_bounding(limit):
    narrative = 'Synthetic fixture: participants make paper lanterns. ' * 300
    narrative = narrative.strip()
    raw, expected = _doorways_fixture(narrative)

    cleaned = description(raw, limit=limit)

    assert cleaned == expected[:limit]
    assert len(cleaned) == limit
    assert 'Synthetic fixture: participants make paper lanterns.' in cleaned
    assert '[vc_' not in cleaned
    assert 'uncode_shortcode_id' not in cleaned


@pytest.mark.parametrize('raw,expected', [
    (
        '[vc_section][vc_row][vc_column][vc_column_text]<p>Bring art supplies.</p>'
        '[/vc_column_text][/vc_column][/vc_row][/vc_section]',
        'Bring art supplies.',
    ),
    (
        '[vc_custom_heading text_size="h6"]Workshop[/vc_custom_heading]'
        '[vc_empty_space height="20px" /][vc_separator][/vc_separator]'
        '[vc_single_image image="123"]'
        '[vc_btn title="Read more" link="url:https://publisher.example/info"]'
        '[vc_button title="Register"][vc_icon icon="fa-star"]',
        'Workshop',
    ),
    (
        '[VC_ROW][VC_COLUMN_TEXT]No cover.[/VC_COLUMN_TEXT][/VC_ROW]',
        'No cover.',
    ),
    (
        '[vc_column_text]Bring a board game. https://publisher.example/info'
        '[/vc_column_text]',
        'Bring a board game. https://publisher.example/info',
    ),
    (
        '[vc_column_text]https://publisher.example/info[/vc_column_text]',
        '',
    ),
    ('[vc_section][vc_row][vc_column][/vc_column][/vc_row][/vc_section]', ''),
])
def test_recognized_layout_controls_preserve_enclosed_content(raw, expected):
    assert description(raw) == expected


@pytest.mark.parametrize('text', [
    'Bring supplies [optional]. Ages [8+].',
    '[Registration opens Friday] Meet at the garden gate.',
    '[Register](https://publisher.example/info) to reserve art supplies.',
    '[vc_row_label]Local workshop[/vc_row_label]',
    '[vc_unrecognized title="Keep this"]Event copy[/vc_unrecognized]',
    '[et_pb_notice]Event reminder[/et_pb_notice]',
    '[et_pb_textbook]Community reading[/et_pb_textbook]',
])
def test_arbitrary_brackets_and_unknown_shortcodes_are_preserved(text):
    assert description(text) == text


def test_doorways_generic_ics_route_preserves_event_identity_and_sanitizes(monkeypatch):
    from roomquest import preview_worker

    feed = 'https://www.thedoorways.org/events/?ical=1'
    event_url = 'https://www.thedoorways.org/events/sip-shop-at-the-shops-at-5807-3/'
    narrative = ('Synthetic fixture: participants make paper lanterns. ' * 50).strip()
    raw, expected = _doorways_fixture(narrative)
    calendar = Calendar()
    calendar.add('version', '2.0')
    event = Event()
    event.add('uid', 'doorways-shortcode-fixture')
    event.add('summary', 'Sip & Shop at The Shops at 5807')
    event.add('dtstart', datetime.now(timezone.utc) + timedelta(days=2))
    event.add('location', 'The Shops at 5807')
    event.add('geo', (37.58, -77.51))
    event.add('url', event_url)
    event.add('description', raw)
    calendar.add_component(event)
    calls = []

    def fetch(url, accept, **kwargs):
        calls.append((url, accept))
        return calendar.to_ical().decode()

    monkeypatch.setattr(preview_worker, 'fetch_publisher', fetch)
    result = preview_worker.preview_source({
        'source_key': 'the_doorways_richmond_events_va', 'feed_url': feed,
        'timezone': 'America/New_York', 'kind': 'ical', 'platform_adapter': 'ical',
    })

    row, = result['p_events']
    assert row['description'] == expected[:2000]
    assert row['id'] == 'doorways-shortcode-fixture'
    assert row['event_url'] == event_url
    assert row['title'] == 'Sip & Shop at The Shops at 5807'
    assert calls == [(feed, 'text/calendar')]


# Exact prefix, suffix and enclosed plain text from normalized staged row
# 239141 (Hurrdat), captured 2026-11-13. This is not a raw API replay.
# The long-boundary test below explicitly substitutes synthetic narrative.
_HURRDAT_DIVI_PREFIX = (
    "[et_pb_section fb_built=”1″ admin_label=”section” _builder_version=”4.16″ global_colors_info=”{}” theme_builder_area=”post_content” da_is_popup=”off” da_exit_intent=”off” da_has_close=”on” da_alt_close=”off” da_dark_close=”off” da_not_modal=”on” da_is_singular=”off” da_with_loader=”off” da_has_shadow=”on” da_disable_devices=”off|off|off”]"
    "[et_pb_row admin_label=”row” _builder_version=”4.16″ background_size=”initial” background_position=”top_left” background_repeat=”repeat” global_colors_info=”{}” theme_builder_area=”post_content”]"
    "[et_pb_column type=”4_4″ _builder_version=”4.16″ custom_padding=”|||” global_colors_info=”{}” custom_padding__hover=”|||” theme_builder_area=”post_content”]"
    "[et_pb_text admin_label=”Text” _builder_version=”4.16″ background_size=”initial” background_position=”top_left” background_repeat=”repeat” global_colors_info=”{}” theme_builder_area=”post_content”]"
)
_HURRDAT_DIVI_SUFFIX = (
    "[/et_pb_text]"
    "[/et_pb_column]"
    "[/et_pb_row]"
    "[et_pb_row _builder_version=”4.27.9″ _module_preset=”default” theme_builder_area=”post_content”]"
    "[et_pb_column _builder_version=”4.27.9″ _module_preset=”default” type=”4_4″ theme_builder_area=”post_content”]"
    "[et_pb_code _builder_version=”4.27.9″ _module_preset=”default” theme_builder_area=”post_content” hover_enabled=”0″ sticky_enabled=”0″]\n[/et_pb_code]"
    "[/et_pb_column]"
    "[/et_pb_row]"
    "[/et_pb_section]"
)
_HURRDAT_VISIBLE_PROSE = "Monthly Omaha Trivia Night\npresented by Hurrdat One\nThink you know Omaha? Prove it.\nJoin Hurrdat ONE for\nOmaha Trivia Night at Hurrdat Sports Bar & Grill.\nA live trivia experience all about the people, places, history, food, sports, nostalgia and local lore that make Omaha, Omaha! You can expect traditional trivia mixed with photos, audio, old-school jingles and plenty of questions that will have your team saying, “I remember that!”\nBring your crew, grab some food and drinks, and put your Omaha knowledge to the test.\nEvery Second Wednesday of the Month | Trivia starts at 7:00 PM | Doors at 6:30 PM"


def _hurrdat_item(narrative):
    from roomquest import hurrdat_calendar

    start = (datetime.now(timezone.utc) + timedelta(days=2)).replace(microsecond=0)
    end = start + timedelta(hours=2)
    zone = ZoneInfo(hurrdat_calendar.ZONE)
    return {
        'id': 271417, 'title': 'Monthly Omaha Trivia Night presented by Hurrdat One!',
        'status': 'publish', 'timezone': hurrdat_calendar.ZONE,
        'url': 'https://hurrdatsportsbar.com/event/monthly-omaha-trivia-night-presented-by-hurrdat-one-3/',
        'start_date': start.astimezone(zone).replace(tzinfo=None).isoformat(),
        'end_date': end.astimezone(zone).replace(tzinfo=None).isoformat(),
        'utc_start_date': start.isoformat(), 'utc_end_date': end.isoformat(),
        'description': narrative,
        'venue': {
            'venue': 'Hurrdat Sports Bar & Grill – La Vista',
            'address': '12744 Westport Pkwy', 'city': 'Omaha', 'state': 'NE',
            'zip': '68138',
        },
    }


def test_hurrdat_wordpress_preview_cleans_observed_divi_and_preserves_facts(monkeypatch):
    from roomquest import hurrdat_calendar, preview_worker

    item = _hurrdat_item(
        _HURRDAT_DIVI_PREFIX + '\n' + _HURRDAT_VISIBLE_PROSE + '\n' + _HURRDAT_DIVI_SUFFIX)
    assert len(item['description']) == 1931
    calls = []

    def fetch(url, accept, **kwargs):
        calls.append((url, accept, kwargs))
        return json.dumps({'events': [item], 'total_pages': 1})

    monkeypatch.setattr(preview_worker, 'fetch_publisher', fetch)
    result = preview_worker.preview_source({
        'source_key': hurrdat_calendar.KEY, 'feed_url': hurrdat_calendar.URL,
        'kind': 'json', 'platform_adapter': 'wordpress', 'timezone': hurrdat_calendar.ZONE,
    })

    row, = result['p_events']
    assert row['description'] == _HURRDAT_VISIBLE_PROSE
    assert row['id'] == '271417'
    assert row['title'] == item['title']
    assert row['event_url'] == item['url']
    assert (row['starts_at'], row['ends_at']) == (item['utc_start_date'], item['utc_end_date'])
    assert row['venue_name'] == 'Hurrdat Sports Bar & Grill – La Vista'
    assert row['venue_address'] == '12744 Westport Pkwy Ste 1A, La Vista, NE, 68138'
    assert row['venue_city'] == 'La Vista'
    assert row['lat'] is None and row['lng'] is None
    assert len(calls) == 1
    assert calls[0][0].startswith(hurrdat_calendar.URL + '?')
    assert calls[0][1] == 'application/json'
    assert calls[0][2]['respect_robots']


@pytest.mark.parametrize('limit', [2000, 12000])
def test_divi_layout_is_removed_before_the_description_limit(limit):
    narrative = ('Synthetic fixture: teams answer local history questions. ' * 300).strip()
    # Repeat the observed layout so the useful text begins after character 2,000.
    raw = _HURRDAT_DIVI_PREFIX * 3 + narrative + _HURRDAT_DIVI_SUFFIX * 3
    assert raw.index(narrative) > 2000
    assert description(raw, limit=limit) == narrative[:limit]


def test_wordpress_parser_uses_shared_cleaning_before_its_existing_limit():
    from roomquest.mapsee_adapter import parse_tribe

    narrative = ('Synthetic fixture: teams answer local history questions. ' * 60).strip()
    raw = _HURRDAT_DIVI_PREFIX * 3 + narrative + _HURRDAT_DIVI_SUFFIX * 3
    row, = parse_tribe({'events': [_hurrdat_item(raw)]},
                      strict_public=True, retain_description=True)
    assert row['description'] == narrative[:2000]


@pytest.mark.parametrize('raw,expected', [
    ('[et_pb_text]No cover.[/et_pb_text]', 'No cover.'),
    (
        '[et_pb_text]Bring a team. https://publisher.example/info[/et_pb_text]',
        'Bring a team. https://publisher.example/info',
    ),
    ('[et_pb_text]https://publisher.example/info[/et_pb_text]', ''),
    (
        '[ET_PB_SECTION][ET_PB_ROW][ET_PB_COLUMN][ET_PB_TEXT]'
        '<p>Join the trivia game.</p>[/ET_PB_TEXT][ET_PB_CODE]'
        '<script>tracking()</script><style>.widget { color: red; }</style>'
        '[/ET_PB_CODE][/ET_PB_COLUMN][/ET_PB_ROW][/ET_PB_SECTION]',
        'Join the trivia game.',
    ),
])
def test_divi_prose_links_and_embedded_code_are_handled_without_extra_content(raw, expected):
    assert description(raw) == expected


@pytest.mark.parametrize('invalid', [0, [], {}])
def test_wordpress_description_validation_error_is_unchanged(invalid):
    from roomquest.mapsee_adapter import parse_tribe

    with pytest.raises(ValueError, match='^invalid_wordpress_description$'):
        parse_tribe({'events': [_hurrdat_item(invalid)]},
                    strict_public=True, retain_description=True)
