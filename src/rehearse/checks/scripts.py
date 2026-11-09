"""Script syntax check. Parse only."""

from __future__ import annotations

from rehearse.checks.base import Check, CheckContext
from rehearse.checks.files import OutsideRootError, resolve_reference
from rehearse.models import Runbook, iter_assets, make_finding
from rehearse.syntax import check_script


class ScriptCheck(Check):
    name = "script-syntax"
    dimension = "references"

    def run(self, runbook: Runbook, ctx: CheckContext) -> list:
        findings = []
        for _step, asset in iter_assets(runbook, "script"):
            try:
                path = resolve_reference(runbook.path, asset.target, ctx.config.root)
            except OutsideRootError as exc:
                findings.append(
                    make_finding(
                        check=self.name,
                        dimension=self.dimension,
                        status="fail",
                        runbook_id=runbook.id,
                        target=asset.target,
                        message="resolved path is outside content root",
                        asset=asset.id,
                        language=asset.language,
                        resolved=str(exc.resolved),
                    )
                )
                continue
            result = check_script(path, asset.language)
            findings.append(
                make_finding(
                    check=self.name,
                    dimension=self.dimension,
                    status=result.status,
                    runbook_id=runbook.id,
                    target=asset.target,
                    message=result.message,
                    asset=asset.id,
                    language=asset.language,
                    details=result.details,
                )
            )
        return findings
