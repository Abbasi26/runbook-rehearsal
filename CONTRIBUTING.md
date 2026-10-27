# Contributing

RunbookRehearsal is an MIT project. Copyright (c) 2026 Wasaf Abbasi.

## Ground rules

- Write code, comments, and documentation in English.
- Use fictional names, fictional `.example` domains, and documentation addresses such as `203.0.113.0/24`. Do not add real tenant names, real hostnames, real phone numbers, or secrets.
- Keep checks non-destructive. A change that writes to a remote system, restarts a service, or executes a referenced script needs an explicit switch and a preview, and it needs a reason that belongs in this tool. v0.1 has no such switch.
- Do not add telemetry.
- Describe behavior the code actually has. If a directory client is only covered with a stand-in, say so in the README.

## Develop

Python 3.11 or newer.

```bash
python -m pip install -e ".[dev]"
pytest
rehearse demo
```

Tests run offline. A live-network test may bind `127.0.0.1` only. Do not point tests at the public internet.

`schema/runbook.schema.json` and `src/rehearse/data/runbook.schema.json` are the same file. Update both and keep the parity test green. PowerShell files in the repo stay ASCII, or UTF-8 with a BOM if they need non-ASCII text.

## Pull requests

Explain the behavior change and point at the test that locks it. Update the README when a command, a score rule, or a permission changes. Add a line to `CHANGELOG.md` under the unreleased or current version.
