"""Placeholder values left over from `rehearse init`.

The skeleton writes a contact named "Incident commander (replace)", an
`operations@example.org` address, and a `+1-555-010-0000` phone. A team that
copies the skeleton and edits only the title still passes `validate`, because
the schema cannot tell a real contact from a placeholder. This check can.

It is deliberately narrow: it looks for the three strings the scaffold writes
and nothing else, so it does not flag a real person whose name happens to
contain a dash or a real host under a `.internal` domain.
"""

from __future__ import annotations

from rehearse.checks.base import Check, CheckContext
from rehearse.models import Runbook, make_finding

# The fictional 555-0100 exchange is unassigned in real life, and the scaffold
# uses `+1-555-010-0000`. Matching `555-010` leaves the demo fixtures alone:
# their numbers are `+1-555-014-xxxx`.
PLACEHOLDER_PATTERNS = ("(replace)", "example.org", "555-010")


class PlaceholderCheck(Check):
    name = "placeholders"
    dimension = "completeness"

    def run(self, runbook: Runbook, ctx: CheckContext) -> list:
        hits: list[tuple[str, str, str, str]] = []
        for contact in runbook.contacts:
            fields = [("name", contact.name), ("email", contact.email)]
            if contact.phone:
                fields.append(("phone", contact.phone))
            for field, value in fields:
                for pattern in PLACEHOLDER_PATTERNS:
                    if pattern in value:
                        hits.append((contact.name, field, pattern, value))
        # The owner has no phone field in v0.1; check name and email only.
        for field, value in (("name", runbook.owner.name), ("email", runbook.owner.email)):
            for pattern in PLACEHOLDER_PATTERNS:
                if pattern in value:
                    hits.append((runbook.owner.name, field, pattern, value))
        for step in runbook.steps:
            for asset in step.assets:
                for pattern in PLACEHOLDER_PATTERNS:
                    if pattern in asset.target:
                        hits.append((asset.id, "target", pattern, asset.target))
        if not hits:
            return [
                make_finding(
                    check=self.name,
                    dimension=self.dimension,
                    status="pass",
                    runbook_id=runbook.id,
                    target=runbook.id,
                    message="no placeholder values from `rehearse init` remain",
                )
            ]
        findings = []
        for who, field, pattern, value in hits:
            findings.append(
                make_finding(
                    check=self.name,
                    dimension=self.dimension,
                    status="warn",
                    runbook_id=runbook.id,
                    target=who,
                    message=(
                        f"{field} still contains the placeholder {pattern!r} "
                        f"left by `rehearse init`: {value}"
                    ),
                )
            )
        return findings