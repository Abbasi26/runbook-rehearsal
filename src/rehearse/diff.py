"""Compare two report.json files: score changes, new failures, and fixed findings."""

from __future__ import annotations

import json
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path

from rehearse.scoring import BANDS

BAND_ORDER = [name for _, name, _ in reversed(BANDS)]
# Targets that change on every review are compared per check, not per target.
TARGETLESS_CHECKS = {"freshness"}


class DiffError(ValueError):
    pass


@dataclass
class FindingChange:
    runbook_id: str
    check: str
    target: str
    before: str | None
    after: str | None
    message: str

    def as_dict(self) -> dict:
        return {
            "runbookId": self.runbook_id,
            "check": self.check,
            "target": self.target,
            "before": self.before,
            "after": self.after,
            "message": self.message,
        }


@dataclass
class RunbookChange:
    runbook_id: str
    title: str
    before: float | None
    after: float | None
    band_before: str | None
    band_after: str | None

    @property
    def delta(self) -> float | None:
        if self.before is None or self.after is None:
            return None
        return round(self.after - self.before, 1)

    @property
    def band_dropped(self) -> bool:
        if self.band_before is None or self.band_after is None:
            return False
        return _band_rank(self.band_after) < _band_rank(self.band_before)

    def as_dict(self) -> dict:
        return {
            "runbookId": self.runbook_id,
            "title": self.title,
            "before": self.before,
            "after": self.after,
            "delta": self.delta,
            "bandBefore": self.band_before,
            "bandAfter": self.band_after,
            "bandDropped": self.band_dropped,
        }


@dataclass
class ReportDiff:
    overall_before: float | None
    overall_after: float | None
    runbooks: list[RunbookChange] = field(default_factory=list)
    new_failures: list[FindingChange] = field(default_factory=list)
    fixed: list[FindingChange] = field(default_factory=list)
    other_changes: list[FindingChange] = field(default_factory=list)
    added_runbooks: list[str] = field(default_factory=list)
    removed_runbooks: list[str] = field(default_factory=list)

    @property
    def regressed(self) -> bool:
        return bool(self.new_failures) or any(item.band_dropped for item in self.runbooks)

    def as_dict(self) -> dict:
        delta = None
        if self.overall_before is not None and self.overall_after is not None:
            delta = round(self.overall_after - self.overall_before, 1)
        return {
            "overall": {"before": self.overall_before, "after": self.overall_after, "delta": delta},
            "regressed": self.regressed,
            "runbooks": [item.as_dict() for item in self.runbooks],
            "newFailures": [item.as_dict() for item in self.new_failures],
            "fixed": [item.as_dict() for item in self.fixed],
            "otherChanges": [item.as_dict() for item in self.other_changes],
            "addedRunbooks": self.added_runbooks,
            "removedRunbooks": self.removed_runbooks,
        }


def _band_rank(band: str) -> int:
    key = band.strip().lower()
    return BAND_ORDER.index(key) if key in BAND_ORDER else -1


def load_report(path: Path) -> dict:
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise DiffError(f"report not found: {path}") from exc
    except json.JSONDecodeError as exc:
        raise DiffError(f"{path} is not JSON ({exc.msg})") from exc
    if not isinstance(data, dict) or data.get("tool") != "runbookrehearsal" or not isinstance(data.get("runbooks"), list):
        raise DiffError(f"{path} is not a RunbookRehearsal report.json")
    return data


def _keyed_findings(runbook: dict) -> dict[tuple, dict]:
    keyed: dict[tuple, dict] = {}
    counter: dict[tuple, int] = defaultdict(int)
    for finding in runbook.get("findings") or []:
        check = str(finding.get("check") or "")
        target = "" if check in TARGETLESS_CHECKS else str(finding.get("target") or "")
        base = (check, target)
        keyed[(check, target, counter[base])] = finding
        counter[base] += 1
    return keyed


