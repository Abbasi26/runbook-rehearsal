"""Demo, CLI exit codes, and the tabletop record."""

import json
import socket
from pathlib import Path

from rehearse.cli import main
from rehearse.demo import load_demo_config, run_demo
from rehearse.runbook_load import load_runbook
from rehearse.tabletop import load_answers, run_tabletop, write_tabletop

ROOT = Path(__file__).resolve().parents[1]


def test_demo_is_offline_and_shows_planted_rot(monkeypatch):
    def boom(*_args, **_kwargs):
        raise AssertionError("demo opened a socket")

    monkeypatch.setattr(socket, "socket", boom)
    monkeypatch.setattr(socket, "getaddrinfo", boom)
    monkeypatch.setattr(socket, "create_connection", boom)

    config, paths = load_demo_config()
    assert config.mode == "offline"
    assert len(paths) == 3
    report = run_demo()
    by_id = {item.runbook.id: item for item in report.results}
    assert set(by_id) == {
        "restore-finance-share",
        "linux-disk-incident",
        "rebuild-backup-catalog",
    }
    finance = by_id["restore-finance-share"]
    linux = by_id["linux-disk-incident"]
    catalog = by_id["rebuild-backup-catalog"]
    assert finance.score.band == "stale"
    assert linux.score.value == 100.0
    assert linux.score.band == "maintained"
    assert catalog.score.band == "drifting"
    assert report.probes_sent is False
    assert report.directory_provider == "stub"
    assert report.clock_date == "2026-10-21"
    messages = " ".join(item.message for item in finance.findings)
    assert "maximum age" in messages
    assert any(item.status == "fail" and item.check == "tcp" for item in finance.findings)
    assert any(item.target.endswith("restore-finance-share.md") and item.status == "fail" for item in finance.findings)
    assert any(item.check == "script-syntax" and item.status == "fail" and item.target.endswith(".sh") for item in finance.findings)
    assert any("pager-desk" in item.message or item.target == "Legacy pager desk" for item in finance.findings if item.status == "fail")
    assert any(item.check == "group-exists" and item.status == "fail" for item in finance.findings)
    assert "stub" in report.directory_note.lower()


def test_cli_demo_validate_and_fail_under(tmp_path: Path, capsys):
    output = tmp_path / "demo-out"
    assert main(["demo", "--output", str(output)]) == 0
    captured = capsys.readouterr().out
    assert "Deliberate rot" in captured
    assert "restore-finance-share" in captured
    payload = json.loads((output / "report.json").read_text(encoding="utf-8"))
    assert payload["mode"] == "offline"
    assert (output / "report.html").is_file()
    assert (output / "report.md").is_file()

    assert main(["validate", str(ROOT / "examples" / "demo" / "runbooks")]) == 0
    assert main(["schema", "--output", str(tmp_path / "schema.json")]) == 0
    assert "observe-only" in (tmp_path / "schema.json").read_text(encoding="utf-8")
    capsys.readouterr()

    code = main(
        [
            "check",
            str(ROOT / "examples" / "demo" / "runbooks"),
            "--config",
            str(ROOT / "examples" / "demo" / "rehearse.yaml"),
            "--fail-under",
            "90",
            "--stdout",
            "json",
        ]
    )
    assert code == 1
    checked = json.loads(capsys.readouterr().out)
    assert checked["overall"]["score"] < 90

    strict = main(
        [
            "check",
            str(ROOT / "examples" / "demo" / "runbooks" / "linux-disk-incident.yaml"),
            "--config",
            str(ROOT / "examples" / "demo" / "rehearse.yaml"),
            "--strict",
        ]
    )
    assert strict == 0


