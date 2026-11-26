from datetime import date

from bs4 import BeautifulSoup
import pytest

from roomquest.feed_registration import classify
from roomquest.registered_listings import MAINE_JEWISH, maine_jewish


def page(extra=''):
    return f'''<html><body class="page page-id-2591"><ul class="columns x2">
      <li class="p-3 align-m"><div class="p-3">
        <h3 class="pb-2 uppercase">Chanukah in New Vaudeville!</h3><div>
        <p><strong>Thursday, December 3, 2026</strong><br>
        <strong>Doors &amp; Social Hour: 6:00 pm | Performance: 7:00 pm</strong><br>
        <strong>The Gem Theater | 48 Cross Street, Bethel, Maine</strong></p>
        <p>A public holiday performance for the community.</p>
        <a class="button slim" href="https://mainejewishmuseum.org/chanukah-in-new-vaudeville/">More Information</a>
        </div></div></li>{extra}</ul></body></html>'''


def test_home_follows_live_program_archive_instead_of_stale_tec_assets():
    home = ('<html><a href="https://mainejewishmuseum.org/programs-and-events/">Programs & Events</a>'
            '<link href="/wp-content/plugins/the-events-calendar/events.css"></html>')
    assert classify('https://mainejewishmuseum.org/', home) == {'calendar_page': MAINE_JEWISH}


def test_program_archive_collects_exact_public_card():
    [row] = list(maine_jewish(BeautifulSoup(page(), 'html.parser'), date(2026, 11, 26)))
    assert row['title'] == 'Chanukah in New Vaudeville!'
    assert row['starts_at'] == '2026-12-03T23:00:00+00:00'
    assert row['ends_at'] == '2026-12-04T00:00:00+00:00'
    assert row['venue_address'] == '48 Cross Street, Bethel, ME 04217'


def test_program_archive_rejects_unknown_cards():
    unknown = '<li class="p-3 align-m"><h3 class="pb-2 uppercase">Unknown</h3></li>'
    with pytest.raises(ValueError, match='maine_jewish_program_card_changed'):
        list(maine_jewish(BeautifulSoup(page(unknown), 'html.parser'), date(2026, 11, 26)))
