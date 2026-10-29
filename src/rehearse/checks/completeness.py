"""Structural readiness that the schema deliberately does not require."""

from __future__ import annotations

import re

from rehearse.checks.base import Check, CheckContext
from rehearse.models import Runbook, make_finding

# Tokens left over from `rehearse init` or from a draft that was never edited.
# They are valid documents, so the schema accepts them; this check flags them.
PLACEHOLDER_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"\(replace\)", re.IGNORECASE), "contains the placeholder text '(replace)'"),
    (re.compile(r"example\.org", re.IGNORECASE), "uses the example.org domain"),
    (re.compile(r"555-010-\d{4}"), "looks like a placeholder 555 number"),
]


def _placeholder_hits(value: str) -> list[str]:
    return [message for pattern, message in PLACEHOLDER_PATTERNS if pattern.search(value)]


class CompletenessCheck(Check):
    name = "completeness"
    dimension = "completeness"

    def run(self, runbook: Runbook, ctx: CheckContext) -> list:
        findings = []
        high = runbook.severity in {"high", "critical"}
        if runbook.preconditions:
            findings.append(
                make_finding(
                    check=self.name,
                    dimension=self.dimension,
                    status="pass",
                    runbook_id=runbook.id,
                    target=runbook.id,
                    message=f"{len(runbook.preconditions)} precondition(s) recorded",
                )
            )
        elif high:
            findings.append(
                make_finding(
                    check=self.name,
                    dimension=self.dimension,
                    status="fail",
                    runbook_id=runbook.id,
                    target=runbook.id,
                    message="high or critical runbook has no preconditions",
                )
            )
        else:
            findings.append(
                make_finding(
                    check=self.name,
                    dimension=self.dimension,
                    status="warn",
                    runbook_id=runbook.id,
                    target=runbook.id,
                    message="no preconditions recorded",
                )
            )
        missing_owner = [step.id for step in runbook.steps if not step.owner]
        if missing_owner:
            findings.append(
                make_finding(
                    check=self.name,
                    dimension=self.dimension,
                    status="warn",
                    runbook_id=runbook.id,
                    target=", ".join(missing_owner),
                    message="steps without an owner: " + ", ".join(missing_owner),
                )
            )
        else:
            findings.append(
                make_finding(
                    check=self.name,
                    dimension=self.dimension,
                    status="pass",
                    runbook_id=runbook.id,
                    target=runbook.id,
                    message="every step names an owner",
                )
            )
        thin = [
            step.id
            for step in runbook.steps
            if len(step.expected_outcome.strip()) < 3 or len(step.description.strip()) < 3
        ]
        if thin:
            findings.append(
                make_finding(
                    check=self.name,
                    dimension=self.dimension,
                    status="fail",
                    runbook_id=runbook.id,
                    target=", ".join(thin),
                    message="steps missing a description or expected outcome: " + ", ".join(thin),
                )
            )
        else:
            findings.append(
                make_finding(
                    check=self.name,
                    dimension=self.dimension,
                    status="pass",
                    runbook_id=runbook.id,
                    target=runbook.id,
                    message="every step states an expected outcome",
                )
            )
        findings.extend(self._placeholder_findings(runbook))
        return findings

    def _placeholder_findings(self, runbook: Runbook) -> list:
        """Flag draft tokens left over from `rehearse init`."""
        hits: list[tuple[str, str]] = []
        hits.extend(_placeholder_hits(runbook.owner.name))
        hits.extend(_placeholder_hits(runbook.owner.email))
        for contact in runbook.contacts:
            hits.extend(_placeholder_hits(contact.name))
            hits.extend(_placeholder_hits(contact.email))
            if contact.phone:
                hits.extend(_placeholder_hits(contact.phone))
        for step in runbook.steps:
            hits.extend(_placeholder_hits(step.description))
            hits.extend(_placeholder_hits(step.expected_outcome))
            for asset in step.assets:
                hits.extend(_placeholder_hits(asset.target))
                if asset.description:
                    hits.extend(_placeholder_hits(asset.description))
        if not hits:
            return [
                make_finding(
                    check=self.name,
                    dimension=self.dimension,
                    status="pass",
                    runbook_id=runbook.id,
                    target=runbook.id,
                    message="no draft placeholders found",
                )
            ]
        unique: list[str] = []
        for hit in hits:
            if hit not in unique:
                unique.append(hit)
        return [
            make_finding(
                check=self.name,
                dimension=self.dimension,
                status="warn",
                runbook_id=runbook.id,
                target=runbook.id,
                message="draft placeholder left in the runbook: " + "; ".join(unique),
            )
        ]
