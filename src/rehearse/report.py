"""Text, Markdown, HTML, and JSON renderers. Reports stay on disk."""

from __future__ import annotations

import html
import json
from pathlib import Path

from rehearse.engine import Report
from rehearse.models import Finding
from rehearse.scoring import STATUS_VALUE

_STATUS_LABEL = {
    "pass": "Pass",
    "warn": "Warn",
    "fail": "Fail",
    "skip": "Skip",
}


def display_path(path: Path) -> str:
    resolved = path.resolve()
    try:
        return str(resolved.relative_to(Path.cwd().resolve()))
    except ValueError:
        return str(resolved)


def render_text(report: Report) -> str:
    lines: list[str] = []
    lines.append(f"RunbookRehearsal {report.version}")
    if report.probes_sent:
        lines.append("Mode: live. DNS, TCP, and HTTP probes were sent to named targets.")
    else:
        lines.append("Mode: offline fixtures. No DNS, TCP, or HTTP probes were sent.")
    lines.append(f"Clock: {report.clock_date}" + (" (pinned)" if report.clock_pinned else ""))
    lines.append(f"Directory: {report.directory_provider}")
    if report.clock_note:
        lines.append(report.clock_note)
    lines.append(report.directory_note)
    lines.append("")
    header = ("Runbook", "Score", "Band", "Pass", "Warn", "Fail", "Skip")
    rows = [header]
    for result in report.results:
        counts = result.score.counts
        score = "n/a" if result.score.value is None else f"{result.score.value:.1f}"
        rows.append(
            (
                result.runbook.id,
                score,
                result.score.band_label,
                str(counts.get("pass", 0)),
                str(counts.get("warn", 0)),
                str(counts.get("fail", 0)),
                str(counts.get("skip", 0)),
            )
        )
    overall = "n/a" if report.overall.value is None else f"{report.overall.value:.1f}"
    rows.append(
        (
            "Overall",
            overall,
            report.overall.band_label,
            "",
            "",
            "",
            "",
        )
    )
    widths = [max(len(row[index]) for row in rows) for index in range(len(header))]
    for row in rows:
        lines.append("  ".join(cell.ljust(widths[index]) for index, cell in enumerate(row)).rstrip())
    failures = [
        finding
        for result in report.results
        for finding in result.findings
        if finding.status == "fail"
    ]
    if failures:
        lines.append("")
        lines.append("Failed checks:")
        for finding in failures:
            lines.append(f"  [{finding.runbook_id}] {finding.check} {finding.target}: {finding.message}")
    if report.errors:
        lines.append("")
        lines.append("Runbooks that did not load:")
        for error in report.errors:
            for message in error["messages"]:
                lines.append(f"  {error['path']}: {message}")
    lines.append("")
    lines.append(report.disclaimer)
    lines.append("")
    return "\n".join(lines)


