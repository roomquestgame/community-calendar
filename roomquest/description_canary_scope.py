"""Explicit process-local scope for the ten-feed private staging experiment.

No environment flag or publisher input can enable this scope. Production entry
points never call it. It changes narrative limits, not access or publication.
"""
from contextlib import contextmanager
from contextvars import ContextVar

SOURCE_KEYS = frozenset((
    'municipal_mapsee_e701e9e414d90b3dd7c28372',
    'municipal_mapsee_76b81f64b3833a4e18382a92',
    'municipal_mapsee_596d8adec09fb63c63d0ec8c',
    'municipal_mapsee_0067c97a79c6399c79eda7b2',
    'municipal_mapsee_58f2b9a6a8c91f848193aecc',
    'municipal_mapsee_f63b83aa136931e0a77618b3',
    'municipal_mapsee_f805b83dcb7b49a7b56ca68a',
    'omaha_public_library_biblioevents_ne',
    'lincoln_city_libraries_localhop_ne',
    'atlantic_county_library_nj',
))
_source = ContextVar('private_description_canary_source', default=None)


def active():
    return _source.get() in SOURCE_KEYS


@contextmanager
def full_description_scope(source_key):
    if source_key not in SOURCE_KEYS:
        raise ValueError('source_not_in_description_canary')
    token = _source.set(source_key)
    try:
        yield
    finally:
        _source.reset(token)


def retain(value, limit):
    """No silent clipping inside the private experiment; legacy default outside."""
    return value if active() else value[:limit]


def repair_c1(value):
    """Repair only defined Windows-1252 punctuation encoded as C1 controls.

    Other characters and undefined bytes are preserved for explicit review.
    """
    result = []
    for char in value:
        if 0x80 <= ord(char) <= 0x9f:
            try:
                char = bytes((ord(char),)).decode('cp1252')
            except UnicodeDecodeError:
                pass
        result.append(char)
    return ''.join(result)
