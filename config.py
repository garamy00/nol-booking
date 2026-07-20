"""설정 로딩: .env(INI) + targets.yaml → AppConfig."""

from __future__ import annotations

import configparser
from dataclasses import dataclass, field

import yaml

from errors import ConfigError


@dataclass
class NtokConfig:
    url: str
    id_perf: str
    id_time: str
    user_id: str
    password: str


@dataclass
class TelegramConfig:
    token: str
    chat_id: str


@dataclass
class Target:
    floor: str
    section: str
    rows: list[int]
    consecutive: int = 1


@dataclass
class PollConfig:
    interval_min: int
    interval_max: int


@dataclass
class AppConfig:
    ntok: NtokConfig
    telegram: TelegramConfig
    targets: list[Target] = field(default_factory=list)
    poll: PollConfig | None = None


def _strip_quotes(value: str) -> str:
    """INI 값 양끝의 큰따옴표를 제거한다."""
    return value.strip().strip('"')


def _require(section: configparser.SectionProxy, key: str, section_name: str) -> str:
    """섹션에서 키를 읽고 없으면 ConfigError."""
    if key not in section:
        raise ConfigError("missing key %s in [%s]" % (key, section_name))
    return _strip_quotes(section[key])


def load_config(env_path: str, targets_path: str) -> AppConfig:
    """`.env`와 `targets.yaml`을 읽어 검증된 AppConfig를 반환한다.

    Raises:
        ConfigError: 파일 누락·키 누락·형식 오류.
    """
    parser = configparser.ConfigParser()
    if not parser.read(env_path):
        raise ConfigError("cannot read env file: %s" % env_path)

    if "NTOK" not in parser or "TELEGRAM" not in parser:
        raise ConfigError("env must contain [NTOK] and [TELEGRAM] sections")

    ntok_sec = parser["NTOK"]
    ntok = NtokConfig(
        url=_require(ntok_sec, "URL", "NTOK"),
        id_perf=_require(ntok_sec, "IDPERF", "NTOK"),
        id_time=_require(ntok_sec, "IDTIME", "NTOK"),
        user_id=_require(ntok_sec, "ID", "NTOK"),
        password=_require(ntok_sec, "PASSWORD", "NTOK"),
    )

    tg_sec = parser["TELEGRAM"]
    telegram = TelegramConfig(
        token=_require(tg_sec, "TELEGRAM_TOKEN", "TELEGRAM"),
        chat_id=_require(tg_sec, "CHAT_ID", "TELEGRAM"),
    )

    targets, poll = _load_targets(targets_path)
    return AppConfig(ntok=ntok, telegram=telegram, targets=targets, poll=poll)


def _load_targets(targets_path: str) -> tuple[list[Target], PollConfig]:
    """targets.yaml을 파싱해 타깃 목록과 폴링 설정을 반환한다."""
    try:
        with open(targets_path, encoding="utf-8") as handle:
            data = yaml.safe_load(handle)
    except (OSError, yaml.YAMLError) as exc:
        raise ConfigError("cannot load targets file: %s" % targets_path) from exc

    if not data or "targets" not in data or "poll" not in data:
        raise ConfigError("targets file must contain 'targets' and 'poll'")

    targets_raw = data["targets"]
    if not isinstance(targets_raw, list) or len(targets_raw) == 0:
        raise ConfigError("targets must be a non-empty list")

    targets: list[Target] = []
    for i, item in enumerate(targets_raw):
        try:
            if not isinstance(item, dict):
                raise ConfigError("target item %d is not a dictionary" % i)
            floor = item.get("floor")
            if floor is None:
                raise ConfigError("target %d missing required key: floor" % i)
            section = item.get("section")
            if section is None:
                raise ConfigError("target %d missing required key: section" % i)
            rows_raw = item.get("rows")
            if rows_raw is None:
                raise ConfigError("target %d missing required key: rows" % i)
            targets.append(
                Target(
                    floor=str(floor),
                    section=str(section),
                    rows=[int(r) for r in rows_raw],
                    consecutive=int(item.get("consecutive", 1)),
                )
            )
        except (KeyError, TypeError, ValueError) as exc:
            if isinstance(exc, ConfigError):
                raise
            raise ConfigError(
                "invalid target %d: %s" % (i, str(exc))
            ) from exc

    poll_raw = data.get("poll")
    if poll_raw is None:
        raise ConfigError("poll configuration missing")

    try:
        interval_min_val = poll_raw.get("interval_min")
        if interval_min_val is None:
            raise ConfigError("poll missing required key: interval_min")
        interval_max_val = poll_raw.get("interval_max")
        if interval_max_val is None:
            raise ConfigError("poll missing required key: interval_max")
        poll = PollConfig(
            interval_min=int(interval_min_val),
            interval_max=int(interval_max_val),
        )
    except (KeyError, TypeError, ValueError) as exc:
        if isinstance(exc, ConfigError):
            raise
        raise ConfigError("invalid poll configuration: %s" % str(exc)) from exc

    return targets, poll
