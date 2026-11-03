# Changelog

## Unreleased

- `rehearse check` now runs a `placeholders` finding that flags `(replace)`, `example.org`, and `555-010` values left in a runbook by `rehearse init`. It is a warning per contact or asset, so a copied skeleton that only got its title edited now shows up in the report instead of silently scoring as healthy.

## 0.2.0 — 2026-10-28

- `rehearse diff BEFORE AFTER` compares two `report.json` files: overall and per-runbook score deltas, band changes, new failures, fixed findings, other status changes, and added or removed runbooks. `--format text|markdown|json`. `--fail-on-regression` exits 1 on a new failure or a band drop. Freshness findings are matched per runbook, so a new review date counts as a fix and not as a new finding.
- `rehearse check --baseline report.json` prints the comparison, writes `diff.md` into `--output`, and `--fail-on-regression` gates on what got worse. Without `--baseline` that flag is a usage error (exit 2).
- `rehearse init ID` writes a runbook skeleton that passes `rehearse validate` (`--title`, `--service`, `--severity`, `--output -` for stdout, `--force`). Review interval 90/180 days for high and critical, 180/365 otherwise.
- `examples/github-actions/rehearse-pull-request.yml`: base-versus-PR comparison in the job summary, offline.
- ROADMAP.md with good first issues, issue forms, and a pull request template. CI runs Python 3.11 to 3.13 and a diff smoke test.

## 0.1.0 — 2026-10-21

First public slice.

- Runbook YAML schema (draft 2020-12) and a VS Code example.
- Non-destructive checks: DNS, TCP, and HTTP; Python, bash, and PowerShell syntax; local files and one level of links; review age; contact shape; optional LDAP, Microsoft Graph, or a stub group list.
- Maturity score per runbook and overall, with HTML, Markdown, and JSON reports.
- `rehearse tabletop` for a terminal walkthrough, including an answers file for non-interactive records.
- `rehearse demo` with fictional Harbor and Pine procedures and planted rot. Offline, no probes.
- pytest suite, a CI workflow, and an example scheduled GitHub Actions workflow.
