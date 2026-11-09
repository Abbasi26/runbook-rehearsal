"""Check behaviour that does not depend on the demo fixtures."""

import json
from datetime import date
from pathlib import Path

from rehearse.checks.base import CheckContext
from rehearse.checks.completeness import CompletenessCheck
from rehearse.checks.contacts import ContactCheck, normalize_phone, valid_email
from rehearse.checks.files import FileCheck
from rehearse.checks.scripts import ScriptCheck
from rehearse.checks.freshness import FreshnessCheck
from rehearse.checks.groups import GroupCheck
from rehearse.checks.reachability import ReachabilityCheck
from rehearse.cli import main
from rehearse.config import Config, ConfigError, FixtureBook, load_config
from rehearse.directory import NoneDirectory, StubDirectory, build_directory
from rehearse.engine import Clock
from rehearse.models import Asset, Precondition, Step
from tests.conftest import make_runbook

TODAY = date(2026, 10, 21)


def _ctx(tmp_path: Path, **config_kwargs) -> CheckContext:
    config = Config(mode="offline", **config_kwargs)
    return CheckContext(
        config=config,
        clock=Clock(TODAY),
        network=None,
        directory=build_directory(config),
    )


def test_phone_and_email_shapes():
    assert normalize_phone("+1-555-014-2281") == "+15550142281"
    assert normalize_phone("+1 (555) 014-2281") == "+15550142281"
    assert normalize_phone("12345") is None
    assert normalize_phone("555-0100") is None
    assert valid_email("ops@harborpine.example")
    assert not valid_email("pager-desk")


def test_freshness_boundaries(tmp_path: Path):
    check = FreshnessCheck()
    fresh = make_runbook(tmp_path / "fresh.yaml", review=_review(date(2026, 9, 1), 90, 180))
    assert check.run(fresh, _ctx(tmp_path))[0].status == "pass"

    due = make_runbook(
        tmp_path / "due.yaml",
        review=_review(date(2026, 8, 1), 90, 180),
    )
    due_finding = check.run(due, _ctx(tmp_path))[0]
    assert due_finding.status == "warn"
    assert "due in" in due_finding.message

    overdue = make_runbook(
        tmp_path / "overdue.yaml",
        review=_review(date(2026, 6, 1), 90, 365),
    )
    overdue_finding = check.run(overdue, _ctx(tmp_path))[0]
    assert overdue_finding.status == "fail"
    assert "overdue" in overdue_finding.message

    ancient = make_runbook(
        tmp_path / "ancient.yaml",
        review=_review(date(2025, 6, 1), 90, 180),
    )
    ancient_finding = check.run(ancient, _ctx(tmp_path))[0]
    assert ancient_finding.status == "fail"
    assert "maximum age" in ancient_finding.message

    future = make_runbook(
        tmp_path / "future.yaml",
        review=_review(date(2026, 12, 1), 90, 180),
    )
    assert check.run(future, _ctx(tmp_path))[0].status == "fail"


def test_contact_rot_and_escalation(tmp_path: Path):
    from rehearse.models import Contact

    book = make_runbook(
        tmp_path / "contacts.yaml",
        contacts=[
            Contact("Priya Nandakumar", "Commander", "priya.nandakumar@harborpine.example", "+1-555-014-2281", 1),
            Contact("Legacy pager desk", "After hours", "pager-desk", "12345", 2),
        ],
    )
    findings = ContactCheck().run(book, _ctx(tmp_path))
    failed = [item for item in findings if item.status == "fail"]
    assert any(item.target == "Legacy pager desk" and "email" in item.message for item in failed)
    assert any(item.target == "Legacy pager desk" and "phone" in item.message for item in failed)
    assert any(item.check == "escalation" and item.status == "pass" for item in findings)

    bare = make_runbook(tmp_path / "bare.yaml", contacts=[
        Contact("Sam", "Note taker", "sam.ortega@harborpine.example", None, None)
    ])
    escalation = [item for item in ContactCheck().run(bare, _ctx(tmp_path)) if item.check == "escalation"]
    assert escalation[0].status == "fail"


