"""Syntax checks never execute the script. Directory helpers stay local."""

import urllib.parse
from pathlib import Path

from rehearse.directory import (
    GraphDirectory,
    LdapDirectory,
    build_ldap_search,
    escape_filter,
    graph_group_url,
    interpret_graph,
    redact,
)
from rehearse.config import GraphSettings, LdapSettings
from rehearse.syntax import check_script


def test_python_and_bash_do_not_execute(tmp_path: Path):
    marker = tmp_path / "marker.txt"
    python_script = tmp_path / "side_effect.py"
    python_script.write_text(
        f"open({str(marker)!r}, 'w').write('x')\n",
        encoding="utf-8",
    )
    result = check_script(python_script, "python")
    assert result.status == "pass"
    assert not marker.exists()

    broken = tmp_path / "broken.py"
    broken.write_text("def rebuild(:\n    return (\n", encoding="utf-8")
    assert check_script(broken, "python").status == "fail"

    bash_script = tmp_path / "side_effect.sh"
    bash_script.write_text(f"touch {marker}\n", encoding="utf-8")
    bash_result = check_script(bash_script, "bash")
    assert bash_result.status == "pass"
    assert "not executed" in bash_result.message
    assert not marker.exists()

    bad_bash = tmp_path / "bad.sh"
    bad_bash.write_text("if [ -d /tmp ]; then\n  echo no\n", encoding="utf-8")
    assert check_script(bad_bash, "bash").status == "fail"


def test_powershell_parser_or_honest_skip(tmp_path: Path):
    import shutil

    script = tmp_path / "note.ps1"
    marker = tmp_path / "marker.txt"
    script.write_text(
        f"Set-Content -LiteralPath '{marker}' -Value 'x'\n",
        encoding="utf-8",
    )
    result = check_script(script, "powershell")
    if shutil.which("pwsh"):
        assert result.status == "pass"
        assert not marker.exists()
        broken = tmp_path / "broken.ps1"
        broken.write_text("if ($true) {\n    Write-Output 'x'\n", encoding="utf-8")
        failed = check_script(broken, "powershell")
        assert failed.status == "fail"
        assert failed.details
    else:
        assert result.status == "warn"
        assert "pwsh" in result.message
        assert not marker.exists()


def test_ldap_filter_and_graph_url():
    assert escape_filter("a*(b)") == r"a\2a\28b\29"
    base, filt, scope = build_ldap_search("Ops (Team)", "DC=harborpine,DC=example")
    assert scope == "SUBTREE"
    assert base == "DC=harborpine,DC=example"
    assert r"\28" in filt
    dn = "CN=Linux-Operators,OU=Groups,DC=harborpine,DC=example"
    base, filt, scope = build_ldap_search(dn, "DC=harborpine,DC=example")
    assert scope == "BASE"
    assert base == dn
    assert filt == "(objectClass=group)"

    quoted = graph_group_url("https://graph.microsoft.com/v1.0", "O'Brien")
    assert "O''Brien" in urllib.parse.unquote(quoted)
    assert "$filter=" in quoted
    guid = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
    by_id = graph_group_url("https://graph.microsoft.com/v1.0/", guid)
    assert f"/groups/{guid}" in by_id


def test_graph_interpretation_and_redaction(monkeypatch):
    status, message, _evidence = interpret_graph(200, '{"value":[{"id":"1","displayName":"Ops"}]}')
    assert status == "pass"
    assert "Ops" in message
    status, message, _evidence = interpret_graph(200, '{"value":[]}')
    assert status == "fail"
    status, message, _evidence = interpret_graph(401, "")
    assert status == "warn"
    status, message, _evidence = interpret_graph(404, "")
    assert status == "fail"

    monkeypatch.setenv("REHEARSE_GRAPH_TOKEN", "super-secret-token")
    assert "super-secret-token" not in redact("failed super-secret-token")

    def opener(request, timeout):
        auth = request.get_header("Authorization")
        raise RuntimeError(f"boom {auth}")

    directory = GraphDirectory(GraphSettings(), opener=opener)
    lookup = directory.lookup("Ops", "entra")
    assert lookup.status == "fail"
    assert "super-secret-token" not in lookup.message
    assert "[redacted]" in lookup.message


def test_ldap_fake_connection_and_missing_library(monkeypatch):
    monkeypatch.setenv("REHEARSE_LDAP_PASSWORD", "pw-secret")

    class Conn:
        def __init__(self):
            self.unbound = False

        def search(self, base, filt, scope):
            assert scope == "BASE"
            return ["group"]

        def unbind(self):
            self.unbound = True

    conn = Conn()
    directory = LdapDirectory(
        LdapSettings(host="ldap.harborpine.example", bind_dn="cn=reader", base_dn="DC=harborpine,DC=example"),
        connect=lambda _settings, password: conn,
    )
    found = directory.lookup("CN=Ops,DC=harborpine,DC=example", "active_directory")
    assert found.status == "pass"
    assert conn.unbound
    assert "pw-secret" not in found.message

    def explode(_settings, password):
        raise RuntimeError(f"bind failed {password}")

    failing = LdapDirectory(
        LdapSettings(host="ldap.harborpine.example", bind_dn="cn=reader", base_dn="DC=harborpine,DC=example"),
        connect=explode,
    )
    failed = failing.lookup("Ops", "active_directory")
    assert failed.status == "fail"
    assert "pw-secret" not in failed.message

    monkeypatch.delenv("REHEARSE_LDAP_PASSWORD")
    skipped = directory.lookup("Ops", None)
    assert skipped.status == "warn"

    monkeypatch.setenv("REHEARSE_LDAP_PASSWORD", "pw-secret")
    missing = LdapDirectory(
        LdapSettings(host="ldap.harborpine.example", bind_dn="cn=reader", base_dn="DC=harborpine,DC=example"),
        load_library=lambda: (_ for _ in ()).throw(ImportError("ldap3")),
    )
    # connect is None, so the import path runs.
    warned = missing.lookup("Ops", "active_directory")
    assert warned.status == "warn"
    assert "ldap3" in warned.message


def test_powershell_helper_is_ascii():
    from rehearse.locate import powershell_helper

    powershell_helper().read_text(encoding="ascii")
