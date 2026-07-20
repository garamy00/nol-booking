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


def test_is_debugger_up_false_when_request_fails(monkeypatch):
    def boom(*args, **kwargs):
        import requests

        raise requests.RequestException("no server")

    import requests

    monkeypatch.setattr(requests, "get", boom)
    assert nol_chrome.is_debugger_up() is False


def test_wait_for_debugger_raises_on_timeout(monkeypatch):
    monkeypatch.setattr(nol_chrome, "is_debugger_up", lambda: False)
    monkeypatch.setattr(nol_chrome.time, "sleep", lambda _s: None)
    with pytest.raises(LauncherError):
        nol_chrome.wait_for_debugger(timeout=0.0)


def test_wait_for_debugger_returns_when_up(monkeypatch):
    monkeypatch.setattr(nol_chrome, "is_debugger_up", lambda: True)
    nol_chrome.wait_for_debugger(timeout=5.0)