def test_missing_file_and_broken_link(tmp_path: Path):
    docs = tmp_path / "docs"
    docs.mkdir()
    note = docs / "note.md"
    note.write_text(
        "See [gone](./gone.md) and [wiki](https://wiki.harborpine.example/restore).\n",
        encoding="utf-8",
    )
    book = make_runbook(
        tmp_path / "book.yaml",
        steps=[
            _step_with_assets(
                [
                    Asset("note", "file", "docs/note.md"),
                    Asset("missing", "file", "docs/missing.md"),
                ]
            )
        ],
    )
    network = _FixtureNet({"https://wiki.harborpine.example/restore": 404})
    ctx = _ctx(tmp_path)
    ctx.network = network
    findings = FileCheck().run(book, ctx)
    by_target = {item.target: item for item in findings}
    assert by_target["docs/note.md"].status == "pass"
    assert by_target["docs/missing.md"].status == "fail"
    assert by_target["./gone.md"].status == "fail"
    assert by_target["https://wiki.harborpine.example/restore"].status == "fail"
    assert by_target["https://wiki.harborpine.example/restore"].dimension == "reachability"


def test_content_root_confines_files_and_follows_safe_symlinks(tmp_path: Path):
    root = tmp_path / "content"
    runbooks = root / "runbooks"
    assets = root / "assets"
    runbooks.mkdir(parents=True)
    assets.mkdir()
    inside = assets / "inside.txt"
    inside.write_text("inside\n", encoding="utf-8")
    outside = tmp_path / "outside.txt"
    outside.write_text("outside\n", encoding="utf-8")
    (assets / "inside-link.txt").symlink_to(inside)
    (assets / "outside-link.txt").symlink_to(outside)
    book = make_runbook(
        runbooks / "book.yaml",
        steps=[
            _step_with_assets(
                [
                    Asset("inside", "file", "../assets/inside.txt"),
                    Asset("parent", "file", "../../outside.txt"),
                    Asset("absolute", "file", str(outside)),
                    Asset("outside-link", "file", "../assets/outside-link.txt"),
                    Asset("inside-link", "file", "../assets/inside-link.txt"),
                ]
            )
        ],
    )

    findings = FileCheck().run(book, _ctx(tmp_path, root=root.resolve()))
    by_target = {item.target: item for item in findings}
    assert by_target["../assets/inside.txt"].status == "pass"
    assert by_target["../assets/inside-link.txt"].status == "pass"
    for target in ("../../outside.txt", str(outside), "../assets/outside-link.txt"):
        assert by_target[target].status == "fail"
        assert by_target[target].evidence["resolved"] == str(outside.resolve())


def test_content_root_confines_links_before_reading_destination(tmp_path: Path):
    root = tmp_path / "content"
    root.mkdir()
    outside = tmp_path / "outside.md"
    outside.write_text("outside\n", encoding="utf-8")
    note = root / "note.md"
    note.write_text(
        '[outside](../outside.md) <a href="../outside.md">outside</a>\n',
        encoding="utf-8",
    )
    book = make_runbook(
        root / "book.yaml",
        preconditions=[Precondition("proof", "Proof is present.", "../outside.md")],
        steps=[_step_with_assets([Asset("note", "file", "note.md")])],
    )

    findings = FileCheck().run(book, _ctx(tmp_path, root=root.resolve()))
    blocked = [item for item in findings if item.status == "fail"]
    assert len([item for item in blocked if item.check == "link-exists"]) == 2
    assert any(item.check == "file-exists" and item.target == "../outside.md" for item in blocked)
    assert all(item.evidence["resolved"] == str(outside.resolve()) for item in blocked)


