"""Run every check and build a report object."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from pathlib import Path

from rehearse import __version__
from rehearse.checks import default_checks
from rehearse.checks.base import CheckContext
from rehearse.config import Config
from rehearse.directory import build_directory
from rehearse.models import Finding, Runbook, make_finding
from rehearse.network import build_network
from rehearse.runbook_load import LoadError, load_runbook
from rehearse.scoring import WEIGHTS, Score, overall_score, score_findings

DISCLAIMER = (
    "Use this report as evidence that the referenced runbooks were dry-run "
    "checked at the time below. A certification body, an internal audit, or "
    "the responsible operator decides what that means for NIS2, ISO/IEC 27001, "
    "or BSI IT-Grundschutz. The score is the weighted freshness and reference "
    "health figure defined by RunbookRehearsal. A reachable host, a well-formed "
    "number, and a high score can still describe the wrong procedure."
)

FRAMEWORK_NOTES = (
    {
        "id": "NIS2 Article 21(2)(b)",
        "theme": "Incident handling",
        "shows": "The procedure names owners, escalation contacts, and steps.",
        "limits": "It does not show detection coverage, a reporting workflow, or that people answer.",
    },
    {
        "id": "NIS2 Article 21(2)(c)",
        "theme": "Business continuity and crisis management",
        "shows": "Restore and continuity procedures are present, dated, and point at files and hosts.",
        "limits": "It does not show that a restore meets an RTO or RPO.",
    },
    {
        "id": "ISO/IEC 27001:2022 A.5.24, A.5.25, A.5.26",
        "theme": "Incident management planning, assessment, and response",
        "shows": "A written procedure, roles, and expected outcomes exist and were checked.",
        "limits": "It does not assess the incident process or classify live events.",
    },
    {
        "id": "ISO/IEC 27001:2022 A.5.29, A.5.30",
        "theme": "Information security during disruption, ICT readiness",
        "shows": "Referenced continuity steps and assets were checked for freshness and reachability.",
        "limits": "It does not test failover or backup restore.",
    },
    {
        "id": "ISO/IEC 27001:2022 A.5.37",
        "theme": "Documented operating procedures",
        "shows": "The operating procedure is structured, owned, and internally referenced.",
        "limits": "It does not show management approval.",
    },
    {
        "id": "BSI IT-Grundschutz DER.2.1 (Edition 2023) A3, A9, A14",
        "theme": "Responsibilities, reporting paths, escalation",
        "shows": "Named contacts and escalation numbers were shape-checked.",
        "limits": "It does not show that the reporting path is staffed. The compendium is under revision; map these identifiers to the edition you use.",
    },
    {
        "id": "BSI IT-Grundschutz DER.4 (Edition 2022) A1",
        "theme": "Emergency handbook",
        "shows": "Roles, immediate steps, and escalation data are present in the runbook.",
        "limits": "A runbook file is not a complete Notfallhandbuch.",
    },
    {
        "id": "BSI IT-Grundschutz DER.4 (Edition 2022) A10, A14",
        "theme": "Exercises and review of emergency measures",
        "shows": "Review dates are scored. rehearse tabletop can store a separate exercise record.",
        "limits": "A dry run is not a full exercise programme.",
    },
)


class Clock:
    def __init__(self, today: date | None = None):
        self._today = today

    def today(self) -> date:
        return self._today or date.today()


@dataclass
class RunbookResult:
    runbook: Runbook
    findings: list[Finding]
    score: Score


@dataclass
class Report:
    version: str
    generated_at: str
    mode: str
    probes_sent: bool
    directory_provider: str
    directory_note: str
    clock_date: str
    clock_pinned: bool
    clock_note: str | None
    disclaimer: str
    results: list[RunbookResult] = field(default_factory=list)
    errors: list[dict] = field(default_factory=list)
    overall: Score = field(default_factory=lambda: overall_score([]))
    weights: dict = field(default_factory=lambda: dict(WEIGHTS))
    framework_notes: tuple = FRAMEWORK_NOTES


def check_paths(
    paths: list[Path],
    config: Config,
    clock: Clock | None = None,
    checks=None,
) -> Report:
    pinned = False
    clock_note = None
    if config.mode == "offline" and config.clock_today is not None:
        clock = Clock(config.clock_today)
        pinned = True
        clock_note = (
            f"The review clock is pinned to {config.clock_today.isoformat()} "
            "because this run is offline. Live mode uses the machine date."
        )
    elif config.mode == "live" and config.clock_today is not None:
        clock_note = "clock.today was ignored because mode is live."
        if clock is None:
            clock = Clock()
    elif clock is None:
        clock = Clock()

    network = build_network(config)
    directory = build_directory(config)
    selected = checks if checks is not None else default_checks()
    results: list[RunbookResult] = []
    errors: list[dict] = []
    for path in paths:
        try:
            runbook = load_runbook(path)
        except LoadError as exc:
            errors.append({"path": str(path), "messages": list(exc.messages)})
            continue
        ctx = CheckContext(
            config=config,
            clock=clock,
            network=network,
            directory=directory,
        )
        findings: list[Finding] = []
        for check in selected:
            try:
                produced = check.run(runbook, ctx)
            except Exception as exc:  # noqa: BLE001 - one check should not hide the report
                produced = [
                    make_finding(
                        check=getattr(check, "name", "check"),
                        dimension=getattr(check, "dimension", "completeness"),
                        status="fail",
                        runbook_id=runbook.id,
                        target=getattr(check, "name", "check"),
                        message=f"check raised {exc.__class__.__name__}: {exc}",
                    )
                ]
            findings.extend(produced)
        results.append(
            RunbookResult(
                runbook=runbook,
                findings=findings,
                score=score_findings(findings),
            )
        )
    overall = overall_score(
        [item.score.value for item in results if item.score.value is not None]
    )
    return Report(
        version=__version__,
        generated_at=datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        mode=config.mode,
        probes_sent=config.mode == "live",
        directory_provider=config.directory_provider,
        directory_note=_directory_note(config.directory_provider),
        clock_date=clock.today().isoformat(),
        clock_pinned=pinned,
        clock_note=clock_note,
        disclaimer=DISCLAIMER,
        results=results,
        errors=errors,
        overall=overall,
        weights=dict(WEIGHTS),
    )


def _directory_note(provider: str) -> str:
    if provider == "stub":
        return (
            "Directory results come from the stub provider. They are a local "
            "list in the config file, not a read of Active Directory or Entra ID."
        )
    if provider == "ldap":
        return (
            "Directory results come from a read-only LDAP search made for this "
            "report. A hit means the directory returned the group at that time."
        )
    if provider == "graph":
        return (
            "Directory results come from a Microsoft Graph GET made for this "
            "report. A hit means Graph returned the group at that time."
        )
    return (
        "No directory provider is configured. Group findings are warnings and "
        "are not evidence that a group exists."
    )
