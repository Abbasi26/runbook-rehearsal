"""Structural readiness that the schema deliberately does not require."""

from __future__ import annotations

from rehearse.checks.base import Check, CheckContext
from rehearse.models import Runbook, make_finding


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
        return findings
