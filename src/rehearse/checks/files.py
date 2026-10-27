"""Local file existence and one-level link extraction."""

from __future__ import annotations

import re
from pathlib import Path

from rehearse.checks.base import Check, CheckContext
from rehearse.models import Runbook, iter_assets, make_finding
from rehearse.network import describe_http, normalize_url

_MD_LINK = re.compile(r"(?<!!)\[[^\]]*\]\(([^)]+)\)")
_HREF = re.compile(r"""href\s*=\s*["']([^"']+)["']""", re.IGNORECASE)
_MAX_SCAN = 1_048_576


class FileCheck(Check):
    name = "file-exists"
    dimension = "references"

    def run(self, runbook: Runbook, ctx: CheckContext) -> list:
        findings = []
        for _step, asset in iter_assets(runbook, "file"):
            findings.extend(self._file(runbook, asset.target, asset.id, ctx, scan_links=True))
        for precondition in runbook.preconditions:
            if precondition.evidence:
                findings.extend(
                    self._file(
                        runbook,
                        precondition.evidence,
                        precondition.id,
                        ctx,
                        scan_links=True,
                    )
                )
        return findings

    def _file(
        self,
        runbook: Runbook,
        target: str,
        asset_id: str,
        ctx: CheckContext,
        scan_links: bool,
    ) -> list:
        if target.startswith(("http://", "https://")):
            return [
                make_finding(
                    check="file-exists",
                    dimension=self.dimension,
                    status="fail",
                    runbook_id=runbook.id,
                    target=target,
                    message="evidence and file targets are local paths in v0.1; use a url asset for HTTP",
                    asset=asset_id,
                )
            ]
        path = resolve_reference(runbook.path, target)
        if not path.exists():
            return [
                make_finding(
                    check="file-exists",
                    dimension=self.dimension,
                    status="fail",
                    runbook_id=runbook.id,
                    target=target,
                    message="file not found",
                    asset=asset_id,
                    resolved=str(path),
                )
            ]
        if not path.is_file():
            return [
                make_finding(
                    check="file-exists",
                    dimension=self.dimension,
                    status="fail",
                    runbook_id=runbook.id,
                    target=target,
                    message="path exists but is not a file",
                    asset=asset_id,
                    resolved=str(path),
                )
            ]
        findings = [
            make_finding(
                check="file-exists",
                dimension=self.dimension,
                status="pass",
                runbook_id=runbook.id,
                target=target,
                message="file exists",
                asset=asset_id,
            )
        ]
        if scan_links:
            findings.extend(self._links(runbook, path, target, ctx))
        return findings

    def _links(self, runbook: Runbook, path: Path, target: str, ctx: CheckContext) -> list:
        if path.stat().st_size > _MAX_SCAN:
            return [
                make_finding(
                    check="link-exists",
                    dimension=self.dimension,
                    status="warn",
                    runbook_id=runbook.id,
                    target=target,
                    message="file is larger than 1 MiB; links inside it were not scanned",
                )
            ]
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            return [
                make_finding(
                    check="link-exists",
                    dimension=self.dimension,
                    status="warn",
                    runbook_id=runbook.id,
                    target=target,
                    message="file is not UTF-8; links inside it were not scanned",
                )
            ]
        findings = []
        for raw in _extract_links(text):
            link = _clean_link(raw)
            if not link or link.startswith("#"):
                findings.append(
                    make_finding(
                        check="link-exists",
                        dimension=self.dimension,
                        status="skip",
                        runbook_id=runbook.id,
                        target=link or raw,
                        message="in-page anchor is not fetched",
                        source=target,
                    )
                )
                continue
            if link.startswith("mailto:"):
                findings.append(
                    make_finding(
                        check="link-exists",
                        dimension=self.dimension,
                        status="skip",
                        runbook_id=runbook.id,
                        target=link,
                        message="mailto links are not fetched",
                        source=target,
                    )
                )
                continue
            if link.startswith(("javascript:", "data:")):
                findings.append(
                    make_finding(
                        check="link-exists",
                        dimension=self.dimension,
                        status="fail",
                        runbook_id=runbook.id,
                        target=link,
                        message="link scheme is not checked",
                        source=target,
                    )
                )
                continue
            if link.startswith(("http://", "https://")):
                key = normalize_url(link)
                if key in ctx.seen_urls:
                    findings.append(
                        make_finding(
                            check="link-exists",
                            dimension=self.dimension,
                            status="skip",
                            runbook_id=runbook.id,
                            target=link,
                            message="URL was already checked as an asset",
                            source=target,
                        )
                    )
                    continue
                ctx.seen_urls.add(key)
                result = ctx.network.http(link)
                findings.append(
                    make_finding(
                        check="http",
                        dimension="reachability",
                        status="pass" if result.ok else "fail",
                        runbook_id=runbook.id,
                        target=link,
                        message=describe_http(result),
                        source=target,
                        httpStatus=result.status,
                    )
                )
                continue
            destination = (path.parent / link.split("#", 1)[0]).resolve()
            if destination.is_file():
                status, message = "pass", "linked file exists"
            else:
                status, message = "fail", "linked file not found"
            findings.append(
                make_finding(
                    check="link-exists",
                    dimension=self.dimension,
                    status=status,
                    runbook_id=runbook.id,
                    target=link,
                    message=message,
                    source=target,
                )
            )
        return findings


def resolve_reference(runbook_path: Path, target: str) -> Path:
    raw = Path(target)
    if raw.is_absolute():
        return raw
    return (runbook_path.parent / raw).resolve()


def _extract_links(text: str) -> list[str]:
    return _MD_LINK.findall(text) + _HREF.findall(text)


def _clean_link(raw: str) -> str:
    value = raw.strip()
    if value.startswith("<") and ">" in value:
        value = value[1 : value.index(">")]
    if " " in value:
        value = value.split()[0]
    return value.strip()
