"""Command line for rehearse."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from rehearse import __version__
from rehearse.config import ConfigError, load_config
from rehearse.demo import load_demo_config
from rehearse.engine import check_paths
from rehearse.locate import schema_path
from rehearse.report import render_json, render_text, write_reports
from rehearse.runbook_load import LoadError, discover_runbooks, load_runbook
from rehearse.tabletop import (
    TabletopError,
    load_answers,
    render_tabletop_markdown,
    run_tabletop,
    write_tabletop,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="rehearse",
        description=(
            "Dry-run checks for incident and operations runbooks. "
            "Checks read references and do not execute the procedure."
        ),
    )
    parser.add_argument("--version", action="version", version=f"rehearse {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)

    check = sub.add_parser("check", help="check a runbook file or directory")
    check.add_argument("path", help="runbook file or directory")
    check.add_argument("--config", help="rehearse.yaml")
    check.add_argument("--offline", action="store_true", help="use fixtures and do not probe the network")
    check.add_argument("--live", action="store_true", help="probe DNS, TCP, and HTTP even if config says offline")
    check.add_argument("--output", help="directory for HTML, Markdown, and JSON reports")
    check.add_argument("--fail-under", type=float, default=None, help="exit 1 when the overall score is below this")
    check.add_argument("--strict", action="store_true", help="exit 1 when any finding fails")
    check.add_argument("--stdout", choices=("text", "json"), default="text")
    check.set_defaults(func=cmd_check)

    demo = sub.add_parser("demo", help="check the fictional Harbor and Pine fixtures offline")
    demo.add_argument("--output", default="rehearse-demo-out", help="report directory (default: rehearse-demo-out)")
    demo.set_defaults(func=cmd_demo)

    tabletop = sub.add_parser("tabletop", help="walk a runbook and record answers")
    tabletop.add_argument("path", help="runbook file")
    tabletop.add_argument("--answers", help="YAML answers for a non-interactive record")
    tabletop.add_argument("--participant", help="name stored on the record")
    tabletop.add_argument("--output", help="directory for the Markdown and JSON record")
    tabletop.set_defaults(func=cmd_tabletop)

    validate = sub.add_parser("validate", help="check runbook YAML against the schema")
    validate.add_argument("path", help="runbook file or directory")
    validate.set_defaults(func=cmd_validate)

    schema = sub.add_parser("schema", help="print the JSON Schema")
    schema.add_argument("--output", help="write the schema to this file instead of stdout")
    schema.set_defaults(func=cmd_schema)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return args.func(args)
    except (ConfigError, TabletopError, LoadError, NotADirectoryError, FileNotFoundError) as exc:
        print(str(exc), file=sys.stderr)
        return 2
    except BrokenPipeError:
        return 0


def cmd_check(args) -> int:
    if args.offline and args.live:
        print("pass only one of --offline and --live", file=sys.stderr)
        return 2
    try:
        config = load_config(Path(args.config) if args.config else None)
    except ConfigError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    if args.offline:
        config.mode = "offline"
    if args.live:
        config.mode = "live"
    try:
        paths = discover_runbooks(Path(args.path))
    except FileNotFoundError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    if not paths:
        print(f"no runbooks found in {args.path}", file=sys.stderr)
        return 2
    report = check_paths(paths, config)
    if args.stdout == "json":
        sys.stdout.write(render_json(report))
    else:
        sys.stdout.write(render_text(report))
    if args.output:
        written = write_reports(report, Path(args.output))
        for path in written.values():
            print(path)
    return _exit_code(report, args, config)


def cmd_demo(args) -> int:
    config, paths = load_demo_config()
    if not paths:
        print("demo fixtures are missing", file=sys.stderr)
        return 2
    report = check_paths(paths, config)
    sys.stdout.write(render_text(report))
    print("Deliberate rot in the Harbor and Pine fixtures is expected.")
    written = write_reports(report, Path(args.output))
    for path in written.values():
        print(path)
    return 2 if report.errors else 0


def cmd_tabletop(args) -> int:
    path = Path(args.path)
    if not path.is_file():
        print(f"runbook file not found: {path}", file=sys.stderr)
        return 2
    runbook = load_runbook(path)
    answers = load_answers(Path(args.answers)) if args.answers else None
    report = run_tabletop(
        runbook,
        answers=answers,
        participant=args.participant,
        input_fn=input if answers is None else None,
        output_fn=print,
        is_tty=sys.stdin.isatty(),
    )
    print(
        f"Tabletop {report.runbook_id}: participant {report.participant}, "
        f"{len(report.steps)} steps, walkthrough {report.discussion_seconds}s"
    )
    if args.output:
        written = write_tabletop(report, Path(args.output))
        for item in written.values():
            print(item)
    else:
        sys.stdout.write(render_tabletop_markdown(report))
    return 0


def cmd_validate(args) -> int:
    try:
        paths = discover_runbooks(Path(args.path))
    except FileNotFoundError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    if not paths:
        print(f"no runbooks found in {args.path}", file=sys.stderr)
        return 2
    failed = False
    for path in paths:
        try:
            load_runbook(path)
        except LoadError as exc:
            failed = True
            for message in exc.messages:
                print(f"{path}: {message}")
        else:
            print(f"ok {path}")
    return 2 if failed else 0


def cmd_schema(args) -> int:
    text = schema_path().read_text(encoding="utf-8")
    if not text.endswith("\n"):
        text += "\n"
    if args.output:
        Path(args.output).write_text(text, encoding="utf-8")
        print(args.output)
    else:
        sys.stdout.write(text)
    return 0


def _exit_code(report, args, config) -> int:
    if report.errors or report.overall.value is None:
        return 2
    threshold = args.fail_under if args.fail_under is not None else config.fail_under
    if threshold is not None and report.overall.value < threshold:
        return 1
    if args.strict and any(
        finding.status == "fail"
        for result in report.results
        for finding in result.findings
    ):
        return 1
    return 0
