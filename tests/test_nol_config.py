import textwrap

import pytest

from config import load_nol_config
from errors import ConfigError


def _write(tmp_path, env_text, nol_targets_text):
    env = tmp_path / ".env"
    env.write_text(textwrap.dedent(env_text))
    nol_targets = tmp_path / "nol_targets.yaml"
    nol_targets.write_text(textwrap.dedent(nol_targets_text))
    return str(env), str(nol_targets)


ENV_OK = """
    [NOL]
    URL=https://tickets.interpark.com/onestop/seat
    GOODS_ID=26005135
    DATE=20260802
    TIME=14:00
    TOGGLE_DATE=2026.08.02
    TOGGLE_TIME=2:00 PM
    [TELEGRAM]
    TELEGRAM_TOKEN="tok123"
    CHAT_ID="chat456"
"""

NOL_TARGETS_OK = """
    targets:
      - grade: "R석"
        section: "A"
        rows: [15, 16]
        consecutive: 2
    poll:
      interval_min: 30
      interval_max: 60
"""


def test_load_nol_config_parses_all_sections(tmp_path):
    env_path, nol_targets_path = _write(tmp_path, ENV_OK, NOL_TARGETS_OK)
    cfg = load_nol_config(env_path, nol_targets_path)

    assert cfg.nol.url == "https://tickets.interpark.com/onestop/seat"
    assert cfg.nol.goods_id == "26005135"
    assert cfg.nol.date == "20260802"
    assert cfg.nol.time == "14:00"
    assert cfg.nol.toggle_date == "2026.08.02"
    assert cfg.nol.toggle_time == "2:00 PM"
    assert cfg.telegram.token == "tok123"
    assert cfg.telegram.chat_id == "chat456"
    assert cfg.targets[0].grade == "R석"
    assert cfg.targets[0].section == "A"
    assert cfg.targets[0].rows == [15, 16]
    assert cfg.targets[0].consecutive == 2
    assert cfg.poll.interval_min == 30
    assert cfg.poll.interval_max == 60


def test_floor_target_field_parsed(tmp_path):
    nol_targets = textwrap.dedent(
        """
        targets:
          - grade: "VIP석"
            section: "B"
            floor: "1층"
            consecutive: 2
        poll:
          interval_min: 30
          interval_max: 60
        """
    )
    env_path, nol_targets_path = _write(tmp_path, ENV_OK, nol_targets)
    cfg = load_nol_config(env_path, nol_targets_path)
    assert cfg.targets[0].floor == "1층"


def test_floor_defaults_to_none_when_absent(tmp_path):
    env_path, nol_targets_path = _write(tmp_path, ENV_OK, NOL_TARGETS_OK)
    cfg = load_nol_config(env_path, nol_targets_path)
    assert cfg.targets[0].floor is None


def test_missing_nol_key_raises_configerror(tmp_path):
    bad_env = ENV_OK.replace("GOODS_ID=26005135\n", "")
    env_path, nol_targets_path = _write(tmp_path, bad_env, NOL_TARGETS_OK)
    with pytest.raises(ConfigError):
        load_nol_config(env_path, nol_targets_path)


def test_missing_nol_section_raises_configerror(tmp_path):
    bad_env = ENV_OK.replace("[NOL]", "[NOPE]")
    env_path, nol_targets_path = _write(tmp_path, bad_env, NOL_TARGETS_OK)
    with pytest.raises(ConfigError):
        load_nol_config(env_path, nol_targets_path)


def test_consecutive_defaults_to_one(tmp_path):
    nol_targets = textwrap.dedent(
        """
        targets:
          - grade: "R석"
        poll:
          interval_min: 30
          interval_max: 60
        """
    )
    env_path, nol_targets_path = _write(tmp_path, ENV_OK, nol_targets)
    cfg = load_nol_config(env_path, nol_targets_path)
    assert cfg.targets[0].consecutive == 1
    assert cfg.targets[0].section is None
    assert cfg.targets[0].rows is None


def test_all_target_fields_optional_except_consecutive(tmp_path):
    nol_targets = textwrap.dedent(
        """
        targets:
          - consecutive: 3
        poll:
          interval_min: 30
          interval_max: 60
        """
    )
    env_path, nol_targets_path = _write(tmp_path, ENV_OK, nol_targets)
    cfg = load_nol_config(env_path, nol_targets_path)
    assert cfg.targets[0].grade is None
    assert cfg.targets[0].section is None
    assert cfg.targets[0].rows is None
    assert cfg.targets[0].consecutive == 3


def test_rows_bad_type_raises_configerror(tmp_path):
    nol_targets = textwrap.dedent(
        """
        targets:
          - grade: "R석"
            rows: "15,16"
        poll:
          interval_min: 30
          interval_max: 60
        """
    )
    env_path, nol_targets_path = _write(tmp_path, ENV_OK, nol_targets)
    with pytest.raises(ConfigError):
        load_nol_config(env_path, nol_targets_path)


def test_rows_with_non_int_element_raises_configerror(tmp_path):
    nol_targets = textwrap.dedent(
        """
        targets:
          - grade: "R석"
            rows: ["열다섯"]
        poll:
          interval_min: 30
          interval_max: 60
        """
    )
    env_path, nol_targets_path = _write(tmp_path, ENV_OK, nol_targets)
    with pytest.raises(ConfigError):
        load_nol_config(env_path, nol_targets_path)


def test_runtime_defaults_when_section_missing(tmp_path):
    env_path, nol_targets_path = _write(tmp_path, ENV_OK, NOL_TARGETS_OK)
    cfg = load_nol_config(env_path, nol_targets_path)
    assert cfg.runtime.debug_port == 9222
    assert cfg.runtime.window_width == 1440
    assert cfg.runtime.max_session_seconds == 540


def test_runtime_values_from_env(tmp_path):
    env = ENV_OK + "\n[RUNTIME]\nDEBUG_PORT=9333\nWINDOW_WIDTH=1600\n"
    env_path, nol_targets_path = _write(tmp_path, env, NOL_TARGETS_OK)
    cfg = load_nol_config(env_path, nol_targets_path)
    assert cfg.runtime.debug_port == 9333
    assert cfg.runtime.window_width == 1600
    # 지정 안 한 키는 기본값
    assert cfg.runtime.window_height == 1000


def test_consecutive_bad_type_raises_configerror(tmp_path):
    nol_targets = textwrap.dedent(
        """
        targets:
          - grade: "R석"
            consecutive: "two"
        poll:
          interval_min: 30
          interval_max: 60
        """
    )
    env_path, nol_targets_path = _write(tmp_path, ENV_OK, nol_targets)
    with pytest.raises(ConfigError):
        load_nol_config(env_path, nol_targets_path)