def diff_reports(before: dict, after: dict) -> ReportDiff:
    old = {str(item.get("id")): item for item in before.get("runbooks") or []}
    new = {str(item.get("id")): item for item in after.get("runbooks") or []}
    result = ReportDiff(
        overall_before=(before.get("overall") or {}).get("score"),
        overall_after=(after.get("overall") or {}).get("score"),
        added_runbooks=sorted(set(new) - set(old)),
        removed_runbooks=sorted(set(old) - set(new)),
    )
    for runbook_id in sorted(set(old) | set(new)):
        prev = old.get(runbook_id)
        curr = new.get(runbook_id)
        result.runbooks.append(
            RunbookChange(
                runbook_id=runbook_id,
                title=str((curr or prev or {}).get("title") or ""),
                before=prev.get("score") if prev else None,
                after=curr.get("score") if curr else None,
                band_before=prev.get("band") if prev else None,
                band_after=curr.get("band") if curr else None,
            )
        )
        if curr is None:
            continue
        prev_findings = _keyed_findings(prev) if prev else {}
        curr_findings = _keyed_findings(curr)
        for key in list(curr_findings) + [item for item in prev_findings if item not in curr_findings]:
            a = prev_findings.get(key)
            b = curr_findings.get(key)
            status_a = a.get("status") if a else None
            status_b = b.get("status") if b else None
            if status_a == status_b:
                continue
            source = b or a or {}
            change = FindingChange(
                runbook_id=runbook_id,
                check=key[0],
                target=str(source.get("target") or ""),
                before=status_a,
                after=status_b,
                message=str(source.get("message") or ""),
            )
            if status_b == "fail":
                result.new_failures.append(change)
            elif status_a == "fail":
                result.fixed.append(change)
            else:
                result.other_changes.append(change)
    return result


def _score(value: float | None) -> str:
    return "-" if value is None else f"{value:.1f}"


def _delta(value: float | None) -> str:
    if value is None:
        return "-"
    return f"{value:+.1f}"


def render_diff_text(diff: ReportDiff) -> str:
    overall = diff.as_dict()["overall"]
    lines = [f"Overall {_score(diff.overall_before)} -> {_score(diff.overall_after)} ({_delta(overall['delta'])})"]
    for item in diff.runbooks:
        flag = "  BAND DROPPED" if item.band_dropped else ""
        lines.append(
            f"  {item.runbook_id}: {_score(item.before)} -> {_score(item.after)} ({_delta(item.delta)})"
            f"  {item.band_before or '-'} -> {item.band_after or '-'}{flag}"
        )
    for title, items in (("New failures", diff.new_failures), ("Fixed", diff.fixed), ("Other changes", diff.other_changes)):
        lines.append(f"{title}: {len(items)}")
        for change in items:
            lines.append(
                f"  {change.runbook_id} {change.check} {change.target}: "
                f"{change.before or 'absent'} -> {change.after or 'absent'}"
                + (f" ({change.message})" if change.message and change.after else "")
            )
    if diff.added_runbooks:
        lines.append("Added runbooks: " + ", ".join(diff.added_runbooks))
    if diff.removed_runbooks:
        lines.append("Removed runbooks: " + ", ".join(diff.removed_runbooks))
    lines.append("Result: regression" if diff.regressed else "Result: no regression")
    return "\n".join(lines) + "\n"


def _cell(value: object) -> str:
    return str(value).replace("|", "\\|").replace("\n", " ")


def render_diff_markdown(diff: ReportDiff) -> str:
    overall = diff.as_dict()["overall"]
    verdict = "**Regression**" if diff.regressed else "No regression"
    lines = [
        "## Runbook rehearsal: changes",
        "",
        f"{verdict}. Overall score {_score(diff.overall_before)} → {_score(diff.overall_after)} ({_delta(overall['delta'])}).",
        "",
        "| Runbook | Before | After | Δ | Band |",
        "| --- | --- | --- | --- | --- |",
    ]
    for item in diff.runbooks:
        band = f"{item.band_before or '-'} → {item.band_after or '-'}"
        if item.band_dropped:
            band += " ⚠"
        lines.append(
            f"| {_cell(item.runbook_id)} | {_score(item.before)} | {_score(item.after)} | {_delta(item.delta)} | {band} |"
        )
    for title, items in (("New failures", diff.new_failures), ("Fixed", diff.fixed), ("Other changes", diff.other_changes)):
        if not items:
            continue
        lines.extend(["", f"### {title} ({len(items)})", ""])
        for change in items:
            text = f"- `{_cell(change.runbook_id)}` {change.check} `{_cell(change.target)}`: {change.before or 'absent'} → {change.after or 'absent'}"
            if change.message and change.after:
                text += f". {_cell(change.message)}"
            lines.append(text)
    if diff.added_runbooks or diff.removed_runbooks:
        lines.append("")
        if diff.added_runbooks:
            lines.append("Added: " + ", ".join(f"`{item}`" for item in diff.added_runbooks))
        if diff.removed_runbooks:
            lines.append("Removed: " + ", ".join(f"`{item}`" for item in diff.removed_runbooks))
    lines.extend(["", "A dry run checks the written procedure and its references. It does not prove a restore works.", ""])
    return "\n".join(lines)


def render_diff_json(diff: ReportDiff) -> str:
    return json.dumps(diff.as_dict(), indent=2) + "\n"
