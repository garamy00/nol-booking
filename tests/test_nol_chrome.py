import signal
import textwrap

import pytest

from errors import LauncherError
import nol_chrome


def _write_env(tmp_path, text):
    env = tmp_path / ".env"
    env.write_text(textwrap.dedent(text))
    return str(env)


ENV_OK = """
    [NOL]
    URL=https://tickets.interpark.com/goods
    GOODS_ID=26005135  # 인라인 주석
    DATE=20260802
    TIME=14:00
    TOGGLE_DATE=2026.08.02
    TOGGLE_TIME=2:00 PM
    [TELEGRAM]
    TELEGRAM_TOKEN="tok123"
    CHAT_ID="chat456"
"""


def test_read_goods_url_joins_url_and_id_ignoring_inline_comment(tmp_path):
    env_path = _write_env(tmp_path, ENV_OK)
    assert nol_chrome._read_goods_url(env_path) == (
        "https://tickets.interpark.com/goods/26005135"
    )


def test_read_goods_url_missing_key_raises(tmp_path):
    bad = ENV_OK.replace("GOODS_ID=26005135  # 인라인 주석\n", "")
    env_path = _write_env(tmp_path, bad)
    with pytest.raises(LauncherError):
        nol_chrome._read_goods_url(env_path)


def test_read_goods_url_missing_section_raises(tmp_path):
    bad = ENV_OK.replace("[NOL]", "[NOPE]")
    env_path = _write_env(tmp_path, bad)
    with pytest.raises(LauncherError):
        nol_chrome._read_goods_url(env_path)


def test_debug_port_from_env_section(tmp_path, monkeypatch):
    env = tmp_path / ".env"
    env.write_text("[RUNTIME]\nDEBUG_PORT=9444\n")
    assert nol_chrome._read_debug_port(str(env)) == 9444


def test_debug_port_defaults_when_absent(tmp_path):
    env = tmp_path / ".env"
    env.write_text("[NOL]\nURL=https://x\nGOODS_ID=1\n")
    assert nol_chrome._read_debug_port(str(env)) == 9222


def test_is_debugger_up_false_when_request_fails(monkeypatch):
    def boom(*args, **kwargs):
        import requests

        raise requests.RequestException("no server")

    import requests

    monkeypatch.setattr(requests, "get", boom)
    assert nol_chrome.is_debugger_up() is False


def test_wait_for_debugger_raises_on_timeout(monkeypatch):
    monkeypatch.setattr(nol_chrome, "is_debugger_up", lambda _port=None: False)
    monkeypatch.setattr(nol_chrome.time, "sleep", lambda _s: None)
    with pytest.raises(LauncherError):
        nol_chrome.wait_for_debugger(timeout=0.0)


def test_wait_for_debugger_returns_when_up(monkeypatch):
    monkeypatch.setattr(nol_chrome, "is_debugger_up", lambda _port=None: True)
    nol_chrome.wait_for_debugger(timeout=5.0)


def test_build_launch_args_has_flags_and_url_last():
    args = nol_chrome._build_launch_args("https://x/goods/1")
    assert args[-1] == "https://x/goods/1"
    assert "--remote-debugging-port=9222" in args
    assert any(
        a.startswith("--user-data-dir=") and a.endswith("chrome_profile") for a in args
    )


def test_chrome_binary_env_override(monkeypatch):
    monkeypatch.setenv("NOL_CHROME_BINARY", "/custom/chrome")
    assert nol_chrome._chrome_binary() == "/custom/chrome"


def test_chrome_binary_env_override_wins(monkeypatch):
    monkeypatch.setenv("NOL_CHROME_BINARY", "/custom/chrome")
    assert nol_chrome._chrome_binary() == "/custom/chrome"


