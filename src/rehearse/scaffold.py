"""Write a new runbook skeleton that passes `rehearse validate`."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date
from pathlib import Path

from rehearse.models import Contact

ID_PATTERN = re.compile(r"^[a-z0-9][a-z0-9-]{2,63}$")
SEVERITIES = ("low", "medium", "high", "critical")

TEMPLATE = """\
# yaml-language-server: $schema={schema_ref}
# Created by `rehearse init`. Replace every placeholder, then run:
#   rehearse validate {file_name}
#   rehearse check {file_name} --offline
schemaVersion: "1.0"
id: {runbook_id}
title: {title}
summary: >
  One or two sentences: what breaks, who notices, and what this procedure restores.
execution: observe-only
service: {service}
severity: {severity}
frameworks: []
owner:
  name: {owner_name}
  email: {owner_email}
  team: {owner_team}
review:
  lastReviewed: "{today}"
  intervalDays: {interval}
  maxAgeDays: {max_age}
contacts:
{contacts_yaml}
preconditions:
  - id: backup-known
    description: A restorable backup or snapshot is named before any change starts.
steps:
  - id: declare
    title: Declare the incident
    owner: Incident commander
    description: Announce the outage in the incident channel and name a note-taker.
    expectedOutcome: The commander acknowledges and a note-taker is named.
    durationMinutes: 10
    prompts:
      - Who is taking notes?
    assets: []
  - id: check-references
    title: Check the systems this procedure depends on
    owner: Operator on call
    description: Confirm each host, URL, group, file, and script below before acting. Do not restart anything in this step.
    expectedOutcome: Each reference is healthy or written down as broken.
    durationMinutes: 20
    assets: []
    # Examples (uncomment and adapt):
    # assets:
    #   - id: app-host
    #     kind: host
    #     target: app01.example.org
    #     port: 443
    #   - id: status-page
    #     kind: url
    #     target: https://status.example.org/app
    #   - id: restore-note
    #     kind: file
    #     target: docs/restore-app.md
    #   - id: health-script
    #     kind: script
    #     target: scripts/Test-App.ps1
    #     language: powershell
"""


class ScaffoldError(ValueError):
    pass


@dataclass
class ScaffoldOwner:
    name: str
    email: str
    team: str | None = None


def _format_owner(owner: ScaffoldOwner) -> dict:
    return {
        "owner_name": _yaml_scalar(owner.name),
        "owner_email": _yaml_scalar(owner.email),
        "owner_team": _yaml_scalar(owner.team or "operations"),
    }


def _format_contacts(contacts: list[Contact]) -> str:
    if not contacts:
        return _default_contacts_yaml()
    lines = []
    for c in contacts:
        phone_line = f'    phone: {_yaml_scalar(c.phone)}' if c.phone else ''
        esc_line = f'    escalationOrder: {c.escalation_order}' if c.escalation_order is not None else ''
        lines.append(f"""  - name: {_yaml_scalar(c.name)}
    role: {_yaml_scalar(c.role)}
    email: {_yaml_scalar(c.email)}"""
        )
        if phone_line:
            lines[-1] += f"\n{phone_line}"
        if esc_line:
            lines[-1] += f"\n{esc_line}"
    return "\n".join(lines)


def _default_contacts_yaml() -> str:
    return """  - name: Incident commander (replace)
    role: Incident commander
    email: commander@example.org
    phone: "+1-555-010-0000"
    escalationOrder: 1"""


def render_scaffold(
    runbook_id: str,
    *,
    title: str | None = None,
    service: str | None = None,
    severity: str = "high",
    today: date | None = None,
    file_name: str = "runbook.yaml",
    schema_ref: str = "https://raw.githubusercontent.com/Abbasi26/runbook-rehearsal/main/schema/runbook.schema.json",
    owner: ScaffoldOwner | None = None,
    contacts: list[Contact] | None = None,
) -> str:
    if not ID_PATTERN.fullmatch(runbook_id):
        raise ScaffoldError(
            f"id {runbook_id!r} must be 3 to 64 lowercase letters, digits, or dashes and start with a letter or digit"
        )
    if severity not in SEVERITIES:
        raise ScaffoldError(f"severity must be one of {', '.join(SEVERITIES)}")
    interval, max_age = (90, 180) if severity in {"high", "critical"} else (180, 365)
    readable = title or runbook_id.replace("-", " ").capitalize()

    default_owner = ScaffoldOwner(name="Operations team", email="operations@example.org", team="operations")
    owner_data = _format_owner(owner or default_owner)
    contacts_yaml = _format_contacts(contacts or [])

    return TEMPLATE.format(
        schema_ref=schema_ref,
        file_name=file_name,
        runbook_id=runbook_id,
        title=_yaml_scalar(readable),
        service=_yaml_scalar(service or runbook_id),
        severity=severity,
        today=(today or date.today()).isoformat(),
        interval=interval,
        max_age=max_age,
        **owner_data,
        contacts_yaml=contacts_yaml,
    )


def _yaml_scalar(value: str) -> str:
    if re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9 _.-]*", value):
        return value
    escaped = value.replace("\\", "\\\\").replace('"', '\\"')
    return f'"{escaped}"'


def write_scaffold(path: Path, text: str, *, force: bool = False) -> Path:
    if path.exists() and not force:
        raise ScaffoldError(f"{path} exists; pass --force to overwrite")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path
