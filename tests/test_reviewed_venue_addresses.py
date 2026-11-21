from roomquest.reviewed_venue_addresses import complete_address, SWEET_BRIAR, SWEET_BRIAR_KEY

SOURCE = {'url': SWEET_BRIAR, 'source_key': SWEET_BRIAR_KEY}


def test_named_campus_venues_receive_address_without_coordinates():
    for venue in ['Mills Chapel', 'Upchurch Field House (all)', 'Prothro Natatorium (all lanes)']:
        row = {'venue_name': venue, 'venue_address': venue, 'lat': None, 'lng': None}
        complete_address(row, SOURCE)
        assert row['venue_name'] == venue
        assert row['venue_address'] == '134 Chapel Road, Sweet Briar, VA 24595'
        assert row['lat'] is None and row['lng'] is None


def test_unknown_offsite_address_and_source_scope_are_preserved():
    for row, source in [
        ({'venue_name': 'Off-Campus Event'}, SOURCE),
        ({'venue_name': 'Archery'}, SOURCE),
        ({'venue_name': 'Mills Chapel', 'venue_address': '12 Different Street'}, SOURCE),
        ({'venue_name': 'Mills Chapel', 'lat': 37.5}, SOURCE),
        ({'venue_name': 'Mills Chapel'}, {**SOURCE, 'source_key': 'other'}),
        ({'venue_name': 'Mills Chapel'}, {**SOURCE, 'url': SWEET_BRIAR + '&cid=2'}),
    ]:
        before = dict(row)
        complete_address(row, source)
        assert row == before