def render_markdown(report: Report) -> str:
    lines: list[str] = []
    lines.append("# Runbook maturity report")
    lines.append("")
    lines.append(f"RunbookRehearsal {report.version} · {report.generated_at}")
    lines.append("")
    lines.append(f"> {report.disclaimer}")
    lines.append("")
    lines.append("## How this run was made")
    lines.append("")
    if report.probes_sent:
        lines.append("- Mode: live. DNS, TCP, and HTTP probes were sent to named targets.")
    else:
        lines.append("- Mode: offline fixtures. No DNS, TCP, or HTTP probes were sent.")
    lines.append(
        f"- Review clock: {report.clock_date}"
        + (" (pinned for an offline run)." if report.clock_pinned else ".")
    )
    if report.clock_note:
        lines.append(f"- {report.clock_note}")
    lines.append(f"- Directory provider: `{report.directory_provider}`. {report.directory_note}")
    lines.append("")
    score = "n/a" if report.overall.value is None else f"{report.overall.value:.1f}"
    lines.append("## Overall")
    lines.append("")
    lines.append(f"**{score}** · {report.overall.band_label}")
    lines.append("")
    lines.append("| Runbook | Score | Band | Pass | Warn | Fail | Skip |")
    lines.append("| --- | ---: | --- | ---: | ---: | ---: | ---: |")
    for result in report.results:
        counts = result.score.counts
        value = "n/a" if result.score.value is None else f"{result.score.value:.1f}"
        lines.append(
            "| {id} | {score} | {band} | {p} | {w} | {f} | {s} |".format(
                id=_md(result.runbook.id),
                score=value,
                band=_md(result.score.band_label),
                p=counts.get("pass", 0),
                w=counts.get("warn", 0),
                f=counts.get("fail", 0),
                s=counts.get("skip", 0),
            )
        )
    lines.append("")
    lines.append("Scores use the weights in the JSON report. Skip findings are left out of the average.")
    lines.append("")
    for result in report.results:
        runbook = result.runbook
        lines.append(f"## {runbook.title}")
        lines.append("")
        lines.append(f"- Id: `{runbook.id}`")
        lines.append(f"- File: `{display_path(runbook.path)}`")
        lines.append(f"- SHA-256: `{runbook.sha256}`")
        lines.append(f"- Service: {_md(runbook.service)}")
        lines.append(f"- Severity: {runbook.severity}")
        lines.append(f"- Owner: {_md(runbook.owner.name)} ({_md(runbook.owner.email)})")
        if runbook.reviewed_by:
            lines.append(f"- Reviewed by: {_md(runbook.reviewed_by)}")
        if runbook.frameworks:
            lines.append("- Framework tags: " + ", ".join(runbook.frameworks))
        value = "n/a" if result.score.value is None else f"{result.score.value:.1f}"
        lines.append(f"- Score: **{value}** ({result.score.band_label})")
        lines.append("")
        lines.append("| Check | Status | Target | Message |")
        lines.append("| --- | --- | --- | --- |")
        for finding in result.findings:
            lines.append(
                "| {check} | {status} | {target} | {message} |".format(
                    check=_md(finding.check),
                    status=_STATUS_LABEL.get(finding.status, finding.status),
                    target=_md(finding.target),
                    message=_md(finding.message),
                )
            )
        lines.append("")
    lines.append("## Reading this as evidence")
    lines.append("")
    lines.append("| Reference | What this report shows | Limit |")
    lines.append("| --- | --- | --- |")
    for note in report.framework_notes:
        lines.append(
            f"| {_md(note['id'])} | {_md(note['shows'])} | {_md(note['limits'])} |"
        )
    lines.append("")
    if report.errors:
        lines.append("## Files that did not load")
        lines.append("")
        for error in report.errors:
            lines.append(f"- `{error['path']}`")
            for message in error["messages"]:
                lines.append(f"  - {_md(message)}")
        lines.append("")
    return "\n".join(lines)


