"""Terminal walkthrough. Records answers and timings. Changes nothing on the targets."""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

import yaml

from rehearse.models import Runbook
from rehearse.runbook_load import RunbookLoader

TABLETOP_DISCLAIMER = (
    "This is a record of a tabletop walkthrough: what people answered, and how "
    "long the discussion of each step took. It does not show that the technical "
    "steps would succeed, and it does not change the systems named in the runbook."
)

_OUTCOMES = {"met", "not_met", "partial", "skipped"}


class TabletopError(Exception):
    pass


@dataclass
class PromptRecord:
    prompt: str
    response: str


@dataclass
class StepRecord:
    step_id: str
    title: str
    action: str
    outcome: str
    notes: str
    discussion_seconds: float
    recorded_seconds: float | None
    timing_source: str
    prompts: list[PromptRecord] = field(default_factory=list)


@dataclass
class PreconditionRecord:
    precondition_id: str
    description: str
    outcome: str
    notes: str


@dataclass
class TabletopReport:
    runbook_id: str
    title: str
    path: str
    sha256: str
    participant: str
    started_at: str
    finished_at: str
    discussion_seconds: float
    notes: str
    preconditions: list[PreconditionRecord]
    steps: list[StepRecord]
    disclaimer: str = TABLETOP_DISCLAIMER


def load_answers(path: Path) -> dict:
    try:
        document = yaml.load(path.read_text(encoding="utf-8"), Loader=RunbookLoader)
    except yaml.YAMLError as exc:
        raise TabletopError(f"{path}: {exc}") from exc
    if not isinstance(document, dict):
        raise TabletopError(f"{path}: answers must be a mapping")
    return document


def run_tabletop(
    runbook: Runbook,
    answers: dict | None = None,
    participant: str | None = None,
    input_fn=None,
    output_fn=None,
    is_tty: bool = False,
) -> TabletopReport:
    if answers is None and input_fn is None:
        raise TabletopError("tabletop needs a terminal or --answers FILE")
    if answers is None and not is_tty:
        raise TabletopError("tabletop needs a terminal or --answers FILE")
    output = output_fn or (lambda _line: None)
    started = time.perf_counter()
    started_at = _now()
    if answers is not None:
        _reject_unknown_ids(runbook, answers)
        name = participant or str(answers.get("participant") or "").strip()
        if not name:
            raise TabletopError("name the participant with --participant or participant: in the answers file")
        notes = str(answers.get("notes") or "")
        preconditions = [_precondition_from_answers(item, answers) for item in runbook.preconditions]
        steps = [_step_from_answers(step, answers) for step in runbook.steps]
    else:
        assert input_fn is not None
        name = participant or _ask(output, input_fn, "Participant name")
        if not name:
            raise TabletopError("a participant name is required")
        output(f"{runbook.title}")
        output(runbook.summary)
        output(f"Owner: {runbook.owner.name} ({runbook.owner.email})")
        output("")
        preconditions = []
        for item in runbook.preconditions:
            output(f"Precondition {item.id}: {item.description}")
            outcome = _ask_outcome(output, input_fn, "Outcome [met/not_met/partial/skipped]")
            note = _ask(output, input_fn, "Notes (optional)")
            preconditions.append(
                PreconditionRecord(item.id, item.description, outcome, note)
            )
        steps = []
        for index, step in enumerate(runbook.steps, start=1):
            step_started = time.perf_counter()
            output("")
            output(f"Step {index}/{len(runbook.steps)} · {step.id}")
            output(step.title)
            output(step.description)
            output(f"Expected: {step.expected_outcome}")
            if step.owner:
                output(f"Owner: {step.owner}")
            for _host_step, asset in _assets(step):
                output(f"Asset {asset.kind}: {asset.target}")
            prompts = []
            for prompt in step.prompts:
                prompts.append(PromptRecord(prompt, _ask(output, input_fn, prompt)))
            action = _ask(output, input_fn, "What do you do?")
            outcome = _ask_outcome(output, input_fn, "Outcome [met/not_met/partial/skipped]")
            note = _ask(output, input_fn, "Notes (optional)")
            discussion = round(time.perf_counter() - step_started, 3)
            steps.append(
                StepRecord(
                    step_id=step.id,
                    title=step.title,
                    action=action,
                    outcome=outcome,
                    notes=note,
                    discussion_seconds=discussion,
                    recorded_seconds=None,
                    timing_source="wall-clock",
                    prompts=prompts,
                )
            )
        notes = _ask(output, input_fn, "Closing notes (optional)")
    finished = time.perf_counter()
    return TabletopReport(
        runbook_id=runbook.id,
        title=runbook.title,
        path=str(runbook.path),
        sha256=runbook.sha256,
        participant=name,
        started_at=started_at,
        finished_at=_now(),
        discussion_seconds=round(finished - started, 3),
        notes=notes,
        preconditions=preconditions,
        steps=steps,
    )


