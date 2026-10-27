"""Contact shape. This does not send mail or dial numbers."""

from __future__ import annotations

import re

from rehearse.checks.base import Check, CheckContext
from rehearse.models import Runbook, make_finding

EMAIL_RE = re.compile(r"^[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}$")


def valid_email(value: str) -> bool:
    return bool(EMAIL_RE.fullmatch(value.strip()))


def normalize_phone(value: str) -> str | None:
    compact = re.sub(r"[\s().-]", "", value.strip())
    if re.fullmatch(r"\+[1-9]\d{7,14}", compact):
        return compact
    return None


class ContactCheck(Check):
    name = "contact-format"
    dimension = "contacts"

    def run(self, runbook: Runbook, ctx: CheckContext) -> list:
        findings = []
        findings.append(self._email_finding(runbook, "owner", runbook.owner.email))
        usable_escalation = False
        for contact in runbook.contacts:
            findings.append(self._email_finding(runbook, contact.name, contact.email))
            phone_ok = False
            if contact.phone:
                normalized = normalize_phone(contact.phone)
                if normalized:
                    phone_ok = True
                    findings.append(
                        make_finding(
                            check="contact-format",
                            dimension=self.dimension,
                            status="pass",
                            runbook_id=runbook.id,
                            target=contact.name,
                            message="phone number has a leading + and 8 to 15 digits",
                        )
                    )
                else:
                    findings.append(
                        make_finding(
                            check="contact-format",
                            dimension=self.dimension,
                            status="fail",
                            runbook_id=runbook.id,
                            target=contact.name,
                            message=(
                                "phone number is not usable; expected a leading + "
                                "and 8 to 15 digits, separators allowed"
                            ),
                        )
                    )
            elif contact.escalation_order is not None:
                findings.append(
                    make_finding(
                        check="contact-format",
                        dimension=self.dimension,
                        status="fail",
                        runbook_id=runbook.id,
                        target=contact.name,
                        message="escalation contact has no phone number",
                    )
                )
            if (
                contact.escalation_order is not None
                and valid_email(contact.email)
                and (phone_ok or (contact.phone and normalize_phone(contact.phone)))
            ):
                usable_escalation = True
        findings.append(self._escalation_finding(runbook, usable_escalation))
        return findings

    def _email_finding(self, runbook: Runbook, target: str, email: str):
        if valid_email(email):
            return make_finding(
                check="contact-format",
                dimension=self.dimension,
                status="pass",
                runbook_id=runbook.id,
                target=target,
                message="email address is well formed",
            )
        return make_finding(
            check="contact-format",
            dimension=self.dimension,
            status="fail",
            runbook_id=runbook.id,
            target=target,
            message="email address is not well formed",
        )

    def _escalation_finding(self, runbook: Runbook, usable: bool):
        high = runbook.severity in {"high", "critical"}
        if usable:
            status = "pass"
            message = "at least one escalation contact has a well-formed email and phone"
        elif high:
            status = "fail"
            message = "high or critical runbook has no escalation contact with a well-formed email and phone"
        else:
            status = "warn"
            message = "no escalation contact with a well-formed email and phone"
        return make_finding(
            check="escalation",
            dimension=self.dimension,
            status=status,
            runbook_id=runbook.id,
            target=runbook.id,
            message=message,
        )
