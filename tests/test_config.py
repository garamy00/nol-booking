import textwrap

import pytest

from config import load_config
from errors import ConfigError


def _write(tmp_path, env_text, targets_text):
    env = tmp_path / ".env"
    env.write_text(textwrap.dedent(env_text))
    targets = tmp_path / "targets.yaml"
    targets.write_text(textwrap.dedent(targets_text))
    return str(env), str(targets)


ENV_OK = """
    [NTOK]
    URL=https://booking.ntok.go.kr/x.aspx
    IDPERF=267114
    IDTIME=81857
    ID=myid
    PASSWORD=mypw
    [TELEGRAM]
    TELEGRAM_TOKEN="tok123"
    CHAT_ID="chat456"
"""

TARGETS_OK = """
    targets:
      - floor: "1F"
        section: "B"
        rows: [1, 2, 3]
        consecutive: 2
    poll:
      interval_min: 30
      interval_max: 60
"""


def test_load_config_parses_all_sections(tmp_path):
    env_path, targets_path = _write(tmp_path, ENV_OK, TARGETS_OK)
    cfg = load_config(env_path, targets_path)

    assert cfg.ntok.id_perf == "267114"
    assert cfg.ntok.password == "mypw"
    # 큰따옴표는 제거되어야 한다
    assert cfg.telegram.token == "tok123"
    assert cfg.telegram.chat_id == "chat456"
    assert cfg.targets[0].section == "B"
    assert cfg.targets[0].rows == [1, 2, 3]
    assert cfg.targets[0].consecutive == 2
    assert cfg.poll.interval_min == 30


def test_missing_ntok_key_raises_configerror(tmp_path):
    bad_env = ENV_OK.replace("IDPERF=267114\n", "")
    env_path, targets_path = _write(tmp_path, bad_env, TARGETS_OK)
    with pytest.raises(ConfigError):
        load_config(env_path, targets_path)


def test_consecutive_defaults_to_one(tmp_path):
    targets = TARGETS_OK.replace("        consecutive: 2\n", "")
    env_path, targets_path = _write(tmp_path, ENV_OK, targets)
    cfg = load_config(env_path, targets_path)
    assert cfg.targets[0].consecutive == 1


def test_empty_targets_raises_configerror(tmp_path):
    targets_yaml = """
    targets: []
    poll:
      interval_min: 30
      interval_max: 60
    """
    env_path, targets_path = _write(tmp_path, ENV_OK, targets_yaml)
    with pytest.raises(ConfigError):
        load_config(env_path, targets_path)


def test_target_missing_floor_raises_configerror(tmp_path):
    targets_yaml = """
    targets:
      - section: "B"
        rows: [1, 2, 3]
    poll:
      interval_min: 30
      interval_max: 60
    """
    env_path, targets_path = _write(tmp_path, ENV_OK, targets_yaml)
    with pytest.raises(ConfigError):
        load_config(env_path, targets_path)


def test_target_missing_section_raises_configerror(tmp_path):
    targets_yaml = """
    targets:
      - floor: "1F"
        rows: [1, 2, 3]
    poll:
      interval_min: 30
      interval_max: 60
    """
    env_path, targets_path = _write(tmp_path, ENV_OK, targets_yaml)
    with pytest.raises(ConfigError):
        load_config(env_path, targets_path)


def test_target_missing_rows_raises_configerror(tmp_path):
    targets_yaml = """
    targets:
      - floor: "1F"
        section: "B"
    poll:
      interval_min: 30
      interval_max: 60
    """
    env_path, targets_path = _write(tmp_path, ENV_OK, targets_yaml)
    with pytest.raises(ConfigError):
        load_config(env_path, targets_path)


def test_poll_missing_interval_min_raises_configerror(tmp_path):
    targets_yaml = """
    targets:
      - floor: "1F"
        section: "B"
        rows: [1, 2, 3]
    poll:
      interval_max: 60
    """
    env_path, targets_path = _write(tmp_path, ENV_OK, targets_yaml)
    with pytest.raises(ConfigError):
        load_config(env_path, targets_path)


def test_poll_missing_interval_max_raises_configerror(tmp_path):
    targets_yaml = """
    targets:
      - floor: "1F"
        section: "B"
        rows: [1, 2, 3]
    poll:
      interval_min: 30
    """
    env_path, targets_path = _write(tmp_path, ENV_OK, targets_yaml)
    with pytest.raises(ConfigError):
        load_config(env_path, targets_path)


def test_non_integer_rows_raises_configerror(tmp_path):
    targets_yaml = """
    targets:
      - floor: "1F"
        section: "B"
        rows: ["a", "b", "c"]
    poll:
      interval_min: 30
      interval_max: 60
    """
    env_path, targets_path = _write(tmp_path, ENV_OK, targets_yaml)
    with pytest.raises(ConfigError):
        load_config(env_path, targets_path)


def test_poll_not_mapping_raises_configerror(tmp_path):
    targets_yaml = """
    targets:
      - floor: "1F"
        section: "B"
        rows: [1, 2, 3]
    poll: sometext
    """
    env_path, targets_path = _write(tmp_path, ENV_OK, targets_yaml)
    with pytest.raises(ConfigError):
        load_config(env_path, targets_path)


def test_non_integer_interval_min_raises_configerror(tmp_path):
    targets_yaml = """
    targets:
      - floor: "1F"
        section: "B"
        rows: [1, 2, 3]
    poll:
      interval_min: "thirty"
      interval_max: 60
    """
    env_path, targets_path = _write(tmp_path, ENV_OK, targets_yaml)
    with pytest.raises(ConfigError):
        load_config(env_path, targets_path)