def render_tabletop_markdown(report: TabletopReport) -> str:
    lines = [
        f"# Tabletop record: {report.title}",
        "",
        f"> {report.disclaimer}",
        "",
        f"- Runbook: `{report.runbook_id}`",
        f"- SHA-256: `{report.sha256}`",
        f"- Participant: {report.participant}",
        f"- Started: {report.started_at}",
        f"- Finished: {report.finished_at}",
        f"- Walkthrough duration: {report.discussion_seconds} seconds",
        "",
        "## Preconditions",
        "",
    ]
    if not report.preconditions:
        lines.append("None recorded.")
        lines.append("")
    for item in report.preconditions:
        lines.append(f"### {item.precondition_id}")
        lines.append("")
        lines.append(item.description)
        lines.append("")
        lines.append(f"- Outcome: {item.outcome}")
        if item.notes:
            lines.append(f"- Notes: {item.notes}")
        lines.append("")
    lines.append("## Steps")
    lines.append("")
    for item in report.steps:
        lines.append(f"### {item.step_id} — {item.title}")
        lines.append("")
        lines.append(f"- Outcome: {item.outcome}")
        lines.append(f"- Action: {item.action or '(none)'}")
        lines.append(f"- Discussion seconds: {item.discussion_seconds}")
        if item.recorded_seconds is not None:
            lines.append(f"- Recorded seconds: {item.recorded_seconds} ({item.timing_source})")
        else:
            lines.append(f"- Timing source: {item.timing_source}")
        if item.notes:
            lines.append(f"- Notes: {item.notes}")
        for prompt in item.prompts:
            lines.append(f"- Q: {prompt.prompt}")
            lines.append(f"  - A: {prompt.response or '(none)'}")
        lines.append("")
    if report.notes:
        lines.append("## Closing notes")
        lines.append("")
        lines.append(report.notes)
        lines.append("")
    return "\n".join(lines)


def render_tabletop_json(report: TabletopReport) -> str:
    payload = {
        "tool": "runbookrehearsal",
        "kind": "tabletop",
        "disclaimer": report.disclaimer,
        "runbookId": report.runbook_id,
        "title": report.title,
        "path": report.path,
        "sha256": report.sha256,
        "participant": report.participant,
        "startedAt": report.started_at,
        "finishedAt": report.finished_at,
        "discussionSeconds": report.discussion_seconds,
        "notes": report.notes,
        "preconditions": [
            {
                "id": item.precondition_id,
                "description": item.description,
                "outcome": item.outcome,
                "notes": item.notes,
            }
            for item in report.preconditions
        ],
        "steps": [
            {
                "id": item.step_id,
                "title": item.title,
                "action": item.action,
                "outcome": item.outcome,
                "notes": item.notes,
                "discussionSeconds": item.discussion_seconds,
                "recordedSeconds": item.recorded_seconds,
                "timingSource": item.timing_source,
                "prompts": [
                    {"prompt": prompt.prompt, "response": prompt.response}
                    for prompt in item.prompts
                ],
            }
            for item in report.steps
        ],
    }
    return json.dumps(payload, indent=2) + "\n"


