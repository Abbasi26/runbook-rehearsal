"""Structural readiness that the schema deliberately does not require."""

from __future__ import annotations

import re

from rehearse.checks.base import Check, CheckContext
from rehearse.models import Runbook, make_finding

PLACEHOLDER_DOMAIN_RE = re.compile(r"@example\.(?:org|com|net)\b|^https?://example\.(?:org|com|net)\b|^example\.(?:org|com|net)\b")
REPLACE_RE = re.compile(r"\(replace\)", re.IGNORECASE)
PLACEHOLDER_PHONE_RE = re.compile(r"^\+1-555-010-0000$")


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
        findings = []
        ph_domain = PLACEHOLDER_DOMAIN_RE
        ph_replace = REPLACE_RE
        ph_phone = PLACEHOLDER_PHONE_RE

        if ph_domain.search(runbook.owner.email):
            findings.append(
                make_finding(
                    check="placeholder",
                    dimension=self.dimension,
                    status="warn",
                    runbook_id=runbook.id,
                    target="owner.email",
                    message="owner email contains example.org placeholder domain",
                )
            )

        for contact in runbook.contacts:
            if ph_replace.search(contact.name):
                findings.append(
                    make_finding(
                        check="placeholder",
                        dimension=self.dimension,
                        status="warn",
                        runbook_id=runbook.id,
                        target=f"contact:{contact.name}",
                        message="contact name contains (replace) placeholder",
                    )
                )
            if ph_domain.search(contact.email):
                findings.append(
                    make_finding(
                        check="placeholder",
                        dimension=self.dimension,
                        status="warn",
                        runbook_id=runbook.id,
                        target=f"contact:{contact.name}.email",
                        message="contact email contains example.org placeholder domain",
                    )
                )
            if contact.phone and ph_phone.match(contact.phone):
                findings.append(
                    make_finding(
                        check="placeholder",
                        dimension=self.dimension,
                        status="warn",
                        runbook_id=runbook.id,
                        target=f"contact:{contact.name}.phone",
                        message="contact phone is the scaffold placeholder +1-555-010-0000",
                    )
                )

        for step in runbook.steps:
            if ph_replace.search(step.owner or ""):
                findings.append(
                    make_finding(
                        check="placeholder",
                        dimension=self.dimension,
                        status="warn",
                        runbook_id=runbook.id,
                        target=f"step:{step.id}.owner",
                        message="step owner contains (replace) placeholder",
                    )
                )
            if ph_replace.search(step.title):
                findings.append(
                    make_finding(
                        check="placeholder",
                        dimension=self.dimension,
                        status="warn",
                        runbook_id=runbook.id,
                        target=f"step:{step.id}.title",
                        message="step title contains (replace) placeholder",
                    )
                )
            if ph_replace.search(step.description):
                findings.append(
                    make_finding(
                        check="placeholder",
                        dimension=self.dimension,
                        status="warn",
                        runbook_id=runbook.id,
                        target=f"step:{step.id}.description",
                        message="step description contains (replace) placeholder",
                    )
                )
            if ph_replace.search(step.expected_outcome):
                findings.append(
                    make_finding(
                        check="placeholder",
                        dimension=self.dimension,
                        status="warn",
                        runbook_id=runbook.id,
                        target=f"step:{step.id}.expected_outcome",
                        message="step expected outcome contains (replace) placeholder",
                    )
                )
            for asset in step.assets:
                if asset.kind in {"url", "host"} and ph_domain.search(asset.target):
                    findings.append(
                        make_finding(
                            check="placeholder",
                            dimension=self.dimension,
                            status="warn",
                            runbook_id=runbook.id,
                            target=f"step:{step.id}.asset:{asset.id}",
                            message=f"{asset.kind} target contains example.org placeholder domain",
                        )
                    )
                if ph_replace.search(asset.description or ""):
                    findings.append(
                        make_finding(
                            check="placeholder",
                            dimension=self.dimension,
                            status="warn",
                            runbook_id=runbook.id,
                            target=f"step:{step.id}.asset:{asset.id}.description",
                            message="asset description contains (replace) placeholder",
                        )
                    )

        for pc in runbook.preconditions:
            if ph_replace.search(pc.description):
                findings.append(
                    make_finding(
                        check="placeholder",
                        dimension=self.dimension,
                        status="warn",
                        runbook_id=runbook.id,
                        target=f"precondition:{pc.id}.description",
                        message="precondition description contains (replace) placeholder",
                    )
                )

        return findings
