import pytest
from roomquest.description_canary_scope import SOURCE_KEYS, active, full_description_scope, repair_c1
from roomquest.event_description import description
from scripts.description_canary import collect_pair, review_reason

KEY = next(iter(SOURCE_KEYS))


def test_complete_text_and_legacy_limit_and_cleanup():
    text = 'Publisher narrative. ' * 1000
    assert len(description(text)) == 2000
    with full_description_scope(KEY):
        assert description('<p>' + text + '</p><script>bad()</script>') == text.strip()
        assert description(None) == ''
        assert description('') == ''
    assert not active()
    assert len(description(text)) == 2000


def test_scope_restores_on_error_and_rejects_other_feeds():
    with pytest.raises(ValueError):
        with full_description_scope('not-approved-for-canary'):
            pass
    with pytest.raises(RuntimeError):
        with full_description_scope(KEY):
            raise RuntimeError()
    assert not active()


def test_encoding_is_narrow_and_bilingual_preserved():
    assert repair_c1('We\x92ll meet — ¡Música! 中文') == 'We’ll meet — ¡Música! 中文'
    assert repair_c1('plain \x81') == 'plain \x81'


def test_cancellations_are_quarantined_not_date_rewritten():
    assert review_reason({'title': 'CANCELED - Storytime'})
    assert review_reason({'title': 'Rescheduled: workshop'})
    assert not review_reason({'title': 'Free workshop'})


def test_live_pair_replays_same_response_without_second_fetch(monkeypatch):
    from roomquest import preview_worker as worker
    calls = []
    def transport(url, accept, **kwargs):
        calls.append(url)
        return 'X' * 15000
    def preview(source, **kwargs):
        raw = worker._fetch_publisher_request('https://example.org/feed', 'text/calendar')
        return {'p_events': [{'id': 'same', 'starts_at': '2026-12-01T12:00:00Z',
                            'title': 'Workshop', 'description': description(raw)}]}
    monkeypatch.setattr(worker, '_fetch_publisher_request', transport)
    monkeypatch.setattr(worker, 'preview_source', preview)
    before, after, receipts = collect_pair({'source_key': KEY})
    assert calls == ['https://example.org/feed']
    assert len(before[0]['description']) == 2000
    assert len(after[0]['description']) == 15000
    assert len(receipts) == 1


def test_canary_cannot_call_production_rpc(monkeypatch):
    from roomquest import preview_worker as worker
    monkeypatch.setattr(worker, 'preview_source', lambda *a, **k: worker.supabase_rpc('write', {}))
    with pytest.raises(RuntimeError, match='production_rpc_forbidden'):
        collect_pair({'source_key': KEY})
