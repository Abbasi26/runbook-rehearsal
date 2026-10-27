"""Schema, YAML safety, and structural validation."""

from pathlib import Path

import yaml

from rehearse.locate import repo_schema_path, schema_path
from rehearse.runbook_load import LoadError, load_runbook, load_schema, parse_yaml

ROOT = Path(__file__).resolve().parents[1]
DEMO = ROOT / "examples" / "demo" / "runbooks"
EXAMPLE = ROOT / "examples" / "runbook.example.yaml"


def test_bundled_schema_matches_repo_copy():
    repo = repo_schema_path()
    assert repo is not None
    assert schema_path().read_bytes() == repo.read_bytes()
    load_schema()


def test_demo_and_example_validate():
    for path in sorted(DEMO.glob("*.yaml")):
        book = load_runbook(path)
        assert book.execution == "observe-only"
        assert book.id
    example = load_runbook(EXAMPLE)
    assert example.id == "restore-archive-share"


def test_rejects_executable_document(tmp_path: Path):
    source = (DEMO / "linux-disk-incident.yaml").read_text(encoding="utf-8")
    broken = source.replace("execution: observe-only", "execution: run", 1)
    path = tmp_path / "job.yaml"
    path.write_text(broken, encoding="utf-8")
    try:
        load_runbook(path)
    except LoadError as exc:
        assert any("observe-only" in message for message in exc.messages)
    else:
        raise AssertionError("expected a schema error")


def test_duplicate_key_and_alias_and_python_tag(tmp_path: Path):
    duplicate = tmp_path / "dup.yaml"
    duplicate.write_text("id: one\nid: two\n", encoding="utf-8")
    try:
        parse_yaml(duplicate.read_text(encoding="utf-8"))
    except ValueError as exc:
        assert "duplicate key" in str(exc)
    else:
        raise AssertionError("duplicate key was accepted")

    alias = tmp_path / "alias.yaml"
    alias.write_text("id: &name sample-runbook\ntitle: *name\n", encoding="utf-8")
    try:
        parse_yaml(alias.read_text(encoding="utf-8"))
    except ValueError as exc:
        assert "alias" in str(exc).lower() or "anchor" in str(exc).lower()
    else:
        raise AssertionError("alias was accepted")

    marker = tmp_path / "marker.txt"
    tagged = tmp_path / "tagged.yaml"
    tagged.write_text(
        f"id: !!python/object/apply:pathlib.Path ['{marker}']\n",
        encoding="utf-8",
    )
    try:
        parse_yaml(tagged.read_text(encoding="utf-8"))
    except ValueError:
        pass
    else:
        raise AssertionError("python tag was accepted")
    assert not marker.exists()


def test_unquoted_date_stays_a_string():
    loaded = parse_yaml("lastReviewed: 2026-10-21\n")
    assert loaded["lastReviewed"] == "2026-10-21"


def test_credentials_in_url_and_max_age(tmp_path: Path):
    text = (DEMO / "linux-disk-incident.yaml").read_text(encoding="utf-8")
    creds = text.replace(
        "https://status.harborpine.example/logs",
        "https://user:secret@status.harborpine.example/logs",
        1,
    )
    path = tmp_path / "creds.yaml"
    path.write_text(creds, encoding="utf-8")
    try:
        load_runbook(path)
    except LoadError as exc:
        assert any("credential" in message for message in exc.messages)
    else:
        raise AssertionError("credentials were accepted")

    short = text.replace("maxAgeDays: 180", "maxAgeDays: 10", 1)
    path.write_text(short, encoding="utf-8")
    try:
        load_runbook(path)
    except LoadError as exc:
        assert any("maxAgeDays" in message for message in exc.messages)
    else:
        raise AssertionError("max age shorter than the interval was accepted")


def test_bad_calendar_date(tmp_path: Path):
    text = (DEMO / "linux-disk-incident.yaml").read_text(encoding="utf-8")
    path = tmp_path / "date.yaml"
    path.write_text(text.replace("2026-09-01", "2026-02-31", 1), encoding="utf-8")
    try:
        load_runbook(path)
    except LoadError as exc:
        assert exc.messages
    else:
        raise AssertionError("invalid date was accepted")


def test_vscode_settings_and_workflows_parse():
    settings = yaml.safe_load((ROOT / "examples" / "vscode" / "settings.json").read_text(encoding="utf-8"))
    assert "yaml.schemas" in settings
    action = yaml.safe_load(
        (ROOT / "examples" / "github-actions" / "rehearse-schedule.yml").read_text(encoding="utf-8")
    )
    # PyYAML 1.1 treats the GitHub Actions key "on" as a boolean.
    trigger = action.get("on", action.get(True))
    assert "schedule" in trigger
    ci = yaml.safe_load((ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8"))
    assert "pytest" in ci["jobs"]
