import pytest
from roomquest.venue_research_address import (
    valid_region, postcode, gb_candidates, uk_address, us_region_evidenced,
)

SCOPE = {"venue": "Nottingham Playhouse", "locality": "Nottingham", "country": "GB", "region": "GB"}
QUOTE = "Nottingham Playhouse\nWellington Circus, Nottingham, NG1 5AL"


def uk(street="Wellington Circus", locality="Nottingham", postal="NG1 5AL", quote=QUOTE, passages=None, scope=SCOPE):
    return uk_address(scope, street, locality, postal, quote, [quote] if passages is None else passages)


def test_uk_street_without_number():
    assert uk() == "Wellington Circus, Nottingham, NG1 5AL"


def test_compact_postcode_and_numbered_street():
    q = "Nottingham Playhouse\n25 Wellington Road, Nottingham NG15AL"
    assert uk(street="25 Wellington Road", postal="NG15AL", quote=q) == "25 Wellington Road, Nottingham, NG1 5AL"


@pytest.mark.parametrize("kw", [
    {"street": "1 Wellington Circus"}, {"locality": "Derby"},
    {"postal": "NG2 9AA"}, {"postal": ""}, {"quote": "Nottingham Playhouse\nNG1 5AL"},
    {"passages": [QUOTE, "Nottingham Playhouse\nOther Road, Nottingham, NG2 9AA"]},
    {"passages": [QUOTE, "Nottingham Playhouse\nOther Road, Nottingham, NG1 5AL"]},
    {"scope": {**SCOPE, "country": "US"}}, {"quote": "Another theatre\nWellington Circus, Nottingham, NG1 5AL"},
])
def test_rejects_wrong_scope_or_unsupported_or_conflicting_evidence(kw):
    assert uk(**kw) is None


def test_scope_and_us_region():
    assert valid_region("US", "VA") and valid_region("GB", "GB")
    assert not valid_region("US", "GB") and not valid_region("US", "ZZ")
    assert not valid_region("GB", "NY")
    assert us_region_evidenced("123 Main Street, Richmond, VA 23219", "Richmond", "VA")
    assert us_region_evidenced("Richmond VA 23219", "Richmond", "VA")
    assert not us_region_evidenced("123 Main Street Richmond, MO 64085", "Richmond", "VA")
    assert not us_region_evidenced("Meet in Richmond in the evening", "Richmond", "IN")


def test_postcode_only_does_not_supply_street():
    assert postcode("E146TL") == "E14 6TL"
    assert not gb_candidates("Nottingham, NG1 5AL", "Nottingham")
