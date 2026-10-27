"""DNS, TCP, and HTTP checks. Offline fixtures never open a socket."""

from __future__ import annotations

from rehearse.checks.base import Check, CheckContext
from rehearse.models import Runbook, iter_assets, make_finding
from rehearse.network import describe_http, normalize_url


class ReachabilityCheck(Check):
    name = "reachability"
    dimension = "reachability"

    def run(self, runbook: Runbook, ctx: CheckContext) -> list:
        findings = []
        for _step, asset in iter_assets(runbook, "host"):
            findings.extend(self._host(runbook, asset, ctx))
        for _step, asset in iter_assets(runbook, "url"):
            findings.append(self._url(runbook, asset.target, asset.id, ctx))
        return findings

    def _host(self, runbook: Runbook, asset, ctx: CheckContext) -> list:
        dns = ctx.network.resolve(asset.target)
        findings = [
            make_finding(
                check="dns",
                dimension=self.dimension,
                status="pass" if dns.ok else "fail",
                runbook_id=runbook.id,
                target=asset.target,
                message=(
                    "DNS resolved to " + ", ".join(dns.addresses)
                    if dns.ok
                    else f"DNS did not resolve ({dns.error})"
                ),
                asset=asset.id,
                addresses=dns.addresses,
            )
        ]
        if asset.port is None:
            return findings
        if not dns.ok:
            findings.append(
                make_finding(
                    check="tcp",
                    dimension=self.dimension,
                    status="skip",
                    runbook_id=runbook.id,
                    target=f"{asset.target}:{asset.port}",
                    message="TCP was not checked because DNS failed",
                    asset=asset.id,
                )
            )
            return findings
        tcp = ctx.network.tcp(asset.target, asset.port)
        findings.append(
            make_finding(
                check="tcp",
                dimension=self.dimension,
                status="pass" if tcp.ok else "fail",
                runbook_id=runbook.id,
                target=f"{asset.target}:{asset.port}",
                message=(
                    f"TCP {asset.port} accepted a connection"
                    if tcp.ok
                    else f"TCP {asset.port} did not connect ({tcp.error})"
                ),
                asset=asset.id,
            )
        )
        return findings

    def _url(self, runbook: Runbook, url: str, asset_id: str, ctx: CheckContext):
        key = normalize_url(url)
        ctx.seen_urls.add(key)
        result = ctx.network.http(url)
        status = "pass" if result.ok else "fail"
        message = describe_http(result)
        return make_finding(
            check="http",
            dimension=self.dimension,
            status=status,
            runbook_id=runbook.id,
            target=url,
            message=message,
            asset=asset_id,
            httpStatus=result.status,
        )
