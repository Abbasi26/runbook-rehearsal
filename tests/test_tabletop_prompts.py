"""Validate tabletop prompt containers without changing valid records."""

from pathlib import Path

import pytest
import yaml

from rehearse.cli import main
from rehearse.runbook_load import load_runbook
from rehearse.tabletop import TabletopError, run_tabletop

RUNBOOK_PATH = (
    Path(__file__).resolve().parents[1]
    / "examples/demo/runbooks/restore-finance-share.yaml"
)


@pytest.mark.parametrize(
    "value",
    [False, True, 0, 1, 0.5, "", "invalid", {}, {"prompt": "Question"}],
)
def test_tabletop_rejects_non_list_prompts(value, tmp_path, capsys):
    answers = {
        "participant": "Sam Ortega",
        "steps": {"declare-incident": {"prompts": value}},
    }
    message = "step declare-incident prompts must be a list"

    with pytest.raises(TabletopError) as exc:
        run_tabletop(load_runbook(RUNBOOK_PATH), answers=answers)
    assert str(exc.value) == message

    answers_path = tmp_path / "answers.yaml"
    answers_path.write_text(yaml.safe_dump(answers), encoding="utf-8")
    output = tmp_path / "tabletop"

    assert main([
        "tabletop", str(RUNBOOK_PATH),
        "--answers", str(answers_path),
        "--output", str(output),
    ]) == 2
    captured = capsys.readouterr()
    assert captured.err.strip() == message
    assert captured.out == ""
    assert not output.exists()


@pytest.mark.parametrize(
    "block",
    [{}, {"prompts": None}, {"prompts": []}],
)
def test_tabletop_preserves_default_prompts(block):
    runbook = load_runbook(RUNBOOK_PATH)
    report = run_tabletop(
        runbook,
        answers={
            "participant": "Sam Ortega",
            "steps": {"declare-incident": block},
        },
    )
    record = next(
        item for item in report.steps if item.step_id == "declare-incident"
    )
    step = next(item for item in runbook.steps if item.id == "declare-incident")
    assert [(item.prompt, item.response) for item in record.prompts] == [
        (prompt, "") for prompt in step.prompts
    ]


def test_tabletop_preserves_supplied_prompts():
    report = run_tabletop(
        load_runbook(RUNBOOK_PATH),
        answers={
            "participant": "Sam Ortega",
            "steps": {
                "declare-incident": {
                    "prompts": [
                        {"prompt": "Acknowledged?", "response": "02:14 UTC"},
                        {"prompt": "Next action?"},
                    ],
                },
            },
        },
    )
    record = next(
        item for item in report.steps if item.step_id == "declare-incident"
    )
    assert [(item.prompt, item.response) for item in record.prompts] == [
        ("Acknowledged?", "02:14 UTC"),
        ("Next action?", ""),
    ]


@pytest.mark.parametrize("entry", [None, False, 1, "invalid", {}, {"response": "yes"}])
def test_tabletop_preserves_prompt_entry_validation(entry):
    with pytest.raises(TabletopError) as exc:
        run_tabletop(
            load_runbook(RUNBOOK_PATH),
            answers={
                "participant": "Sam Ortega",
                "steps": {"declare-incident": {"prompts": [entry]}},
            },
        )
    assert str(exc.value) == (
        "step declare-incident prompts need prompt and response"
    )

# Skipped: implementation and test execution in this read-only review.
# Risk: malformed prompts containers now fail with CLI exit code 2.
