# Security

RunbookRehearsal 0.1 reads procedure files and, in live mode, probes the hosts and URLs those files name. It does not execute the procedure.

## Reports

A report contains the hostnames, URLs, names, email addresses, and phone numbers written in the runbooks, plus SHA-256 hashes of the files. Treat `report.html`, `report.md`, `report.json`, and tabletop records as internal. The tool writes them only to the directory you pass as `--output`. `rehearse demo` writes `rehearse-demo-out/` in the current directory.

## Probes

Live mode sends DNS queries, a TCP connection, and an HTTP `HEAD` (a one-byte `GET` when `HEAD` is refused). That is visible in remote logs. TLS is verified. Environment proxies are ignored unless `http.useEnvironmentProxy` is true. There is no rate limit in v0.1: a file that names thousands of hosts will probe all of them. Review the file before a live check.

Offline mode and `rehearse demo` do not open those connections. A target missing from the fixture fails closed.

## Credentials

Do not put passwords or tokens in `rehearse.yaml` or in a runbook. A URL with embedded credentials is rejected at load time.

- `REHEARSE_LDAP_PASSWORD` is read when `directory.provider` is `ldap`. The bind is read-only. The password is redacted from error text.
- `REHEARSE_GRAPH_TOKEN` is read when `directory.provider` is `graph`. v0.1 sends `GET` only. The token is redacted from error text.

The stub provider matches a list in the config. A stub hit is not evidence that a directory group exists. The report says so.

## Untrusted files

v0.1 follows symlinks and does not confine referenced paths to a root. A runbook can name any local file, and a script check will parse that file. It will not execute it. Run the tool as a user who is allowed to read those paths, on files you trust. YAML anchors, aliases, and Python tags are rejected. Runbook files larger than 1 MiB are rejected.

## Network position

There is no telemetry and no default proxy. The only outbound traffic in live mode is the probes above, plus an LDAP or Graph call when that provider is configured.

## Reporting a vulnerability

Open a private security advisory on the forge that hosts the repository when that forge supports one. Do not include live credentials, customer data, or a proof that touches a network you do not own. If a private channel is not available, open an issue that describes the impact without exploit detail.
