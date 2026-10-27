"""Regression guard: Vercel installs from pyproject.toml, not requirements.txt."""
from pathlib import Path
import tomllib


def test_vercel_function_has_real_parser_dependencies():
    root = Path(__file__).resolve().parent.parent
    config = tomllib.loads((root / "pyproject.toml").read_text())
    deps = {p.split("==", 1)[0].lower() for p in config["project"]["dependencies"]}
    required = {
        "icalendar", "recurring-ical-events", "feedparser", "beautifulsoup4",
        "requests", "lxml", "pytz", "jinja2",
    }
    assert required.issubset(deps), f"Missing Python runtime dependencies: {required - deps}"
    assert config["tool"]["vercel"]["entrypoint"] == "api.preview:handler"
    assert "anthropic" not in deps, "AI is disabled for lightweight RoomQuest source previews"