def test_chrome_binary_finds_linux_chromium(monkeypatch):
    monkeypatch.delenv("NOL_CHROME_BINARY", raising=False)
    monkeypatch.setattr(nol_chrome.sys, "platform", "linux")
    found = {"chromium": "/usr/bin/chromium"}
    monkeypatch.setattr(nol_chrome.shutil, "which", lambda name: found.get(name))
    assert nol_chrome._chrome_binary() == "/usr/bin/chromium"


def test_chrome_binary_raises_when_none_found_on_linux(monkeypatch):
    monkeypatch.delenv("NOL_CHROME_BINARY", raising=False)
    monkeypatch.setattr(nol_chrome.sys, "platform", "linux")
    monkeypatch.setattr(nol_chrome.shutil, "which", lambda name: None)
    with pytest.raises(LauncherError):
        nol_chrome._chrome_binary()


def test_main_noop_when_debugger_already_up(monkeypatch):
    called = {"launch": False}
    monkeypatch.setattr(nol_chrome, "is_debugger_up", lambda _port=None: True)
    monkeypatch.setattr(
        nol_chrome,
        "launch_chrome",
        lambda _u, _port=None: called.__setitem__("launch", True),
    )
    nol_chrome.main()
    assert called["launch"] is False


def test_main_launches_when_debugger_down(monkeypatch):
    calls = {"launch": None, "waited": False}
    monkeypatch.setattr(nol_chrome, "is_debugger_up", lambda _port=None: False)
    monkeypatch.setattr(nol_chrome, "_read_goods_url", lambda _p: "https://x/g/1")
    monkeypatch.setattr(
        nol_chrome,
        "launch_chrome",
        lambda u, _port=None: calls.__setitem__("launch", u),
    )
    monkeypatch.setattr(
        nol_chrome,
        "wait_for_debugger",
        lambda _port=None: calls.__setitem__("waited", True),
    )
    nol_chrome.main()
    assert calls["launch"] == "https://x/g/1"
    assert calls["waited"] is True


# stop / PID 파일 (창 종료 후 남는 Chrome 정상 종료)


def test_launch_chrome_writes_pidfile(tmp_path, monkeypatch):
    pidfile = tmp_path / ".nol_chrome.pid"
    monkeypatch.setattr(nol_chrome, "PID_PATH", str(pidfile))

    class _FakeProc:
        pid = 4242

    monkeypatch.setattr(nol_chrome.subprocess, "Popen", lambda *a, **k: _FakeProc())

    nol_chrome.launch_chrome("https://x/goods/1")

    assert pidfile.read_text().strip() == "4242"


def test_stop_sends_sigterm_and_removes_pidfile(tmp_path, monkeypatch):
    pidfile = tmp_path / ".nol_chrome.pid"
    pidfile.write_text("12345")
    monkeypatch.setattr(nol_chrome, "PID_PATH", str(pidfile))
    killed = []
    monkeypatch.setattr(
        nol_chrome.os, "kill", lambda pid, sig: killed.append((pid, sig))
    )

    nol_chrome.stop()

    assert killed == [(12345, signal.SIGTERM)]
    assert not pidfile.exists()


def test_stop_without_pidfile_is_noop(tmp_path, monkeypatch):
    pidfile = tmp_path / ".nol_chrome.pid"  # 생성하지 않음
    monkeypatch.setattr(nol_chrome, "PID_PATH", str(pidfile))
    killed = []
    monkeypatch.setattr(
        nol_chrome.os, "kill", lambda pid, sig: killed.append((pid, sig))
    )

    nol_chrome.stop()  # 예외 없이 넘어가야 한다

    assert killed == []


def test_stop_dead_process_still_removes_pidfile(tmp_path, monkeypatch):
    pidfile = tmp_path / ".nol_chrome.pid"
    pidfile.write_text("999999")
    monkeypatch.setattr(nol_chrome, "PID_PATH", str(pidfile))

    def _raise(pid, sig):
        raise ProcessLookupError()

    monkeypatch.setattr(nol_chrome.os, "kill", _raise)

    nol_chrome.stop()  # 이미 죽은 프로세스여도 예외 없이 정리

    assert not pidfile.exists()
