"""Directory group existence. Unconfigured providers produce a warning, not a pass."""

from __future__ import annotations

from rehearse.checks.base import Check, CheckContext
from rehearse.models import Runbook, iter_assets, make_finding


class GroupCheck(Check):
    name = "group-exists"
    dimension = "directory"

    def run(self, runbook: Runbook, ctx: CheckContext) -> list:
        findings = []
        provider = ctx.config.directory_provider
        for _step, asset in iter_assets(runbook, "group"):
            mismatch = _mismatch(provider, asset.directory)
            if mismatch:
                findings.append(
                    make_finding(
                        check=self.name,
                        dimension=self.dimension,
                        status="warn",
                        runbook_id=runbook.id,
                        target=asset.target,
                        message=mismatch,
                        asset=asset.id,
                        provider=provider,
                    )
                )
                continue
            result = ctx.directory.lookup(asset.target, asset.directory)
            extra = {
                key: result.evidence[key]
                for key in (
                    "authoritative",
                    "note",
                    "status",
                    "displayName",
                    "filter",
                    "scope",
                    "directory",
                )
                if key in result.evidence
            }
            findings.append(
                make_finding(
                    check=self.name,
                    dimension=self.dimension,
                    status=result.status,
                    runbook_id=runbook.id,
                    target=asset.target,
                    message=result.message,
                    asset=asset.id,
                    provider=result.provider,
                    **extra,
                )
            )
        return findings


def _mismatch(provider: str, directory: str | None) -> str | None:
    if provider == "ldap" and directory == "entra":
        return "group is marked entra, and the configured provider is LDAP; it was not queried"
    if provider == "graph" and directory == "active_directory":
        return (
            "group is marked active_directory, and the configured provider is "
            "Microsoft Graph; it was not queried"
        )
    return None
