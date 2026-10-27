"""Load rehearse.yaml. Unknown keys are errors so a typo cannot disable a check."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

import yaml

from rehearse.runbook_load import RunbookLoader


class ConfigError(Exception):
    pass


@dataclass
class LdapSettings:
    host: str
    port: int = 389
    use_ssl: bool = False
    bind_dn: str = ""
    base_dn: str = ""
    timeout_seconds: float = 5.0


@dataclass
class GraphSettings:
    endpoint: str = "https://graph.microsoft.com/v1.0"
    timeout_seconds: float = 10.0


@dataclass
class FixtureBook:
    hosts: dict = field(default_factory=dict)
    urls: dict = field(default_factory=dict)


@dataclass
class Config:
    mode: str = "live"
    fail_under: float | None = None
    due_soon_days: int = 14
    dns_timeout: float = 3.0
    tcp_timeout: float = 3.0
    http_timeout: float = 5.0
    use_environment_proxy: bool = False
    directory_provider: str = "none"
    stub_groups: list[str] = field(default_factory=list)
    ldap: LdapSettings | None = None
    graph: GraphSettings | None = None
    fixtures: FixtureBook = field(default_factory=FixtureBook)
    clock_today: date | None = None
    source: str | None = None


_TOP_KEYS = {
    "mode",
    "failUnder",
    "dueSoonDays",
    "clock",
    "timeouts",
    "http",
    "directory",
    "offline",
}


def default_config() -> Config:
    return Config()


def load_config(path: Path | None) -> Config:
    if path is None:
        return default_config()
    path = path.expanduser().resolve()
    if not path.is_file():
        raise ConfigError(f"config file not found: {path}")
    try:
        document = yaml.load(path.read_text(encoding="utf-8"), Loader=RunbookLoader)
    except yaml.YAMLError as exc:
        raise ConfigError(f"{path}: {exc}") from exc
    if document is None:
        document = {}
    if not isinstance(document, dict):
        raise ConfigError(f"{path}: config must be a mapping")
    config = _parse_config(document, str(path))
    config.source = str(path)
    return config


def _parse_config(document: dict, origin: str) -> Config:
    unknown = sorted(set(document) - _TOP_KEYS)
    if unknown:
        raise ConfigError(f"{origin}: unknown config keys: {', '.join(unknown)}")

    mode = document.get("mode", "live")
    if mode not in {"live", "offline"}:
        raise ConfigError(f"{origin}: mode must be live or offline")

    config = Config(mode=mode)
    if "failUnder" in document:
        config.fail_under = _number(document["failUnder"], "failUnder", 0, 100, origin)
    if "dueSoonDays" in document:
        config.due_soon_days = int(_number(document["dueSoonDays"], "dueSoonDays", 0, 365, origin))

    clock = document.get("clock") or {}
    if clock:
        _reject_unknown(clock, {"today"}, "clock", origin)
        today = clock.get("today")
        if today is not None:
            if isinstance(today, date):
                config.clock_today = today
            else:
                try:
                    config.clock_today = date.fromisoformat(str(today))
                except ValueError as exc:
                    raise ConfigError(f"{origin}: clock.today must be YYYY-MM-DD") from exc

    timeouts = document.get("timeouts") or {}
    if timeouts:
        _reject_unknown(timeouts, {"dnsSeconds", "tcpSeconds", "httpSeconds"}, "timeouts", origin)
        if "dnsSeconds" in timeouts:
            config.dns_timeout = _number(timeouts["dnsSeconds"], "timeouts.dnsSeconds", 0.1, 60, origin)
        if "tcpSeconds" in timeouts:
            config.tcp_timeout = _number(timeouts["tcpSeconds"], "timeouts.tcpSeconds", 0.1, 60, origin)
        if "httpSeconds" in timeouts:
            config.http_timeout = _number(timeouts["httpSeconds"], "timeouts.httpSeconds", 0.1, 120, origin)

    http = document.get("http") or {}
    if http:
        _reject_unknown(http, {"useEnvironmentProxy"}, "http", origin)
        proxy = http.get("useEnvironmentProxy", False)
        if not isinstance(proxy, bool):
            raise ConfigError(f"{origin}: http.useEnvironmentProxy must be true or false")
        config.use_environment_proxy = proxy

    directory = document.get("directory") or {}
    if directory:
        _apply_directory(config, directory, origin)

    offline = document.get("offline") or {}
    if offline:
        _apply_offline(config, offline, origin)
    return config


def _apply_directory(config: Config, directory: dict, origin: str) -> None:
    _reject_unknown(directory, {"provider", "stub", "ldap", "graph"}, "directory", origin)
    provider = directory.get("provider", "none")
    if provider not in {"none", "stub", "ldap", "graph"}:
        raise ConfigError(f"{origin}: directory.provider must be none, stub, ldap, or graph")
    config.directory_provider = provider

    stub = directory.get("stub") or {}
    if stub:
        _reject_unknown(stub, {"groups"}, "directory.stub", origin)
        groups = stub.get("groups") or []
        if not isinstance(groups, list) or not all(isinstance(item, str) and item.strip() for item in groups):
            raise ConfigError(f"{origin}: directory.stub.groups must be a list of strings")
        config.stub_groups = [item.strip() for item in groups]

    ldap = directory.get("ldap") or {}
    if ldap:
        _reject_unknown(
            ldap,
            {"host", "port", "useSsl", "bindDn", "baseDn", "timeoutSeconds"},
            "directory.ldap",
            origin,
        )
        host = ldap.get("host")
        bind_dn = ldap.get("bindDn")
        base_dn = ldap.get("baseDn")
        if provider == "ldap" and (not host or not bind_dn or not base_dn):
            raise ConfigError(f"{origin}: directory.ldap needs host, bindDn, and baseDn")
        config.ldap = LdapSettings(
            host=str(host or ""),
            port=int(_number(ldap.get("port", 389), "directory.ldap.port", 1, 65535, origin)),
            use_ssl=bool(ldap.get("useSsl", False)),
            bind_dn=str(bind_dn or ""),
            base_dn=str(base_dn or ""),
            timeout_seconds=_number(
                ldap.get("timeoutSeconds", 5),
                "directory.ldap.timeoutSeconds",
                0.1,
                120,
                origin,
            ),
        )
        if not isinstance(ldap.get("useSsl", False), bool):
            raise ConfigError(f"{origin}: directory.ldap.useSsl must be true or false")

    graph = directory.get("graph") or {}
    if graph:
        _reject_unknown(graph, {"endpoint", "timeoutSeconds"}, "directory.graph", origin)
        endpoint = str(graph.get("endpoint", "https://graph.microsoft.com/v1.0"))
        if not endpoint.startswith("https://"):
            raise ConfigError(f"{origin}: directory.graph.endpoint must start with https://")
        config.graph = GraphSettings(
            endpoint=endpoint.rstrip("/"),
            timeout_seconds=_number(
                graph.get("timeoutSeconds", 10),
                "directory.graph.timeoutSeconds",
                0.1,
                120,
                origin,
            ),
        )

    if provider == "ldap" and config.ldap is None:
        raise ConfigError(f"{origin}: directory.provider ldap requires a directory.ldap block")
    if provider == "graph" and config.graph is None:
        config.graph = GraphSettings()


def _apply_offline(config: Config, offline: dict, origin: str) -> None:
    _reject_unknown(offline, {"hosts", "urls"}, "offline", origin)
    hosts = offline.get("hosts") or {}
    urls = offline.get("urls") or {}
    if not isinstance(hosts, dict) or not isinstance(urls, dict):
        raise ConfigError(f"{origin}: offline.hosts and offline.urls must be mappings")
    normalized_hosts = {}
    for host, spec in hosts.items():
        if not isinstance(host, str) or not isinstance(spec, dict):
            raise ConfigError(f"{origin}: each offline host needs a mapping value")
        _reject_unknown(spec, {"addresses", "ports", "error"}, f"offline.hosts.{host}", origin)
        addresses = spec.get("addresses", [])
        if not isinstance(addresses, list) or not all(isinstance(item, str) for item in addresses):
            raise ConfigError(f"{origin}: offline host {host} addresses must be a list of strings")
        ports = spec.get("ports") or {}
        if not isinstance(ports, dict):
            raise ConfigError(f"{origin}: offline host {host} ports must be a mapping")
        clean_ports = {}
        for port, state in ports.items():
            state_name = str(state)
            if state_name not in {"open", "closed"}:
                raise ConfigError(f"{origin}: port state for {host}:{port} must be open or closed")
            clean_ports[str(port)] = state_name
        normalized_hosts[host.casefold()] = {
            "addresses": list(addresses),
            "ports": clean_ports,
            "error": spec.get("error"),
        }
    normalized_urls = {}
    for url, spec in urls.items():
        if not isinstance(url, str) or not isinstance(spec, dict):
            raise ConfigError(f"{origin}: each offline url needs a mapping value")
        _reject_unknown(spec, {"status", "reason"}, f"offline.urls.{url}", origin)
        status = spec.get("status")
        if not isinstance(status, int) or not 100 <= status <= 599:
            raise ConfigError(f"{origin}: offline url {url} status must be an integer 100-599")
        normalized_urls[_url_key(url)] = {"status": status, "reason": spec.get("reason")}
    config.fixtures = FixtureBook(hosts=normalized_hosts, urls=normalized_urls)


def _url_key(url: str) -> str:
    if len(url) > len("https://a/") and url.endswith("/"):
        return url[:-1]
    return url


def _reject_unknown(block: dict, allowed: set[str], label: str, origin: str) -> None:
    unknown = sorted(set(block) - allowed)
    if unknown:
        raise ConfigError(f"{origin}: unknown {label} keys: {', '.join(unknown)}")


def _number(value, label: str, low: float, high: float, origin: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ConfigError(f"{origin}: {label} must be a number")
    number = float(value)
    if number < low or number > high:
        raise ConfigError(f"{origin}: {label} must be between {low} and {high}")
    return number
