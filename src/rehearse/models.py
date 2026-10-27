"""Document and result types. No I/O."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from pathlib import Path


@dataclass(frozen=True)
class Owner:
    name: str
    email: str
    team: str | None = None


@dataclass(frozen=True)
class Review:
    last_reviewed: date
    interval_days: int
    max_age_days: int


@dataclass(frozen=True)
class Contact:
    name: str
    role: str
    email: str
    phone: str | None = None
    escalation_order: int | None = None


@dataclass(frozen=True)
class Asset:
    id: str
    kind: str
    target: str
    port: int | None = None
    language: str | None = None
    directory: str | None = None
    description: str | None = None


@dataclass(frozen=True)
class Precondition:
    id: str
    description: str
    evidence: str | None = None


@dataclass(frozen=True)
class Step:
    id: str
    title: str
    description: str
    expected_outcome: str
    owner: str | None = None
    duration_minutes: int | None = None
    prompts: list[str] = field(default_factory=list)
    assets: list[Asset] = field(default_factory=list)


@dataclass(frozen=True)
class Runbook:
    path: Path
    schema_version: str
    id: str
    title: str
    summary: str
    execution: str
    owner: Owner
    service: str
    severity: str
    frameworks: list[str]
    review: Review
    contacts: list[Contact]
    preconditions: list[Precondition]
    steps: list[Step]
    reviewed_by: str | None = None
    sha256: str = ""


@dataclass(frozen=True)
class Finding:
    check: str
    dimension: str
    status: str
    runbook_id: str
    target: str
    message: str
    evidence: dict = field(default_factory=dict)


def make_finding(
    *,
    check: str,
    dimension: str,
    status: str,
    runbook_id: str,
    target: str,
    message: str,
    **evidence: object,
) -> Finding:
    return Finding(
        check=check,
        dimension=dimension,
        status=status,
        runbook_id=runbook_id,
        target=target,
        message=message,
        evidence=dict(evidence),
    )


def iter_assets(runbook: Runbook, kind: str | None = None):
    for step in runbook.steps:
        for asset in step.assets:
            if kind is None or asset.kind == kind:
                yield step, asset
