"""Opt-in request accounting for evergreen workers; legacy transports unchanged."""
from contextlib import contextmanager
from contextvars import ContextVar

_admission = ContextVar('activity_request_admission', default=None)


@contextmanager
def admitted_requests(reserve):
    state = {'reserve': reserve, 'primary': 0, 'redirects': 0}
    token = _admission.set(state)
    try:
        yield state
    finally:
        _admission.reset(token)


def before_request(url, *, auxiliary=False, redirect=False):
    state = _admission.get()
    if state is None:
        return
    if redirect:
        state['redirects'] += 1
        if state['redirects'] > 3:
            raise ValueError('activity_redirect_limit')
    kind = 'auxiliary' if auxiliary or redirect else 'page'
    result = state['reserve'](kind, url)
    if not isinstance(result, dict) or result.get('status') != 'reserved':
        raise ValueError('activity_request_not_admitted')
    if kind == 'page':
        state['primary'] += 1
