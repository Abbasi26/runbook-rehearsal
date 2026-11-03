"""v0.2: report diff, check --baseline, and init."""

from __future__ import annotations

import copy
import json
from datetime import date
from pathlib import Path

import pytest

from rehearse.cli import main
from rehearse.diff import DiffError, diff_reports, load_report, render_diff_markdown
from rehearse.runbook_load import load_runbook
from rehearse.scaffold import ScaffoldError, render_scaffold, ScaffoldOwner

ROOT = Path(__file__).resolve().parents[1]
DEMO_RUNBOOKS = ROOT / "examples" / "demo" / "runbooks"
DEMO_CONFIG = ROOT / "examples" / "demo" / "rehearse.yaml"


@pytest.fixture(scope="module")
def demo_report(tmp_path_factory) -> Path:
    out = tmp_path_factory.mktemp("demo")
    assert main(["check", str(DEMO_RUNBOOKS), "--config", str(DEMO_CONFIG), "--output", str(out)]) in (0, 1)
    return out / "report.json"


def _runbook(report: dict, runbook_id: str) -> dict:
    return next(item for item in report["runbooks"] if item["id"] == runbook_id)


def test_identical_reports_have_no_changes(demo_report):
    data = load_report(demo_report)
    result = diff_reports(data, copy.deepcopy(data))
    assert not result.regressed
    assert not result.new_failures and not result.fixed and not result.other_changes
    assert all(item.delta == 0 for item in result.runbooks)


def test_new_failure_fix_and_band_drop_are_reported(demo_report):
    before = load_report(demo_report)
    after = copy.deepcopy(before)
    healthy = _runbook(after, "linux-disk-incident")
    dns = next(item for item in healthy["findings"] if item["check"] == "dns")
    dns["status"] = "fail"
    dns["message"] = "name does not resolve"
    healthy["score"] = 70.0
    healthy["band"] = "drifting"
    stale = _runbook(after, "restore-finance-share")
    fixed = next(item for item in stale["findings"] if item["status"] == "fail" and item["check"] != "freshness")
    fixed["status"] = "pass"
    result = diff_reports(before, after)
    assert result.regressed
    assert [(item.runbook_id, item.check) for item in result.new_failures] == [("linux-disk-incident", "dns")]
    assert any(item.runbook_id == "restore-finance-share" for item in result.fixed)
    change = next(item for item in result.runbooks if item.runbook_id == "linux-disk-incident")
    assert change.band_dropped and change.delta == -30.0
    markdown = render_diff_markdown(result)
    assert "**Regression**" in markdown and "name does not resolve" in markdown


def test_freshness_is_matched_even_when_the_review_date_changes(demo_report):
    before = load_report(demo_report)
    after = copy.deepcopy(before)
    runbook = _runbook(after, "rebuild-backup-catalog")
    fresh = next(item for item in runbook["findings"] if item["check"] == "freshness")
    fresh["target"] = "2026-10-20"
    fresh["status"] = "pass"
    result = diff_reports(before, after)
    assert [(item.check, item.before, item.after) for item in result.fixed] == [("freshness", "fail", "pass")]
    assert not result.new_failures


def test_added_and_removed_runbooks(demo_report):
    before = load_report(demo_report)
    after = copy.deepcopy(before)
    removed = after["runbooks"].pop(0)
    extra = copy.deepcopy(removed)
    extra["id"] = "brand-new"
    after["runbooks"].append(extra)
    result = diff_reports(before, after)
    assert result.added_runbooks == ["brand-new"]
    assert result.removed_runbooks == [removed["id"]]


def test_diff_cli_formats_and_exit_codes(demo_report, tmp_path, capsys):
    before = load_report(demo_report)
    after = copy.deepcopy(before)
    finding = next(item for item in _runbook(after, "linux-disk-incident")["findings"] if item["check"] == "tcp")
    finding["status"] = "fail"
    regressed = tmp_path / "after.json"
    regressed.write_text(json.dumps(after), encoding="utf-8")
    assert main(["diff", str(demo_report), str(demo_report), "--fail-on-regression"]) == 0
    assert "no regression" in capsys.readouterr().out
    assert main(["diff", str(demo_report), str(regressed)]) == 0
    assert main(["diff", str(demo_report), str(regressed), "--fail-on-regression"]) == 1
    capsys.readouterr()
    assert main(["diff", str(demo_report), str(regressed), "--format", "json"]) == 0
    data = json.loads(capsys.readouterr().out)
    assert data["regressed"] is True and data["newFailures"][0]["check"] == "tcp"
    bogus = tmp_path / "bogus.json"
    bogus.write_text('{"tool": "other"}', encoding="utf-8")
    assert main(["diff", str(bogus), str(demo_report)]) == 2
    with pytest.raises(DiffError):
        load_report(tmp_path / "missing.json")


