"""Focused no-network tests for enrolled ICS parser rule fingerprints."""
from pathlib import Path
import re

from roomquest import incremental_snapshot as inc


PILOT = {
    "kind": "ical", "platform_adapter": "ical",
    "ical_optimization_enabled": True,
    "source_key": "municipal_df6fb09e5e9df3f197946372",
}


def _fixture(root: Path):
    (root / "roomquest").mkdir()
    (root / "scripts").mkdir()
    for name in inc._SCOPED_ICAL_FILES:
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("VALUE = 'current'\n", encoding="utf-8")
    names = inc._SCOPED_ICAL_PREVIEW_FUNCTIONS
    functions = "".join(
        f"def {name}(*args, **kwargs):\n    return 'stable'\n\n"
        for name in names
    )
    (root / "roomquest/preview_worker.py").write_text(
        functions +
        """def preview_source(source):
    if source.get("kind", "ical") == "ical" and source.get("platform_adapter") == "ical":
        return "primary-ics"
    adapter = source.get("platform_adapter")
    if adapter == "other":
        return 0
    adapter = source.get("platform_adapter") or "unknown"
    if adapter == "ical":
        return "ics"
    return "other"
""", encoding="utf-8")


def test_real_checked_in_ical_dependencies_are_complete():
    # The actual current package must not silently fall through to the broad
    # parser hash. Fail if a new deployment changes the generic ICS structure
    # beyond what the scoped parser knows how to fingerprint.
    value = inc._scoped_ical_parser_context()
    assert isinstance(value, str) and re.fullmatch(r"[0-9a-f]{64}", value)


def test_unrelated_module_and_unrelated_preview_branch_do_not_invalidate(tmp_path):
    _fixture(tmp_path)
    baseline = inc._scoped_ical_parser_digest(tmp_path)
    assert baseline is not None
    (tmp_path / "roomquest/unrelated_london_adapter.py").write_text(
        "UNRELATED = 'new'\n", encoding="utf-8")
    assert inc._scoped_ical_parser_digest(tmp_path) == baseline

    preview = tmp_path / "roomquest/preview_worker.py"
    contents = preview.read_text("utf-8")
    preview.write_text(contents.replace(
        '    if adapter == "other":\n        return 0',
        '    if adapter == "other":\n        return 6'
    ), encoding="utf-8")
    assert inc._scoped_ical_parser_digest(tmp_path) == baseline


def test_shared_ics_normalizer_change_invalidates(tmp_path):
    _fixture(tmp_path)
    baseline = inc._scoped_ical_parser_digest(tmp_path)
    preview = tmp_path / "roomquest/preview_worker.py"
    contents = preview.read_text("utf-8")
    preview.write_text(contents.replace(
        "def parse_ics_preview(*args, **kwargs):\n    return 'stable'",
        "def parse_ics_preview(*args, **kwargs):\n    return 'changed'"
    ), encoding="utf-8")
    assert inc._scoped_ical_parser_digest(tmp_path) != baseline


def test_ics_dispatch_or_recurrence_module_change_invalidates(tmp_path):
    _fixture(tmp_path)
    baseline = inc._scoped_ical_parser_digest(tmp_path)
    preview = tmp_path / "roomquest/preview_worker.py"
    contents = preview.read_text("utf-8")
    preview.write_text(contents.replace('return "ics"', 'return "different"'), encoding="utf-8")
    assert inc._scoped_ical_parser_digest(tmp_path) != baseline

    preview.write_text(contents, encoding="utf-8")
    recurrence = tmp_path / "scripts/combine_ics.py"
    recurrence.write_text("VALUE = 'changed'\n", encoding="utf-8")
    assert inc._scoped_ical_parser_digest(tmp_path) != baseline



def test_primary_ical_route_change_invalidates_even_when_generic_tail_unchanged(tmp_path):
    _fixture(tmp_path)
    baseline = inc._scoped_ical_parser_digest(tmp_path)
    assert baseline is not None
    preview = tmp_path / "roomquest/preview_worker.py"
    body = preview.read_text("utf-8").replace(
        'return "primary-ics"', 'return "different-ical-parser"')
    preview.write_text(body, encoding="utf-8")
    assert inc._scoped_ical_parser_digest(tmp_path) != baseline



def test_missing_dependency_or_dispatch_falls_back(tmp_path):
    _fixture(tmp_path)
    (tmp_path / "roomquest/reviewed_venue_addresses.py").unlink()
    assert inc._scoped_ical_parser_digest(tmp_path) is None

    _fixture2 = tmp_path / "next"
    _fixture(_fixture2)
    preview = _fixture2 / "roomquest/preview_worker.py"
    preview.write_text("def preview_source(source): return []\n", encoding="utf-8")
    assert inc._scoped_ical_parser_digest(_fixture2) is None


def test_scope_only_applies_to_exact_approved_ical_profile(monkeypatch):
    monkeypatch.setattr(inc, "_global_parser_context", lambda: "global")
    monkeypatch.setattr(inc, "_scoped_ical_parser_context", lambda: "specific")
    from roomquest.ical_source_semantics import NORMALIZATION_VERSION
    assert inc.parser_context(PILOT) == inc.fingerprint({
        "protocol": "ical-publisher-facts-v1", "normalization": NORMALIZATION_VERSION})
    assert inc.parser_context({**PILOT, "source_key": "municipal_mapsee_0123456789abcdef01234567"}) == inc.parser_context(PILOT)
    assert inc.parser_context({**PILOT, "source_key": "other"}) == "global"
    assert inc.parser_context({**PILOT, "ical_optimization_enabled": False}) == "global"
    assert inc.parser_context({key: value for key,value in PILOT.items()
                               if key != "ical_optimization_enabled"}) == "global"
    assert inc.parser_context({**PILOT, "kind": "json"}) == "global"
    assert inc.parser_context({**PILOT, "platform_adapter": "localist"}) == "global"
    assert inc.parser_context() == "global"