def test_tabletop_answers_record_timings(tmp_path: Path, capsys):
    runbook = load_runbook(ROOT / "examples" / "demo" / "runbooks" / "restore-finance-share.yaml")
    answers = {
        "participant": "Sam Ortega",
        "notes": "Classroom exercise. No production changes.",
        "preconditions": {
            "backup-fresh": {"outcome": "met", "notes": "Snapshot snap-2026-10-20 is listed."}
        },
        "steps": {
            "declare-incident": {
                "action": "Posted in the incident channel and paged Priya.",
                "outcome": "met",
                "notes": "Acknowledged in four minutes.",
                "elapsedSeconds": 240,
                "prompts": [
                    {"prompt": "What time did the commander acknowledge?", "response": "02:14 UTC"}
                ],
            },
            "check-file-server": {
                "action": "Recorded that TCP 445 is closed in the fixture.",
                "outcome": "not_met",
                "notes": "Did not restart the server.",
                "elapsedSeconds": 90,
            },
        },
    }
    path = tmp_path / "answers.yaml"
    import yaml

    path.write_text(yaml.safe_dump(answers), encoding="utf-8")
    loaded = load_answers(path)
    report = run_tabletop(runbook, answers=loaded)
    by_step = {item.step_id: item for item in report.steps}
    assert report.participant == "Sam Ortega"
    assert by_step["declare-incident"].recorded_seconds == 240
    assert by_step["declare-incident"].timing_source == "participant"
    assert by_step["declare-incident"].prompts[0].response == "02:14 UTC"
    assert by_step["check-file-server"].outcome == "not_met"
    assert by_step["restore-copy"].outcome == "skipped"
    assert by_step["restore-copy"].notes == "no answer supplied"
    written = write_tabletop(report, tmp_path / "tabletop")
    body = json.loads(written["json"].read_text(encoding="utf-8"))
    assert body["kind"] == "tabletop"
    assert "does not show that the technical steps would succeed" in body["disclaimer"]
    assert "240" in written["md"].read_text(encoding="utf-8")

    assert main(
        [
            "tabletop",
            str(ROOT / "examples" / "demo" / "runbooks" / "restore-finance-share.yaml"),
            "--answers",
            str(path),
            "--output",
            str(tmp_path / "from-cli"),
        ]
    ) == 0
    assert list((tmp_path / "from-cli").glob("tabletop-*.json"))

    missing = dict(answers)
    missing["steps"] = dict(answers["steps"])
    missing["steps"]["not-a-step"] = {"outcome": "met"}
    bad = tmp_path / "bad.yaml"
    bad.write_text(yaml.safe_dump(missing), encoding="utf-8")
    assert main(
        [
            "tabletop",
            str(ROOT / "examples" / "demo" / "runbooks" / "restore-finance-share.yaml"),
            "--answers",
            str(bad),
        ]
    ) == 2


def test_interactive_tabletop_uses_the_wall_clock():
    runbook = load_runbook(ROOT / "examples" / "demo" / "runbooks" / "restore-finance-share.yaml")
    replies = iter(
        [
            "met",
            "Snapshot is listed.",
            "02:14 UTC",
            "Paged Priya.",
            "met",
            "Acknowledged.",
            "no",
            "Recorded the closed port.",
            "not_met",
            "Did not restart anything.",
            "Waited.",
            "partial",
            "Copy was not started.",
            "Exercise closed.",
        ]
    )

    def fake_input(_prompt: str) -> str:
        return next(replies)

    lines: list[str] = []
    report = run_tabletop(
        runbook,
        participant="Sam Ortega",
        input_fn=fake_input,
        output_fn=lines.append,
        is_tty=True,
    )
    assert report.participant == "Sam Ortega"
    assert report.steps[0].timing_source == "wall-clock"
    assert report.steps[0].prompts[0].response == "02:14 UTC"
    assert report.steps[1].outcome == "not_met"
    assert report.steps[2].outcome == "partial"
    assert report.notes == "Exercise closed."
    assert any("Declare the incident" in line for line in lines)


def test_tabletop_refuses_a_non_interactive_terminal(monkeypatch):
    runbook = load_runbook(ROOT / "examples" / "demo" / "runbooks" / "linux-disk-incident.yaml")
    from rehearse.tabletop import TabletopError

    try:
        run_tabletop(runbook, answers=None, is_tty=False)
    except TabletopError as exc:
        assert "answers" in str(exc)
    else:
        raise AssertionError("non-interactive tabletop should fail")
