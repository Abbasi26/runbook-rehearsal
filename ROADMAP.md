# Roadmap

RunbookRehearsal checks written procedures. It does not run them, and it stays that way.

## 0.2 (this branch)

- `rehearse diff before.json after.json`: score deltas per runbook, new failures, fixed findings, band drops. Text, Markdown (for a pull-request comment or job summary), or JSON. `--fail-on-regression`.
- `rehearse check --baseline report.json --fail-on-regression`: compare in the same run, write `diff.md` next to the reports, and gate only on what got worse.
- `rehearse init <id>`: a runbook skeleton that passes `validate`, with commented asset examples.
- An example pull-request workflow that writes the diff to the job summary.

## Next

- A content root (`--root`) that refuses file and script paths outside a directory and does not follow symlinks out of it.
- Third-party check plugins via entry points.
- IPv6 host targets and authenticated HTTP (header from an environment variable, never from the YAML).
- A placeholder check: flag `example.org`, `(replace)`, and `555` numbers left over from `rehearse init`.
- A LDAP integration test against a local directory container in CI.
- Windows PowerShell 5.1 parser fallback when `pwsh` is missing.

## Good first issues

1. **Placeholder check**: a new completeness finding when a contact still contains `(replace)` or an `example.org` address. Look at `src/rehearse/checks/completeness.py` and add a test in `tests/test_checks.py`.
2. **`rehearse diff --only-failures`**: hide the score table and print only new failures.
3. **`init --from` an existing runbook**: copy contacts and owner from another file.
4. **Markdown diff in the HTML report**: show the `diff.md` content as a section when `--baseline` is set.
5. **Docs**: a German walkthrough of the pull-request workflow for teams that keep their Notfallhandbuch in Git.
6. **More script languages**: `node --check` for JavaScript files, behind the same "missing interpreter is a warning" rule.

Out of scope: executing steps, remediation, fault injection, telemetry.