def test_content_root_blocks_script_before_syntax_check(tmp_path: Path, monkeypatch):
    root = tmp_path / "content"
    root.mkdir()
    outside = tmp_path / "outside.py"
    outside.write_text("raise AssertionError('must not be read')\n", encoding="utf-8")
    link = root / "script.py"
    link.symlink_to(outside)
    book = make_runbook(root / "book.yaml")
    book.steps[0].assets.append(Asset("script", "script", "script.py", language="python"))

    def should_not_run(*_args, **_kwargs):
        raise AssertionError("syntax check should not run outside the content root")

    monkeypatch.setattr("rehearse.checks.scripts.check_script", should_not_run)
    finding = ScriptCheck().run(book, _ctx(tmp_path, root=root.resolve()))[0]
    assert finding.status == "fail"
    assert finding.evidence["resolved"] == str(outside.resolve())


def test_config_root_is_relative_to_config_and_canonical(tmp_path: Path):
    real = tmp_path / "real"
    real.mkdir()
    alias = tmp_path / "alias"
    alias.symlink_to(real, target_is_directory=True)
    config_path = tmp_path / "rehearse.yaml"
    config_path.write_text("mode: offline\nroot: alias\n", encoding="utf-8")
    assert load_config(config_path).root == real.resolve()

    config_path.write_text("root: missing\n", encoding="utf-8")
    try:
        load_config(config_path)
    except ConfigError as exc:
        assert "root is not a directory" in str(exc)
    else:
        raise AssertionError("missing content root was accepted")


