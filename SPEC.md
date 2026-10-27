# SPEC: RunbookRehearsal

## Original task

Build v0.1 of **RunbookRehearsal**, an open-source tool that keeps incident and operations runbooks from silently rotting. Runbooks are written as YAML and regularly dry-run checked: are the hosts and URLs reachable, do the referenced accounts/groups/permissions still exist, do the scripts parse, are contacts and escalation numbers still valid, do referenced docs still exist. The output is a maturity report useful as evidence for NIS2 / ISO 27001 / BSI IT-Grundschutz (business continuity, incident handling). Follow ALL rules in uploads/gemeinsame_regeln.md. Before writing the README comparison, briefly research existing tools (e.g. Rundeck, PagerDuty runbooks, Backstage TechDocs, chaos engineering tools) and position this honestly: classic Windows/Linux ops runbooks, checked without executing anything destructive.

v0.1 scope (Python 3.11+ CLI `rehearse`):
- Runbook YAML schema with:
  - steps, preconditions, owners, contacts, referenced assets (hosts, URLs, AD/Entra groups, files, scripts), max age and review date
  - a JSON Schema plus a VS Code-friendly example
- Check plugins, all non-destructive:
  - DNS/TCP/HTTP reachability
  - script syntax check (PowerShell via pwsh `[System.Management.Automation.Language.Parser]` when available, bash -n, python compile)
  - file and link existence
  - review-date staleness
  - contact format
  - optional LDAP/Graph group existence behind explicit config, stubbed in demo
- Maturity score per runbook and overall, with an HTML/Markdown report and JSON for CI. A GitHub Action example lets teams run it on a schedule.
- `rehearse tabletop <runbook>`: an interactive terminal walk-through for tabletop exercises that records the answers and timings into a report.
- `rehearse demo` with fictional runbooks containing deliberate rot.
- pytest suite.

## Shared rules

See GEMEINSAME_REGELN.md (extracted from transcript).
