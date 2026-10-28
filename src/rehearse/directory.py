"""Group existence lookups. Stub, LDAP, and Microsoft Graph.

The stub provider matches a local list. It is for demos and fixtures.
LDAP and Graph run only when directory.provider is set and the credential
environment variable is present. Passwords and tokens are read at call time
and redacted from error text.
"""

from __future__ import annotations

import json
import os
import re
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass

from rehearse.config import Config, GraphSettings, LdapSettings

GUID_RE = re.compile(
    r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$"
)
_FILTER_ESCAPES = {
    "*": r"\2a",
    "(": r"\28",
    ")": r"\29",
    "\\": r"\5c",
    "\x00": r"\00",
}


@dataclass(frozen=True)
class GroupLookup:
    status: str
    message: str
    provider: str
    evidence: dict


def escape_filter(value: str) -> str:
    return "".join(_FILTER_ESCAPES.get(char, char) for char in value)


def looks_like_dn(value: str) -> bool:
    return bool(re.search(r"(?i)(?:^|[,+])\s*(?:CN|OU|DC|O|UID)=", value))


def build_ldap_search(target: str, base_dn: str) -> tuple[str, str, str]:
    if looks_like_dn(target):
        return target, "(objectClass=group)", "BASE"
    return base_dn, f"(&(objectClass=group)(cn={escape_filter(target)}))", "SUBTREE"


def graph_group_url(endpoint: str, target: str) -> str:
    base = endpoint.rstrip("/")
    if GUID_RE.fullmatch(target):
        return f"{base}/groups/{urllib.parse.quote(target)}?$select=id,displayName"
    escaped = target.replace("'", "''")
    filt = urllib.parse.quote(f"displayName eq '{escaped}'", safe="")
    return f"{base}/groups?$select=id,displayName&$top=1&$filter={filt}"


def interpret_graph(status: int, body: str) -> tuple[str, str, dict]:
    if status in {401, 403}:
        return "warn", f"Microsoft Graph denied the read (HTTP {status})", {"status": status}
    if status == 404:
        return "fail", "group not found in Microsoft Graph", {"status": status}
    if status >= 400:
        return "fail", f"Microsoft Graph returned HTTP {status}", {"status": status}
    try:
        payload = json.loads(body or "{}")
    except json.JSONDecodeError:
        return "fail", "Microsoft Graph returned a body that is not JSON", {"status": status}
    if isinstance(payload, dict) and "value" in payload:
        values = payload.get("value") or []
        if not values:
            return "fail", "group not found in Microsoft Graph", {"status": status}
        name = values[0].get("displayName")
        return "pass", f"group found ({name})" if name else "group found", {
            "status": status,
            "displayName": name,
        }
    if isinstance(payload, dict) and payload.get("id"):
        name = payload.get("displayName")
        return "pass", f"group found ({name})" if name else "group found", {
            "status": status,
            "displayName": name,
        }
    return "fail", "group not found in Microsoft Graph", {"status": status}


def redact(text: str) -> str:
    redacted = text
    for name in ("REHEARSE_GRAPH_TOKEN", "REHEARSE_LDAP_PASSWORD"):
        secret = os.environ.get(name, "")
        if secret:
            redacted = redacted.replace(secret, "[redacted]")
    return redacted


class NoneDirectory:
    provider = "none"

    def lookup(self, target: str, directory: str | None) -> GroupLookup:
        return GroupLookup(
            "warn",
            "directory provider is none; group existence was not checked",
            self.provider,
            {"target": target, "directory": directory, "authoritative": False},
        )


class StubDirectory:
    provider = "stub"

    def __init__(self, groups: list[str]):
        self._groups = {item.casefold(): item for item in groups}

    def lookup(self, target: str, directory: str | None) -> GroupLookup:
        found = target.strip().casefold() in self._groups
        if found:
            message = "group is listed in the stub directory"
            status = "pass"
        else:
            message = "group is not listed in the stub directory"
            status = "fail"
        return GroupLookup(
            status,
            message,
            self.provider,
            {
                "target": target,
                "directory": directory,
                "authoritative": False,
                "note": "stub results are local fixtures, not Active Directory or Entra ID",
            },
        )


