"""Score math, live-mode clock, reports, and a local HTTP probe."""

import json
import socket
import threading
from datetime import date
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from rehearse.checks.base import Check
from rehearse.config import Config
from rehearse.engine import Clock, check_paths
from rehearse.models import make_finding
from rehearse.report import render_html, render_json, render_markdown, write_reports
from rehearse.runbook_load import discover_runbooks
from rehearse.scoring import WEIGHTS, score_findings


def _finding(dimension: str, status: str, check: str = "sample"):
    return make_finding(
        check=check,
        dimension=dimension,
        status=status,
        runbook_id="sample-runbook",
        target=dimension,
        message=status,
    )


def test_score_weights_and_redistribution():
    assert sum(WEIGHTS.values()) == 100
    scored = score_findings(
        [
            _finding("freshness", "pass"),
            _finding("contacts", "pass"),
            _finding("contacts", "fail"),
            _finding("reachability", "pass"),
            _finding("reachability", "pass"),
            _finding("references", "fail"),
            _finding("directory", "warn"),
            _finding("completeness", "pass"),
            _finding("reachability", "skip"),
        ]
    )
    assert scored.value == 67.5
    assert scored.band == "drifting"
    assert scored.counts["skip"] == 1

    only = score_findings([_finding("freshness", "warn")])
    assert only.value == 50.0
    assert only.dimensions[0].effective_weight == 100.0

    assert score_findings([_finding("freshness", "skip")]).value is None


def test_live_mode_ignores_pinned_clock(tmp_path: Path, monkeypatch):
    book_path = tmp_path / "old.yaml"
    # A review that is fresh only if the clock is pinned to January 2020.
    text = Path(__file__).resolve().parents[1].joinpath(
        "examples/demo/runbooks/linux-disk-incident.yaml"
    ).read_text(encoding="utf-8")
    text = text.replace("lastReviewed: \"2026-09-01\"", "lastReviewed: \"2020-01-01\"", 1)
    text = text.replace("id: linux-disk-incident", "id: clock-pin-check", 1)
    # Drop assets so the live check does not probe the network.
    book_path.write_text(_strip_assets(text), encoding="utf-8")

    def boom(*_args, **_kwargs):
        raise AssertionError("live check probed the network")

    monkeypatch.setattr(socket, "getaddrinfo", boom)
    monkeypatch.setattr(socket, "create_connection", boom)

    pinned = Config(mode="offline", clock_today=date(2020, 1, 2))
    offline = check_paths([book_path], pinned)
    assert offline.results[0].score.dimensions
    freshness = next(item for item in offline.results[0].findings if item.check == "freshness")
    assert freshness.status == "pass"
    assert offline.clock_pinned is True

    live = Config(mode="live", clock_today=date(2020, 1, 2))
    report = check_paths([book_path], live, clock=Clock(date(2026, 10, 21)))
    freshness = next(item for item in report.results[0].findings if item.check == "freshness")
    assert freshness.status == "fail"
    assert report.clock_pinned is False
    assert report.clock_note and "ignored" in report.clock_note
    assert report.probes_sent is True


def test_check_crash_becomes_a_finding(tmp_path: Path):
    path = tmp_path / "one.yaml"
    source = Path(__file__).resolve().parents[1].joinpath(
        "examples/demo/runbooks/linux-disk-incident.yaml"
    ).read_text(encoding="utf-8")
    path.write_text(_strip_assets(source), encoding="utf-8")

    class Boom(Check):
        name = "boom"
        dimension = "completeness"

        def run(self, runbook, ctx):
            raise RuntimeError("nope")

    report = check_paths([path], Config(mode="offline"), checks=[Boom()])
    assert report.results[0].findings[0].status == "fail"
    assert "RuntimeError" in report.results[0].findings[0].message


def test_report_files_include_disclaimer_and_weights(tmp_path: Path):
    source = Path(__file__).resolve().parents[1] / "examples" / "demo" / "runbooks" / "linux-disk-incident.yaml"
    report = check_paths(discover_runbooks(source), Config(mode="offline", clock_today=date(2026, 10, 21)))
    written = write_reports(report, tmp_path / "out")
    html = written["html"].read_text(encoding="utf-8")
    markdown = written["md"].read_text(encoding="utf-8")
    payload = json.loads(written["json"].read_text(encoding="utf-8"))
    assert "not a certification" not in html.lower() or "certification" in html.lower()
    assert "certification" in payload["disclaimer"].lower()
    assert payload["weights"] == WEIGHTS
    assert payload["probesSent"] is False
    assert "A.5.24" in markdown
    assert "DER.4" in html
    assert "Article 21" in html
    assert render_html(report).startswith("<!DOCTYPE html>")
    assert "linux-disk-incident" in render_markdown(report)
    assert render_json(report).strip().endswith("}")


def test_live_http_and_tcp_ignore_fixtures():
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(204)
            self.end_headers()

        def do_HEAD(self):
            self.send_response(204)
            self.end_headers()

        def log_message(self, fmt, *args):
            return

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    port = server.server_address[1]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    closed = socket.socket()
    closed.bind(("127.0.0.1", 0))
    closed_port = closed.getsockname()[1]
    closed.close()
    try:
        from rehearse.network import LiveNetwork

        config = Config(
            mode="live",
            http_timeout=2,
            tcp_timeout=2,
            fixtures=__import__("rehearse.config", fromlist=["FixtureBook"]).FixtureBook(
                hosts={"127.0.0.1": {"addresses": [], "ports": {str(port): "closed"}}},
                urls={f"http://127.0.0.1:{port}/health": {"status": 404}},
            ),
        )
        network = LiveNetwork(config)
        dns = network.resolve("localhost")
        assert dns.ok
        http = network.http(f"http://127.0.0.1:{port}/health")
        assert http.ok and http.status == 204
        assert network.tcp("127.0.0.1", port).ok
        assert network.tcp("127.0.0.1", closed_port).ok is False
        rejected = network.http("https://user:secret@127.0.0.1/hidden")
        assert rejected.ok is False
        assert "credential" in (rejected.error or "")
    finally:
        server.shutdown()


def _strip_assets(text: str) -> str:
    """Remove asset blocks so a live check has nothing to probe."""
    lines = []
    skipping = False
    for line in text.splitlines():
        if line.startswith("    assets:"):
            lines.append("    assets: []")
            skipping = True
            continue
        if skipping:
            if line.startswith("      ") or line.strip() == "":
                continue
            skipping = False
        lines.append(line)
    return "\n".join(lines) + "\n"
