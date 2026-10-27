"""DNS, TCP, and HTTP clients. Offline mode uses fixtures and opens no sockets."""

from __future__ import annotations

import socket
import ssl
import urllib.error
import urllib.request
from dataclasses import dataclass
from urllib.parse import urlparse

from rehearse.config import Config, FixtureBook


def normalize_url(url: str) -> str:
    if len(url) > len("https://a/") and url.endswith("/"):
        return url[:-1]
    return url


@dataclass(frozen=True)
class DnsResult:
    ok: bool
    addresses: list[str]
    error: str | None = None


@dataclass(frozen=True)
class TcpResult:
    ok: bool
    error: str | None = None


@dataclass(frozen=True)
class HttpResult:
    ok: bool
    status: int | None
    error: str | None
    url: str


class _HttpsOnlyRedirect(urllib.request.HTTPRedirectHandler):
    max_redirections = 3

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        parsed = urlparse(newurl)
        if parsed.scheme not in {"http", "https"} or parsed.username or parsed.password:
            raise urllib.error.HTTPError(
                req.full_url,
                code,
                "redirect target is not a plain http(s) URL",
                headers,
                fp,
            )
        return super().redirect_request(req, fp, code, msg, headers, newurl)


class LiveNetwork:
    """Active probes. DNS lookup, TCP connect, HTTP HEAD with a one-byte GET fallback."""

    def __init__(self, config: Config):
        self.config = config

    def resolve(self, host: str) -> DnsResult:
        try:
            infos = socket.getaddrinfo(host, None)
        except socket.gaierror as exc:
            return DnsResult(False, [], str(exc))
        addresses = sorted({item[4][0] for item in infos})
        if not addresses:
            return DnsResult(False, [], "no addresses returned")
        return DnsResult(True, addresses, None)

    def tcp(self, host: str, port: int) -> TcpResult:
        try:
            with socket.create_connection((host, port), timeout=self.config.tcp_timeout):
                return TcpResult(True, None)
        except OSError as exc:
            return TcpResult(False, str(exc))

    def http(self, url: str) -> HttpResult:
        rejected = _reject_url(url)
        if rejected:
            return HttpResult(False, None, rejected, url)
        status, error = _request(url, self.config.http_timeout, self.config.use_environment_proxy, "HEAD")
        if status in {405, 501}:
            status, error = _request(url, self.config.http_timeout, self.config.use_environment_proxy, "GET")
        if error:
            return HttpResult(False, status, error, url)
        if status is None:
            return HttpResult(False, None, "no status", url)
        if 200 <= status < 400:
            return HttpResult(True, status, None, url)
        return HttpResult(False, status, f"HTTP {status}", url)


class FixtureNetwork:
    """Answers from rehearse.yaml. Does not import socket functions into the call path."""

    def __init__(self, fixtures: FixtureBook):
        self.fixtures = fixtures

    def resolve(self, host: str) -> DnsResult:
        spec = self.fixtures.hosts.get(host.casefold())
        if spec is None:
            return DnsResult(
                False,
                [],
                "no offline fixture for this host; live DNS is disabled",
            )
        addresses = list(spec.get("addresses") or [])
        if not addresses:
            return DnsResult(False, [], spec.get("error") or "fixture NXDOMAIN")
        return DnsResult(True, addresses, None)

    def tcp(self, host: str, port: int) -> TcpResult:
        spec = self.fixtures.hosts.get(host.casefold())
        if spec is None:
            return TcpResult(False, "no offline fixture for this host; live TCP is disabled")
        state = (spec.get("ports") or {}).get(str(port))
        if state == "open":
            return TcpResult(True, None)
        if state == "closed":
            return TcpResult(False, "fixture: connection refused")
        return TcpResult(False, f"no offline TCP fixture for port {port}")

    def http(self, url: str) -> HttpResult:
        rejected = _reject_url(url)
        if rejected:
            return HttpResult(False, None, rejected, url)
        spec = self.fixtures.urls.get(normalize_url(url))
        if spec is None:
            return HttpResult(
                False,
                None,
                "no offline fixture for this URL; live HTTP is disabled",
                url,
            )
        status = int(spec["status"])
        if 200 <= status < 400:
            return HttpResult(True, status, None, url)
        reason = spec.get("reason") or f"HTTP {status}"
        return HttpResult(False, status, str(reason), url)


def describe_http(result: HttpResult) -> str:
    if result.ok:
        return f"HTTP {result.status}"
    if result.status and result.error and result.error != f"HTTP {result.status}":
        return f"HTTP {result.status} ({result.error})"
    return result.error or "HTTP check failed"


def build_network(config: Config):
    if config.mode == "offline":
        return FixtureNetwork(config.fixtures)
    return LiveNetwork(config)


def _reject_url(url: str) -> str | None:
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"}:
        return "only http and https URLs are checked"
    if parsed.username or parsed.password:
        return "URLs with embedded credentials are not checked"
    if not parsed.hostname:
        return "URL has no host"
    return None


def _request(url: str, timeout: float, use_proxy: bool, method: str) -> tuple[int | None, str | None]:
    request = urllib.request.Request(
        url,
        method=method,
        headers={"User-Agent": "RunbookRehearsal/0.1.0"},
    )
    handlers: list = [_HttpsOnlyRedirect()]
    if not use_proxy:
        handlers.append(urllib.request.ProxyHandler({}))
    context = ssl.create_default_context()
    handlers.append(urllib.request.HTTPSHandler(context=context))
    opener = urllib.request.build_opener(*handlers)
    try:
        with opener.open(request, timeout=timeout) as response:
            if method == "GET":
                response.read(1)
            return getattr(response, "status", None) or response.getcode(), None
    except urllib.error.HTTPError as exc:
        return exc.code, f"HTTP {exc.code}"
    except Exception as exc:  # noqa: BLE001 - probe failures become findings
        return None, _short_error(exc)


def _short_error(exc: Exception) -> str:
    text = str(exc).strip() or exc.__class__.__name__
    return text.splitlines()[0][:300]