class LdapDirectory:
    provider = "ldap"

    def __init__(self, settings: LdapSettings, connect=None, load_library=None):
        self.settings = settings
        self._connect = connect
        self._load_library = load_library or _import_ldap3

    def lookup(self, target: str, directory: str | None) -> GroupLookup:
        password = os.environ.get("REHEARSE_LDAP_PASSWORD", "")
        if not password:
            return GroupLookup(
                "warn",
                "REHEARSE_LDAP_PASSWORD is not set; the LDAP group was not queried",
                self.provider,
                {"target": target, "authoritative": False},
            )
        connect = self._connect
        if connect is None:
            try:
                library = self._load_library()
            except ImportError:
                return GroupLookup(
                    "warn",
                    "ldap3 is not installed; the LDAP group was not queried. "
                    "Install it with pip install 'runbookrehearsal[directory]'.",
                    self.provider,
                    {"target": target, "authoritative": False},
                )
            connect = lambda cfg, secret: _real_ldap_connect(library, cfg, secret)  # noqa: E731
        base, filt, scope = build_ldap_search(target, self.settings.base_dn)
        try:
            connection = connect(self.settings, password)
            try:
                entries = connection.search(base, filt, scope)
            finally:
                connection.unbind()
        except Exception as exc:  # noqa: BLE001 - surfaced as a finding, secrets stripped
            return GroupLookup(
                "fail",
                "LDAP query failed: " + redact(str(exc) or exc.__class__.__name__),
                self.provider,
                {"target": target, "authoritative": True},
            )
        if entries:
            return GroupLookup(
                "pass",
                "group found in LDAP",
                self.provider,
                {"target": target, "filter": filt, "scope": scope, "authoritative": True},
            )
        return GroupLookup(
            "fail",
            "group not found in LDAP",
            self.provider,
            {"target": target, "filter": filt, "scope": scope, "authoritative": True},
        )


class GraphDirectory:
    provider = "graph"

    def __init__(self, settings: GraphSettings, opener=None):
        self.settings = settings
        self._opener = opener or _graph_open

    def lookup(self, target: str, directory: str | None) -> GroupLookup:
        token = os.environ.get("REHEARSE_GRAPH_TOKEN", "")
        if not token:
            return GroupLookup(
                "warn",
                "REHEARSE_GRAPH_TOKEN is not set; the Entra group was not queried",
                self.provider,
                {"target": target, "authoritative": False},
            )
        url = graph_group_url(self.settings.endpoint, target)
        request = urllib.request.Request(
            url,
            headers={
                "Authorization": f"Bearer {token}",
                "Accept": "application/json",
                "User-Agent": "RunbookRehearsal/0.2.0",
            },
        )
        try:
            status, body = self._opener(request, self.settings.timeout_seconds)
        except Exception as exc:  # noqa: BLE001
            return GroupLookup(
                "fail",
                "Microsoft Graph request failed: " + redact(str(exc) or exc.__class__.__name__),
                self.provider,
                {"target": target, "authoritative": True},
            )
        status_name, message, evidence = interpret_graph(status, body)
        evidence = {"target": target, "authoritative": status_name != "warn", **evidence}
        return GroupLookup(status_name, message, self.provider, evidence)


def build_directory(config: Config):
    provider = config.directory_provider
    if provider == "stub":
        return StubDirectory(config.stub_groups)
    if provider == "ldap":
        if config.ldap is None:
            raise ValueError("LDAP provider requires ldap settings")
        return LdapDirectory(config.ldap)
    if provider == "graph":
        return GraphDirectory(config.graph or GraphSettings())
    return NoneDirectory()


def _import_ldap3():
    import ldap3

    return ldap3


def _real_ldap_connect(ldap3, settings: LdapSettings, password: str):
    server = ldap3.Server(
        settings.host,
        port=settings.port,
        use_ssl=settings.use_ssl,
        connect_timeout=settings.timeout_seconds,
    )
    connection = ldap3.Connection(
        server,
        user=settings.bind_dn,
        password=password,
        auto_bind=True,
        receive_timeout=settings.timeout_seconds,
        read_only=True,
    )

    class _Bound:
        def search(self, base: str, filt: str, scope: str):
            scope_value = {
                "BASE": ldap3.BASE,
                "SUBTREE": ldap3.SUBTREE,
            }[scope]
            connection.search(base, filt, search_scope=scope_value, attributes=["cn"])
            return list(connection.entries)

        def unbind(self):
            connection.unbind()

    return _Bound()


def _graph_open(request: urllib.request.Request, timeout: float) -> tuple[int, str]:
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    try:
        with opener.open(request, timeout=timeout) as response:
            body = response.read(1_048_576).decode("utf-8", errors="replace")
            return response.getcode(), body
    except urllib.error.HTTPError as exc:
        body = exc.read(1_048_576).decode("utf-8", errors="replace")
        return exc.code, body