def render_html(report: Report) -> str:
    score = "n/a" if report.overall.value is None else f"{report.overall.value:.1f}"
    width = 0 if report.overall.value is None else max(0, min(100, report.overall.value))
    rows = []
    for result in report.results:
        counts = result.score.counts
        value = "n/a" if result.score.value is None else f"{result.score.value:.1f}"
        rows.append(
            "<tr>"
            f"<td>{_esc(result.runbook.id)}</td>"
            f"<td class='num'>{value}</td>"
            f"<td>{_esc(result.score.band_label)}</td>"
            f"<td class='num'>{counts.get('pass', 0)}</td>"
            f"<td class='num'>{counts.get('warn', 0)}</td>"
            f"<td class='num'>{counts.get('fail', 0)}</td>"
            f"<td class='num'>{counts.get('skip', 0)}</td>"
            "</tr>"
        )
    sections = []
    for result in report.results:
        runbook = result.runbook
        value = "n/a" if result.score.value is None else f"{result.score.value:.1f}"
        finding_rows = []
        for finding in result.findings:
            finding_rows.append(
                "<tr>"
                f"<td>{_esc(finding.check)}</td>"
                f"<td><span class='pill {finding.status}'>{_esc(_STATUS_LABEL.get(finding.status, finding.status))}</span></td>"
                f"<td><code>{_esc(finding.target)}</code></td>"
                f"<td>{_esc(finding.message)}</td>"
                "</tr>"
            )
        meta = [
            f"<li>File <code>{_esc(display_path(runbook.path))}</code></li>",
            f"<li>SHA-256 <code>{_esc(runbook.sha256)}</code></li>",
            f"<li>Service {_esc(runbook.service)} · severity {_esc(runbook.severity)}</li>",
            f"<li>Owner {_esc(runbook.owner.name)} · {_esc(runbook.owner.email)}</li>",
        ]
        if runbook.reviewed_by:
            meta.append(f"<li>Reviewed by {_esc(runbook.reviewed_by)}</li>")
        sections.append(
            f"<section class='runbook'><h2>{_esc(runbook.title)}</h2>"
            f"<p class='scoreline'><strong>{value}</strong> {_esc(result.score.band_label)}</p>"
            f"<ul class='meta'>{''.join(meta)}</ul>"
            "<table><thead><tr><th>Check</th><th>Status</th><th>Target</th><th>Message</th></tr></thead>"
            f"<tbody>{''.join(finding_rows)}</tbody></table></section>"
        )
    notes = []
    for note in report.framework_notes:
        notes.append(
            "<tr>"
            f"<td>{_esc(note['id'])}</td>"
            f"<td>{_esc(note['theme'])}</td>"
            f"<td>{_esc(note['shows'])}</td>"
            f"<td>{_esc(note['limits'])}</td>"
            "</tr>"
        )
    mode = (
        "Live. DNS, TCP, and HTTP probes were sent to named targets."
        if report.probes_sent
        else "Offline fixtures. No DNS, TCP, or HTTP probes were sent."
    )
    clock = _esc(report.clock_date) + (" (pinned)" if report.clock_pinned else "")
    error_block = ""
    if report.errors:
        items = []
        for error in report.errors:
            messages = "".join(f"<li>{_esc(message)}</li>" for message in error["messages"])
            items.append(f"<li><code>{_esc(error['path'])}</code><ul>{messages}</ul></li>")
        error_block = f"<section><h2>Files that did not load</h2><ul>{''.join(items)}</ul></section>"
    clock_note = f"<p>{_esc(report.clock_note)}</p>" if report.clock_note else ""
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Runbook maturity report</title>
<style>
:root {{
  --ink: #221c16;
  --paper: #f4efe4;
  --card: #fbf7f0;
  --rule: #d9d0c1;
  --green: #1f4d3a;
  --fail: #8f2d2d;
  --warn: #8a5a12;
  --pass: #1f4d3a;
  --skip: #5c564c;
}}
* {{ box-sizing: border-box; }}
body {{
  margin: 0;
  background: var(--paper);
  color: var(--ink);
  font-family: Georgia, "Iowan Old Style", Palatino, "Palatino Linotype", serif;
  line-height: 1.45;
}}
main {{
  max-width: 980px;
  margin: 0 auto;
  padding: 32px 20px 64px;
}}
header.dossier {{
  border-top: 8px solid var(--green);
  background: var(--card);
  padding: 24px 24px 8px;
  border-bottom: 1px solid var(--rule);
}}
.kicker {{
  font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
  letter-spacing: 0.08em;
  text-transform: uppercase;
  font-size: 12px;
  margin: 0 0 8px;
}}
h1 {{ font-weight: 600; font-size: 2.1rem; margin: 0 0 8px; }}
h2 {{ font-size: 1.35rem; margin: 0 0 8px; }}
.disclaimer {{
  background: #fff;
  border-left: 4px solid var(--green);
  padding: 12px 14px;
  margin: 16px 0;
}}
.scoreblock {{
  display: flex;
  gap: 24px;
  align-items: center;
  flex-wrap: wrap;
  margin: 12px 0 20px;
}}
.bignum {{
  font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
  font-size: 3rem;
  line-height: 1;
}}
.meter {{
  flex: 1;
  min-width: 180px;
  height: 14px;
  background: #e4dccb;
  border-radius: 99px;
  overflow: hidden;
}}
.meter span {{
  display: block;
  height: 100%;
  background: var(--green);
}}
table {{
  width: 100%;
  border-collapse: collapse;
  background: var(--card);
  margin: 8px 0 24px;
  font-size: 0.95rem;
}}
th, td {{
  text-align: left;
  padding: 8px 10px;
  border-bottom: 1px solid var(--rule);
  vertical-align: top;
}}
.num {{ text-align: right; font-variant-numeric: tabular-nums; }}
code {{
  font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
  font-size: 0.86em;
}}
.pill {{
  display: inline-block;
  min-width: 3.2rem;
  text-align: center;
  border-radius: 99px;
  padding: 1px 8px;
  font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
  font-size: 0.78rem;
}}
.pill.pass {{ background: #e5f2ea; color: var(--pass); }}
.pill.warn {{ background: #f8efd8; color: var(--warn); }}
.pill.fail {{ background: #f8e4e0; color: var(--fail); }}
.pill.skip {{ background: #ece8e1; color: var(--skip); }}
.runbook {{ margin-top: 28px; }}
.meta {{ margin-top: 0; }}
.scoreline {{ font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace; }}
@media (max-width: 720px) {{
  table, thead, tbody, th, td, tr {{ display: block; }}
  thead {{ display: none; }}
  td {{ border-bottom: 0; padding: 4px 10px; }}
  tr {{ border-bottom: 1px solid var(--rule); padding: 8px 0; }}
}}
@media print {{
  body {{ background: white; }}
  main {{ max-width: none; }}
}}
</style>
</head>
<body>
<main>
<header class="dossier">
<p class="kicker">RunbookRehearsal {_esc(report.version)} · evidence copy · {_esc(report.generated_at)}</p>
<h1>Runbook maturity</h1>
<p class="disclaimer">{_esc(report.disclaimer)}</p>
<div class="scoreblock">
<div>
<div class="bignum">{_esc(score)}</div>
<div>{_esc(report.overall.band_label)}</div>
</div>
<div class="meter" role="img" aria-label="score { _esc(score) } of 100"><span style="width: {width:.1f}%"></span></div>
</div>
<p>{_esc(mode)}</p>
<p>Review clock {clock}.</p>
{clock_note}
<p>Directory provider <code>{_esc(report.directory_provider)}</code>. {_esc(report.directory_note)}</p>
</header>
<h2>Runbooks</h2>
<table>
<thead><tr><th>Runbook</th><th>Score</th><th>Band</th><th>Pass</th><th>Warn</th><th>Fail</th><th>Skip</th></tr></thead>
<tbody>
{''.join(rows)}
</tbody>
</table>
{''.join(sections)}
<section>
<h2>Reading this as evidence</h2>
<table>
<thead><tr><th>Reference</th><th>Theme</th><th>What this report shows</th><th>Limit</th></tr></thead>
<tbody>
{''.join(notes)}
</tbody>
</table>
</section>
{error_block}
</main>
</body>
</html>
"""


def render_json(report: Report) -> str:
    payload = {
        "tool": "runbookrehearsal",
        "version": report.version,
        "generatedAt": report.generated_at,
        "mode": report.mode,
        "probesSent": report.probes_sent,
        "directoryProvider": report.directory_provider,
        "directoryNote": report.directory_note,
        "clockDate": report.clock_date,
        "clockPinned": report.clock_pinned,
        "clockNote": report.clock_note,
        "disclaimer": report.disclaimer,
        "weights": report.weights,
        "statusValues": {key: STATUS_VALUE.get(key) for key in ("pass", "warn", "fail")},
        "overall": _score_json(report.overall, len(report.results)),
        "runbooks": [_result_json(result) for result in report.results],
        "errors": report.errors,
        "frameworkNotes": list(report.framework_notes),
    }
    return json.dumps(payload, indent=2, sort_keys=False) + "\n"


def write_reports(report: Report, output: Path) -> dict[str, Path]:
    output = output.expanduser()
    if output.exists() and not output.is_dir():
        raise NotADirectoryError(f"output path is a file: {output}")
    output.mkdir(parents=True, exist_ok=True)
    targets = {
        "html": output / "report.html",
        "md": output / "report.md",
        "json": output / "report.json",
    }
    targets["html"].write_text(render_html(report), encoding="utf-8")
    targets["md"].write_text(render_markdown(report), encoding="utf-8")
    targets["json"].write_text(render_json(report), encoding="utf-8")
    return targets


def _result_json(result) -> dict:
    runbook = result.runbook
    return {
        "id": runbook.id,
        "title": runbook.title,
        "path": display_path(runbook.path),
        "sha256": runbook.sha256,
        "service": runbook.service,
        "severity": runbook.severity,
        "owner": {"name": runbook.owner.name, "email": runbook.owner.email, "team": runbook.owner.team},
        "reviewedBy": runbook.reviewed_by,
        "frameworks": runbook.frameworks,
        "score": result.score.value,
        "band": result.score.band,
        "bandLabel": result.score.band_label,
        "counts": result.score.counts,
        "dimensions": [
            {
                "dimension": item.dimension,
                "weight": item.weight,
                "effectiveWeight": item.effective_weight,
                "ratio": item.ratio,
                "contribution": item.contribution,
                "counts": item.counts,
            }
            for item in result.score.dimensions
        ],
        "findings": [_finding_json(finding) for finding in result.findings],
    }


def _finding_json(finding: Finding) -> dict:
    return {
        "check": finding.check,
        "dimension": finding.dimension,
        "status": finding.status,
        "runbookId": finding.runbook_id,
        "target": finding.target,
        "message": finding.message,
        "evidence": _jsonable(finding.evidence),
    }


def _score_json(score, runbooks: int) -> dict:
    return {
        "score": score.value,
        "band": score.band,
        "bandLabel": score.band_label,
        "runbooks": runbooks,
    }


def _jsonable(value):
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    if isinstance(value, dict):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(item) for item in value]
    return str(value)


def _esc(value: object) -> str:
    return html.escape(str(value), quote=True)


def _md(value: object) -> str:
    return str(value).replace("|", "\\|").replace("\n", " ")
