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