def write_tabletop(report: TabletopReport, output: Path) -> dict[str, Path]:
    output = output.expanduser()
    if output.exists() and not output.is_dir():
        raise NotADirectoryError(f"output path is a file: {output}")
    output.mkdir(parents=True, exist_ok=True)
    slug = report.runbook_id
    targets = {
        "md": output / f"tabletop-{slug}.md",
        "json": output / f"tabletop-{slug}.json",
    }
    targets["md"].write_text(render_tabletop_markdown(report), encoding="utf-8")
    targets["json"].write_text(render_tabletop_json(report), encoding="utf-8")
    return targets


def _assets(step):
    for asset in step.assets:
        yield step, asset


def _reject_unknown_ids(runbook: Runbook, answers: dict) -> None:
    known_steps = {step.id for step in runbook.steps}
    known_pre = {item.id for item in runbook.preconditions}
    for key in (answers.get("steps") or {}):
        if key not in known_steps:
            raise TabletopError(f"answers refer to unknown step {key!r}")
    for key in (answers.get("preconditions") or {}):
        if key not in known_pre:
            raise TabletopError(f"answers refer to unknown precondition {key!r}")


def _precondition_from_answers(item, answers: dict) -> PreconditionRecord:
    block = (answers.get("preconditions") or {}).get(item.id) or {}
    if not isinstance(block, dict):
        raise TabletopError(f"precondition {item.id} answers must be a mapping")
    outcome = block.get("outcome", "skipped")
    if outcome not in _OUTCOMES:
        raise TabletopError(f"precondition {item.id} outcome must be one of {sorted(_OUTCOMES)}")
    notes = "no answer supplied" if item.id not in (answers.get("preconditions") or {}) else str(block.get("notes") or "")
    return PreconditionRecord(item.id, item.description, str(outcome), notes)


def _step_from_answers(step, answers: dict) -> StepRecord:
    provided = answers.get("steps") or {}
    block = provided.get(step.id) or {}
    if not isinstance(block, dict):
        raise TabletopError(f"step {step.id} answers must be a mapping")
    missing = step.id not in provided
    outcome = "skipped" if missing else block.get("outcome", "skipped")
    if outcome not in _OUTCOMES:
        raise TabletopError(f"step {step.id} outcome must be one of {sorted(_OUTCOMES)}")
    recorded = block.get("elapsedSeconds")
    if recorded is not None and not isinstance(recorded, (int, float)):
        raise TabletopError(f"step {step.id} elapsedSeconds must be a number")
    prompts = []
    for entry in block.get("prompts") or []:
        if not isinstance(entry, dict) or "prompt" not in entry:
            raise TabletopError(f"step {step.id} prompts need prompt and response")
        prompts.append(PromptRecord(str(entry["prompt"]), str(entry.get("response") or "")))
    if not prompts and not missing:
        prompts = [PromptRecord(prompt, "") for prompt in step.prompts]
    return StepRecord(
        step_id=step.id,
        title=step.title,
        action="" if missing else str(block.get("action") or ""),
        outcome=str(outcome),
        notes="no answer supplied" if missing else str(block.get("notes") or ""),
        discussion_seconds=0.0,
        recorded_seconds=None if recorded is None else float(recorded),
        timing_source="participant" if recorded is not None else "unspecified",
        prompts=prompts,
    )


def _ask(output, input_fn, prompt: str) -> str:
    output(prompt)
    try:
        return str(input_fn("> ")).strip()
    except EOFError as exc:
        raise TabletopError("input closed before the walkthrough finished") from exc


def _ask_outcome(output, input_fn, prompt: str) -> str:
    for _ in range(5):
        value = _ask(output, input_fn, prompt).lower().replace("-", "_").replace(" ", "_")
        aliases = {"y": "met", "yes": "met", "n": "not_met", "no": "not_met", "not": "not_met"}
        value = aliases.get(value, value)
        if value in _OUTCOMES:
            return value
        output("Enter met, not_met, partial, or skipped.")
    return "skipped"


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()
