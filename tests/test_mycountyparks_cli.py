"""Read-only audit behavior; no publisher or database calls."""
import json
from unittest.mock import Mock

import pytest

from scripts import scrape_mycountyparks as cli


def output_for(county, events=None):
    source = cli.source_for_county(county)
    events = [] if events is None else events
    return {"source_key": source["source_key"], "source_url": source["feed_url"],
            "timezone": "America/Chicago", "event_count": len(events), "events": events}


def test_single_source_uses_production_guards_and_does_not_extend_outer_deadline(monkeypatch):
    monkeypatch.setattr(cli, "monotonic", lambda: 100)
    fetch = Mock(return_value="public html")
    monkeypatch.setattr(cli, "fetch_publisher", fetch)

    def collect(source, request, *, deadline_at):
        assert source == cli.source_for_county("mahaska")
        assert deadline_at == 120
        assert request(source["feed_url"], "text/html") == "public html"
        return [{"id": "example"}]

    monkeypatch.setattr(cli, "collect", collect)
    result = cli.scrape_county("mahaska", 30, deadline_at=120)
    assert result["events"] == [{"id": "example"}] and result["event_count"] == 1
    assert fetch.call_args.kwargs == {"respect_robots": True, "deadline_at": 120,
                                      "allowed_hosts": ("www.mycountyparks.com",)}


def test_source_finishing_after_deadline_is_not_a_success(monkeypatch):
    clock = [100]
    monkeypatch.setattr(cli, "monotonic", lambda: clock[0])

    def collect(*args, **kwargs):
        clock[0] = 130
        return []

    monkeypatch.setattr(cli, "collect", collect)
    with pytest.raises(ValueError, match="collection_deadline"):
        cli.scrape_county("mahaska", 30)


def test_all_county_audit_continues_after_failure_without_fabricated_empty(monkeypatch):
    monkeypatch.setattr(cli, "COUNTIES", {"mahaska": "Mahaska", "iowa": "Iowa", "adair": "Adair"})
    monkeypatch.setattr(cli, "monotonic", lambda: 100)
    attempted = []

    def scrape(county, timeout, *, deadline_at):
        attempted.append(county)
        assert timeout == 30 and deadline_at == 1000
        if county == "iowa":
            raise cli.PreviewError("publisher_http_503")
        # Counts are normalized output records, after registration-option merges.
        return output_for(county, [{"id": "one"}] if county == "adair" else [{"id": "two"}, {"id": "three"}])

    monkeypatch.setattr(cli, "scrape_county", scrape)
    result = cli.scrape_all_counties(30, 900)
    assert attempted == ["adair", "iowa", "mahaska"]
    assert result["complete"] is False and result["source_count"] == 3
    assert result["event_count"] == 3
    assert result["successful_count"] == 2 and result["failed_count"] == 1
    assert result["not_attempted_count"] == 0
    failed = result["sources"][1]
    assert failed["status"] == "failed" and failed["error"] == "publisher_http_503"
    assert "events" not in failed and "event_count" not in failed


def test_overall_deadline_marks_remaining_counties_without_starting_requests(monkeypatch):
    monkeypatch.setattr(cli, "COUNTIES", {"adair": "Adair", "iowa": "Iowa", "mahaska": "Mahaska"})
    clock, attempted = [0], []
    monkeypatch.setattr(cli, "monotonic", lambda: clock[0])

    def scrape(county, timeout, *, deadline_at):
        attempted.append(county)
        assert deadline_at == 20
        clock[0] += 10
        return output_for(county)

    monkeypatch.setattr(cli, "scrape_county", scrape)
    result = cli.scrape_all_counties(10, 20)
    assert attempted == ["adair", "iowa"]
    assert result["complete"] is False and result["not_attempted_count"] == 1
    assert result["successful_count"] == 2 and result["failed_count"] == 0
    remaining = result["sources"][2]
    assert remaining["status"] == "not_attempted" and remaining["error"] == "audit_deadline"
    assert "events" not in remaining and "event_count" not in remaining


def test_list_counties_emits_all_canonical_sources_without_network(monkeypatch, capsys):
    fetch = Mock(side_effect=AssertionError("must not fetch"))
    monkeypatch.setattr(cli, "fetch_publisher", fetch)
    assert cli.main(["--list-counties"]) == 0
    output = json.loads(capsys.readouterr().out)
    assert output["source_count"] == len(output["sources"]) == 99
    assert cli.source_for_county("obrien") in output["sources"]
    assert cli.source_for_county("black_hawk") in output["sources"]
    fetch.assert_not_called()


def test_single_county_output_remains_compatible_and_defaults_to_120_seconds(monkeypatch, capsys):
    scrape = Mock(return_value=output_for("mahaska", [{"id": "example"}]))
    monkeypatch.setattr(cli, "scrape_county", scrape)
    assert cli.main(["--county", "mahaska"]) == 0
    scrape.assert_called_once_with("mahaska", 120)
    assert json.loads(capsys.readouterr().out) == output_for("mahaska", [{"id": "example"}])


def test_all_county_report_is_written_even_when_a_source_fails(monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(cli, "COUNTIES", {"mahaska": "Mahaska"})
    scrape = Mock(side_effect=ValueError("collection_deadline"))
    monkeypatch.setattr(cli, "scrape_county", scrape)
    destination = tmp_path / "audit.json"
    assert cli.main(["--all-counties", "--output", str(destination)]) == 1
    output = json.loads(destination.read_text())
    assert output["failed_count"] == 1 and output["complete"] is False
    assert output["event_count"] == 0
    assert output["sources"][0]["error"] == "collection_deadline"
    assert output["per_source_timeout_seconds"] == 30
    assert output["overall_timeout_seconds"] == 900
    assert "Wrote 0 events across 0 complete county scrapes, 1 failed, 0 not attempted" in capsys.readouterr().out


def test_complete_all_county_audit_exits_successfully(monkeypatch, capsys):
    monkeypatch.setattr(cli, "COUNTIES", {"mahaska": "Mahaska", "adair": "Adair"})
    monkeypatch.setattr(cli, "scrape_county", lambda county, timeout, **kwargs: output_for(county))
    assert cli.main(["--all-counties", "--timeout", "45", "--overall-timeout", "100"]) == 0
    output = json.loads(capsys.readouterr().out)
    assert output["complete"] is True and output["successful_count"] == 2
    assert output["per_source_timeout_seconds"] == 45 and output["overall_timeout_seconds"] == 100


@pytest.mark.parametrize("args", [
    ["--county", "unknown"], ["--county", "iowa", "--all-counties"],
    ["--county", "iowa", "--timeout", "9"], ["--all-counties", "--timeout", "301"],
    ["--all-counties", "--overall-timeout", "9"], ["--all-counties", "--overall-timeout", "3601"],
])
def test_invalid_selection_or_unbounded_budget_fails_before_fetch(args, monkeypatch):
    fetch = Mock(side_effect=AssertionError("must not fetch"))
    monkeypatch.setattr(cli, "fetch_publisher", fetch)
    with pytest.raises(SystemExit) as exc:
        cli.main(args)
    assert exc.value.code == 2
    fetch.assert_not_called()