def test_check_with_baseline_writes_diff_and_gates(demo_report, tmp_path, capsys):
    out = tmp_path / "out"
    code = main([
        "check", str(DEMO_RUNBOOKS), "--config", str(DEMO_CONFIG),
        "--output", str(out), "--baseline", str(demo_report), "--fail-on-regression",
    ])
    assert code == 0
    assert (out / "diff.md").read_text(encoding="utf-8").startswith("## Runbook rehearsal: changes")
    assert "Compared with" in capsys.readouterr().out
    better = load_report(demo_report)
    for runbook in better["runbooks"]:
        for finding in runbook["findings"]:
            finding["status"] = "pass"
        runbook["band"] = "maintained"
    optimistic = tmp_path / "optimistic.json"
    optimistic.write_text(json.dumps(better), encoding="utf-8")
    code = main([
        "check", str(DEMO_RUNBOOKS), "--config", str(DEMO_CONFIG),
        "--baseline", str(optimistic), "--fail-on-regression",
    ])
    assert code == 1
    assert main(["check", str(DEMO_RUNBOOKS), "--config", str(DEMO_CONFIG), "--fail-on-regression"]) == 2


def test_init_writes_a_valid_runbook(tmp_path, capsys):
    target = tmp_path / "runbooks" / "restore-erp.yaml"
    assert main(["init", "restore-erp", "--title", "Restore the ERP database: \"primary\"", "--output", str(target)]) == 0
    runbook = load_runbook(target)
    assert runbook.id == "restore-erp"
    assert runbook.title == 'Restore the ERP database: "primary"'
    assert runbook.execution == "observe-only"
    assert main(["validate", str(target)]) == 0
    assert main(["init", "restore-erp", "--output", str(target)]) == 2
    assert "exists" in capsys.readouterr().err
    assert main(["init", "restore-erp", "--output", str(target), "--force", "--severity", "low"]) == 0
    assert load_runbook(target).review.interval_days == 180


def test_init_rejects_bad_ids_and_prints_to_stdout(capsys):
    with pytest.raises(ScaffoldError):
        render_scaffold("Bad ID")
    text = render_scaffold("db-restore", today=date(2026, 10, 1))
    assert 'lastReviewed: "2026-10-01"' in text
    assert main(["init", "db-restore", "--output", "-"]) == 0
    assert "id: db-restore" in capsys.readouterr().out


def test_init_from_copies_owner_and_contacts(tmp_path, capsys):
    source = Path("examples/runbook.example.yaml")
    target = tmp_path / "new-runbook.yaml"
    assert main(["init", "new-runbook", "--from", str(source), "--output", str(target)]) == 0
    runbook = load_runbook(target)
    assert runbook.id == "new-runbook"
    assert runbook.owner.name == "Harbor and Pine Operations"
    assert runbook.owner.email == "ops@harborpine.example"
    assert runbook.owner.team == "operations"
    assert len(runbook.contacts) == 1
    assert runbook.contacts[0].name == "Priya Nandakumar"
    assert runbook.contacts[0].role == "Incident commander"
    assert runbook.contacts[0].email == "priya.nandakumar@harborpine.example"
    assert runbook.contacts[0].phone == "+1-555-014-2281"
    assert runbook.contacts[0].escalation_order == 1
    assert main(["validate", str(target)]) == 0


def test_init_from_missing_file_exits_with_error(tmp_path, capsys):
    target = tmp_path / "new-runbook.yaml"
    code = main(["init", "new-runbook", "--from", "/nonexistent/path.yaml", "--output", str(target)])
    assert code == 2
    assert "not found" in capsys.readouterr().err
    assert not target.exists()


def test_init_from_invalid_yaml_exits_with_error(tmp_path, capsys):
    bad = tmp_path / "bad.yaml"
    bad.write_text("invalid: [", encoding="utf-8")
    target = tmp_path / "new-runbook.yaml"
    code = main(["init", "new-runbook", "--from", str(bad), "--output", str(target)])
    assert code == 2
    assert "invalid source runbook" in capsys.readouterr().err
    assert not target.exists()


def test_init_from_preserves_other_scaffold_defaults(tmp_path):
    source = Path("examples/runbook.example.yaml")
    target = tmp_path / "new-runbook.yaml"
    assert main(["init", "new-runbook", "--from", str(source), "--output", str(target)]) == 0
    runbook = load_runbook(target)
    assert runbook.id == "new-runbook"
    assert runbook.title == "New runbook"
    assert runbook.execution == "observe-only"
    assert runbook.service == "new-runbook"
    assert runbook.severity == "high"
    assert runbook.review.interval_days == 90
    assert runbook.review.max_age_days == 180
    assert len(runbook.preconditions) == 1
    assert runbook.preconditions[0].id == "backup-known"
    assert len(runbook.steps) == 2


def test_render_scaffold_with_owner_and_contacts():
    owner = ScaffoldOwner(name="Test Team", email="test@example.org", team="test-team")
    contacts = [
        type("Contact", (), {"name": "Alice", "role": "Lead", "email": "alice@example.org", "phone": "+1-555-010-0001", "escalation_order": 1})(),
        type("Contact", (), {"name": "Bob", "role": "Backup", "email": "bob@example.org", "phone": None, "escalation_order": 2})(),
    ]
    text = render_scaffold(
        "test-id",
        owner=owner,
        contacts=contacts,
        today=date(2026, 1, 15),
    )
    assert "name: Test Team" in text
    assert 'email: "test@example.org"' in text
    assert "team: test-team" in text
    assert "name: Alice" in text
    assert "role: Lead" in text
    assert 'email: "alice@example.org"' in text
    assert 'phone: "+1-555-010-0001"' in text
    assert "escalationOrder: 1" in text
    assert "name: Bob" in text
    assert "phone" not in text.split("name: Bob")[1].split("\n  -")[0]
    assert "escalationOrder: 2" in text
