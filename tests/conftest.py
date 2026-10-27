"""Shared runbook factory for unit tests."""

from __future__ import annotations

from datetime import date
from pathlib import Path

from rehearse.models import Contact, Owner, Precondition, Review, Runbook, Step


def make_runbook(path: Path, **overrides) -> Runbook:
    path.write_text("placeholder\n", encoding="utf-8")
    values = dict(
        path=path,
        schema_version="1.0",
        id="sample-runbook",
        title="Sample runbook",
        summary="A sample runbook used by unit tests only.",
        execution="observe-only",
        owner=Owner("Ops", "ops@harborpine.example", "operations"),
        service="sample",
        severity="high",
        frameworks=["nis2"],
        review=Review(date(2026, 9, 1), 90, 180),
        contacts=[
            Contact(
                "Priya Nandakumar",
                "Incident commander",
                "priya.nandakumar@harborpine.example",
                "+1-555-014-2281",
                1,
            )
        ],
        preconditions=[Precondition("ready", "The maintenance window is open.")],
        steps=[
            Step(
                id="look",
                title="Look first",
                description="Read the service state before changing anything.",
                expected_outcome="The operator records the state they saw.",
                owner="Operator",
            )
        ],
        reviewed_by="Test Reviewer",
        sha256="abc",
    )
    values.update(overrides)
    return Runbook(**values)
