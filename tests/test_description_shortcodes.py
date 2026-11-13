"""Remove publisher layout shortcodes while preserving event prose."""
from datetime import datetime, timedelta, timezone

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