def test_cli_root_uses_working_directory_and_overrides_config(tmp_path: Path, monkeypatch, capsys):
    config_root = tmp_path / "configured"
    config_root.mkdir()
    config_path = tmp_path / "rehearse.yaml"
    config_path.write_text("mode: offline\nroot: configured\n", encoding="utf-8")
    demo = Path(__file__).resolve().parents[1] / "examples" / "demo" / "runbooks"
    monkeypatch.chdir(tmp_path)

    assert main(["check", str(demo), "--config", str(config_path), "--root", ".", "--stdout", "json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["contentRoot"] == str(tmp_path.resolve())


def test_url_asset_is_not_scored_twice(tmp_path: Path):
    docs = tmp_path / "docs"
    docs.mkdir()
    (docs / "note.md").write_text(
        "Already listed: [status](https://status.harborpine.example/logs).\n",
        encoding="utf-8",
    )
    url = "https://status.harborpine.example/logs"
    book = make_runbook(
        tmp_path / "book.yaml",
        steps=[
            _step_with_assets(
                [
                    Asset("status", "url", url),
                    Asset("note", "file", "docs/note.md"),
                ]
            )
        ],
    )
    ctx = _ctx(tmp_path)
    ctx.network = _FixtureNet({url: 200})
    ReachabilityCheck().run(book, ctx)
    findings = FileCheck().run(book, ctx)
    http = [item for item in findings if item.target == url]
    assert len(http) == 1
    assert http[0].status == "skip"


def test_group_stub_none_and_mismatch(tmp_path: Path):
    book = make_runbook(
        tmp_path / "group.yaml",
        steps=[
            _step_with_assets(
                [
                    Asset(
                        "ops",
                        "group",
                        "CN=Linux-Operators,OU=Groups,DC=harborpine,DC=example",
                        directory="active_directory",
                    )
                ]
            )
        ],
    )
    stub_ctx = _ctx(
        tmp_path,
        directory_provider="stub",
        stub_groups=["CN=Linux-Operators,OU=Groups,DC=harborpine,DC=example"],
    )
    stub_ctx.directory = StubDirectory(stub_ctx.config.stub_groups)
    assert GroupCheck().run(book, stub_ctx)[0].status == "pass"

    missing = make_runbook(
        tmp_path / "missing-group.yaml",
        steps=[
            _step_with_assets(
                [Asset("old", "group", "CN=Finance-Share-Admins,OU=Groups,DC=harborpine,DC=example")]
            )
        ],
    )
    assert GroupCheck().run(missing, stub_ctx)[0].status == "fail"

    none_ctx = _ctx(tmp_path)
    none_ctx.directory = NoneDirectory()
    assert GroupCheck().run(book, none_ctx)[0].status == "warn"

    class Boom:
        def lookup(self, target, directory):
            raise AssertionError("lookup should not run on a provider mismatch")

    graph_ctx = _ctx(tmp_path, directory_provider="graph")
    graph_ctx.directory = Boom()
    warned = GroupCheck().run(book, graph_ctx)[0]
    assert warned.status == "warn"
    assert "Graph" in warned.message


def test_completeness_requires_preconditions_when_severe(tmp_path: Path):
    book = make_runbook(tmp_path / "empty.yaml", preconditions=[], severity="critical")
    findings = CompletenessCheck().run(book, _ctx(tmp_path))
    assert any(item.status == "fail" for item in findings)
    low = make_runbook(tmp_path / "low.yaml", preconditions=[], severity="low")
    low_findings = CompletenessCheck().run(low, _ctx(tmp_path))
    assert any(item.status == "warn" and "precondition" in item.message for item in low_findings)


def test_offline_host_and_url_fixtures(tmp_path: Path):
    from rehearse.network import FixtureNetwork

    book = make_runbook(
        tmp_path / "net.yaml",
        steps=[
            _step_with_assets(
                [
                    Asset("fs01", "host", "fs01.ops.harborpine.example", port=445),
                    Asset("page", "url", "https://status.harborpine.example/finance"),
                ]
            )
        ],
    )
    network = FixtureNetwork(
        FixtureBook(
            hosts={
                "fs01.ops.harborpine.example": {
                    "addresses": ["203.0.113.10"],
                    "ports": {"445": "closed"},
                }
            },
            urls={"https://status.harborpine.example/finance": {"status": 404, "reason": "not found"}},
        )
    )
    ctx = _ctx(tmp_path)
    ctx.network = network
    findings = ReachabilityCheck().run(book, ctx)
    by_check = {item.check: item for item in findings}
    assert by_check["dns"].status == "pass"
    assert by_check["tcp"].status == "fail"
    assert by_check["http"].status == "fail"
    unknown = network.resolve("missing.harborpine.example")
    assert unknown.ok is False
    assert "offline fixture" in (unknown.error or "")


class _FixtureNet:
    def __init__(self, urls: dict[str, int]):
        self.urls = urls

    def http(self, url: str):
        from rehearse.network import HttpResult

        status = self.urls[url]
        if 200 <= status < 400:
            return HttpResult(True, status, None, url)
        return HttpResult(False, status, f"HTTP {status}", url)


def _review(reviewed: date, interval: int, max_age: int):
    from rehearse.models import Review

    return Review(reviewed, interval, max_age)


def _step_with_assets(assets: list[Asset]) -> Step:
    return Step(
        id="look",
        title="Look first",
        description="Read the service state before changing anything.",
        expected_outcome="The operator records the state they saw.",
        owner="Operator",
        assets=assets,
    )


def test_phone_requires_ascii_digits():
    for digit in ("\u0662", "\uff12"):
        assert normalize_phone("+1" + digit * 7) is None

    assert normalize_phone("+12345678") == "+12345678"
    assert normalize_phone("+123456789012345") == "+123456789012345"
    assert normalize_phone(" +1 (555) 014-2281 ") == "+15550142281"

    for value in ("+1234567", "+1234567890123456", "+02345678"):
        assert normalize_phone(value) is None


def test_escalation_eligibility_uses_each_contacts_phone(tmp_path: Path):
    from rehearse.models import Contact

    valid_email = "ops@harborpine.example"
    valid_phone = "+1-555-014-2281"
    cases = [
        (valid_email, valid_phone, 1, "pass"),
        (valid_email, "12345", 1, "fail"),
        (valid_email, None, 1, "fail"),
        ("pager-desk", valid_phone, 1, "fail"),
        (valid_email, valid_phone, None, "fail"),
    ]
    for email, phone, order, expected in cases:
        book = make_runbook(
            tmp_path / "contacts.yaml",
            contacts=[
                Contact("Observer", "Observer", valid_email, valid_phone, None),
                Contact("On call", "Commander", email, phone, order),
            ],
        )
        findings = ContactCheck().run(book, _ctx(tmp_path))
        escalation = [item for item in findings if item.check == "escalation"]
        assert len(escalation) == 1
        assert escalation[0].status == expected
