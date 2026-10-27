"""Review-date staleness. One finding per runbook."""

from __future__ import annotations

from rehearse.checks.base import Check, CheckContext
from rehearse.models import Runbook, make_finding


class FreshnessCheck(Check):
    name = "freshness"
    dimension = "freshness"

    def run(self, runbook: Runbook, ctx: CheckContext) -> list:
        today = ctx.clock.today()
        age = (today - runbook.review.last_reviewed).days
        target = runbook.review.last_reviewed.isoformat()
        if age < 0:
            return [
                make_finding(
                    check=self.name,
                    dimension=self.dimension,
                    status="fail",
                    runbook_id=runbook.id,
                    target=target,
                    message=f"lastReviewed is {abs(age)} days in the future",
                    ageDays=age,
                )
            ]
        overdue_by = age - runbook.review.interval_days
        past_max = age > runbook.review.max_age_days
        if past_max or overdue_by > 0:
            parts = [f"last reviewed {age} days ago"]
            if overdue_by > 0:
                parts.append(
                    f"review interval is {runbook.review.interval_days} days "
                    f"(overdue by {overdue_by})"
                )
            if past_max:
                parts.append(f"maximum age is {runbook.review.max_age_days} days")
            return [
                make_finding(
                    check=self.name,
                    dimension=self.dimension,
                    status="fail",
                    runbook_id=runbook.id,
                    target=target,
                    message="; ".join(parts),
                    ageDays=age,
                )
            ]
        remaining = runbook.review.interval_days - age
        due_soon = ctx.config.due_soon_days
        if remaining <= due_soon:
            return [
                make_finding(
                    check=self.name,
                    dimension=self.dimension,
                    status="warn",
                    runbook_id=runbook.id,
                    target=target,
                    message=f"review due in {remaining} days",
                    ageDays=age,
                )
            ]
        return [
            make_finding(
                check=self.name,
                dimension=self.dimension,
                status="pass",
                runbook_id=runbook.id,
                target=target,
                message=(
                    f"reviewed {age} days ago; next review in {remaining} days"
                ),
                ageDays=age,
            )
        ]
