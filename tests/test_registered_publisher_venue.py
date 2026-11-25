from bs4 import BeautifulSoup

from roomquest import registered_publisher_venue as venue


def test_same_host_contact_link_and_exact_publisher_address():
    page = BeautifulSoup('<a href="/contact/">Contact</a>', 'html.parser')
    assert venue.contact_link(page, 'https://venue.example/events/one') == {
        'https://venue.example/contact/'}
    rows = [{"venue_name": "Example Venue — Studio", "venue_address": "",
             "venue_city": "London"}]
    contact = ('<meta property="og:site_name" content="Example Venue">'
               '<main>Addresses: Example Venue, 65-67 Peckham Rd, London, SE5 8UH</main>')
    [row] = venue.apply(rows, contact, 'https://venue.example/contact/')
    assert row["venue_address"] == "65-67 Peckham Rd, London, SE5 8UH, United Kingdom"
    assert row["publisher_details"]["venue_address_evidence_url"] == (
        'https://venue.example/contact/')


def test_footer_phone_number_is_not_absorbed_into_the_street_address():
    contact = ('<meta property="og:site_name" content="Example Venue">'
               '<footer><span>Box office</span><a>020 7613 7498</a>'
               '<span>35-47 Bethnal Green Road, London, E1 6LA</span></footer>')
    [row] = venue.apply([{'venue_name': 'Example Venue'}], contact,
                        'https://venue.example/events/')
    assert row['venue_address'] == (
        '35-47 Bethnal Green Road, London, E1 6LA, United Kingdom')


def test_offsite_or_ambiguous_contact_address_stays_unresolved():
    rows = [{"venue_name": "Other Hall", "venue_address": ""}]
    contact = ('<meta property="og:site_name" content="Example Venue">'
               '<p>Example Venue 1 High Street London SW4 0QW</p>')
    assert venue.apply(rows, contact, 'https://venue.example/contact/') is None
    own = [{"venue_name": "Example Venue", "venue_address": ""}]
    two = contact + '<p>Example Venue 2 High Street London SW4 0QW</p>'
    assert venue.apply(own, two, 'https://venue.example/contact/') is None


def test_contact_candidates_reject_foreign_query_and_keep_one_exact_page():
    soup = BeautifulSoup(
        '<a href="https://other.example/contact">Contact</a>'
        '<a href="/contact?ref=event">Contact us</a>'
        '<a href="/visit/">Visit us</a>', 'html.parser')
    assert venue.contact_link(soup, 'https://venue.example/events/') == {
        'https://venue.example/visit/'}


def test_contact_identity_collapses_only_optional_trailing_slash():
    assert venue.contact_identity('https://venue.example/contact') == (
        'https', 'venue.example', '/contact')
    assert venue.contact_identity('https://venue.example/contact/') == (
        'https', 'venue.example', '/contact')
    assert venue.contact_identity('https://venue.example/visit-us') != (
        venue.contact_identity('https://venue.example/contact/'))
