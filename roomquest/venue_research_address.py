"""Country-aware, evidence-only address validation for the shared venue worker."""
from __future__ import annotations

import re
import unicodedata

US_REGIONS = frozenset("AL AK AZ AR CA CO CT DE DC FL GA HI ID IL IN IA KS KY LA ME MD MA MI MN MS MO MT NE NV NH NJ NM NY NC ND OH OK OR PA RI SC SD TN TX UT VT VA WA WV WI WY".split())
GB_POSTCODE = re.compile(r"\b(?:GIR\s?0AA|[A-Z]{1,2}[0-9][A-Z0-9]?\s?[0-9][A-Z]{2})\b", re.I)
GB_STREET_SUFFIX = r"(?:street|st|road|rd|lane|ln|avenue|ave|drive|dr|close|cl|way|court|ct|place|pl|square|sq|terrace|ter|circus|crescent|grove|walk|row|gardens?|hill|northside|southside|eastside|westside)"
GB_STREET = rf"(?:\d{{1,5}}[A-Za-z]?(?:-\d{{1,5}}[A-Za-z]?)?\s+)?[A-Za-z][A-Za-z0-9.'’ &-]{{0,95}}?\b{GB_STREET_SUFFIX}\.?"


def norm(value):
    return re.sub(r"[^a-z0-9]+", " ", unicodedata.normalize(
        "NFKD", str(value or "")).encode("ascii", "ignore").decode().lower()).strip()


def contains(text, phrase):
    return bool(norm(phrase)) and (" " + norm(phrase) + " ") in (" " + norm(text) + " ")


def valid_region(country, region):
    return (country == "US" and region in US_REGIONS) or (country == "GB" and region == "GB")


def postcode(value):
    if not isinstance(value, str) or not GB_POSTCODE.fullmatch(value.strip()):
        return None
    compact = re.sub(r"\s+", "", value.upper())
    return compact[:-3] + " " + compact[-3:]


def gb_candidates(text, locality):
    """Extract explicit address blocks. No postcode-only or invented street.

    Newlines preserve publisher block boundaries; the town must immediately
    follow the street component and the postcode must be present on the page.
    """
    if not isinstance(text, str) or not isinstance(locality, str) or not locality.strip():
        return set()
    city = r"[ \t]+".join(re.escape(t) for t in locality.split())
    pattern = re.compile(
        rf"(?:^|[\n:;,])\s*(?P<street>{GB_STREET})\s*,?\s+{city}"
        rf"\s*,?\s+(?P<postal>{GB_POSTCODE.pattern})", re.I | re.M)
    return {(norm(m.group("street")), postcode(m.group("postal"))) for m in pattern.finditer(text)}


def us_region_evidenced(quote, locality, region):
    """US generic permits must have the supplied state in the address itself."""
    city = r"\s+".join(re.escape(t) for t in locality.split())
    # Case-sensitive postal abbreviation avoids treating 'in' or 'or' as states.
    return bool(re.search(rf"(?i:{city})\s*,\s*{re.escape(region)}\b", quote)
                or re.search(rf"(?i:{city})\s+{re.escape(region)}\s+\d{{5}}\b", quote))


def uk_address(scope, street, locality, postal, quote, passages):
    """Accept one independently parsed UK street/postcode pair, verbatim."""
    p = postcode(postal)
    if (scope.get("country") != "GB" or scope.get("region") != "GB" or p is None
            or norm(locality) != norm(scope.get("locality"))
            or not 3 <= len(street) <= 120
            or not re.fullmatch(GB_STREET, street.strip(), re.I)
            or any(t in street.casefold() for t in ("p.o. box", "po box", "virtual"))
            or not contains(quote, scope.get("venue"))
            or not contains(quote, street) or not contains(quote, locality)):
        return None
    # Compare normalized postcode explicitly, allowing publisher compact form.
    if p not in {postcode(m.group()) for m in GB_POSTCODE.finditer(quote)}:
        return None
    all_postcodes = {postcode(m.group()) for text in passages for m in GB_POSTCODE.finditer(text)}
    all_streets = set().union(*(gb_candidates(text, locality) for text in passages))
    if all_postcodes != {p} or all_streets != {(norm(street), p)}:
        return None
    if (norm(street), p) not in gb_candidates(quote, locality):
        return None
    return f"{street.strip()}, {locality.strip()}, {p}"
