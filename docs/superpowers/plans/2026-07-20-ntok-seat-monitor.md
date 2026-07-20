# 국립극장 좌석 모니터 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 국립극장 예매 페이지에서 지정 좌석(층·구역·열·연석 수)이 예매 가능해지면 텔레그램으로 알리는 폴링 모니터를 만든다.

**Architecture:** Selenium(Chrome)으로 `.env`의 계정으로 직접 로그인 → 좌석 페이지 진입 → 30~60초 지터 간격으로 좌석맵 DOM을 파싱해 가용 좌석을 수집 → `targets.yaml`의 타깃·연석 조건으로 매칭 → 직전 회차 대비 신규 묶음만 텔레그램 알림. 순수 로직(설정·매칭·dedupe·알림)과 브라우저 드라이버를 파일로 분리한다.

**Tech Stack:** Python 3.10+, Selenium, PyYAML, requests, configparser(표준 라이브러리), pytest.

## Global Constraints

- Python 3.10+ 타입 힌트: `X | None` 사용(`Optional` 금지).
- 최대 줄 길이 88자, 포매터 `ruff format`, 린터 `ruff check`.
- 로그는 `logging` 모듈 사용(`print` 금지), 로그 메시지는 영문, `%` 지연 포매팅.
- 구조 데이터는 dataclass 사용.
- 비밀값(토큰·PW)을 로그·주석·커밋에 노출하지 않는다.
- 도메인 예외는 `AppBaseError`를 상속하는 계층으로 정의한다.
- `.env`는 INI 형식이므로 `configparser`로 읽는다(python-dotenv 아님). 값의 양끝 큰따옴표는 제거한다.
- 커밋 메시지: `<type>: <요약>` (feat/fix/refactor/test/docs/chore).
- 파일 위치는 `booking/` 루트 기준. (참고: 이 디렉토리는 아직 git 저장소가 아님 — Task 0에서 초기화)

---

### Task 0: 프로젝트 스캐폴딩

**Files:**
- Create: `requirements.txt`
- Create: `pyproject.toml` (ruff 설정 + pytest 경로)
- Create: `targets.yaml`
- Create: `errors.py`
- Create: `tests/__init__.py`

**Interfaces:**
- Produces: 도메인 예외 계층 `AppBaseError`, `ConfigError`, `DriverError`, `NotifyError`.

- [ ] **Step 1: git 저장소 초기화 및 .gitignore 작성**

`.gitignore` 생성(내용):
```
__pycache__/
*.pyc
.env
.pytest_cache/
chrome_profile/
```

Run:
```bash
cd /Users/sondaegon/source/python/booking && git init
```
Expected: `Initialized empty Git repository`

- [ ] **Step 2: requirements.txt 작성**

```
selenium>=4.20
PyYAML>=6.0
requests>=2.31
pytest>=8.0
```

- [ ] **Step 3: pyproject.toml 작성**

```toml
[tool.ruff]
line-length = 88

[tool.pytest.ini_options]
testpaths = ["tests"]
```

- [ ] **Step 4: 도메인 예외 정의 (errors.py)**

```python
"""애플리케이션 도메인 예외 계층."""


class AppBaseError(Exception):
    """모든 애플리케이션 예외의 최상위."""


class ConfigError(AppBaseError):
    """설정 로딩·검증 실패."""


class DriverError(AppBaseError):
    """브라우저 제어·페이지 파싱 실패."""


class NotifyError(AppBaseError):
    """알림 전송 실패."""
```

- [ ] **Step 5: targets.yaml 초기 작성**

```yaml
targets:
  - floor: "1F"
    section: "B"
    rows: [1, 2, 3, 4, 5]
    consecutive: 2
poll:
  interval_min: 30
  interval_max: 60
```

- [ ] **Step 6: tests 패키지 생성**

빈 파일 `tests/__init__.py` 생성.

- [ ] **Step 7: 의존성 설치 확인**

Run: `cd /Users/sondaegon/source/python/booking && python3 -m pip install -r requirements.txt`
Expected: 설치 완료, 에러 없음.

- [ ] **Step 8: Commit**

```bash
git add .gitignore requirements.txt pyproject.toml targets.yaml errors.py tests/__init__.py
git commit -m "chore: scaffold ntok seat monitor project"
```

---

### Task 1: 설정 로딩 (config.py)

**Files:**
- Create: `config.py`
- Test: `tests/test_config.py`

**Interfaces:**
- Consumes: `errors.ConfigError`.
- Produces:
  - dataclass `NtokConfig(url: str, id_perf: str, id_time: str, user_id: str, password: str)`
  - dataclass `TelegramConfig(token: str, chat_id: str)`
  - dataclass `Target(floor: str, section: str, rows: list[int], consecutive: int)`
  - dataclass `PollConfig(interval_min: int, interval_max: int)`
  - dataclass `AppConfig(ntok: NtokConfig, telegram: TelegramConfig, targets: list[Target], poll: PollConfig)`
  - `load_config(env_path: str, targets_path: str) -> AppConfig`

- [ ] **Step 1: 실패 테스트 작성 (tests/test_config.py)**

```python
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
    targets = TARGETS_OK.replace("    consecutive: 2\n", "")
    env_path, targets_path = _write(tmp_path, ENV_OK, targets)
    cfg = load_config(env_path, targets_path)
    assert cfg.targets[0].consecutive == 1
```

- [ ] **Step 2: 테스트 실패 확인**

Run: `cd /Users/sondaegon/source/python/booking && python3 -m pytest tests/test_config.py -v`
Expected: FAIL (`ModuleNotFoundError: No module named 'config'`)

- [ ] **Step 3: config.py 구현**

```python
"""설정 로딩: .env(INI) + targets.yaml → AppConfig."""

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
    poll: PollConfig = None


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

    targets: list[Target] = []
    for item in data["targets"]:
        targets.append(
            Target(
                floor=str(item["floor"]),
                section=str(item["section"]),
                rows=[int(r) for r in item["rows"]],
                consecutive=int(item.get("consecutive", 1)),
            )
        )

    poll_raw = data["poll"]
    poll = PollConfig(
        interval_min=int(poll_raw["interval_min"]),
        interval_max=int(poll_raw["interval_max"]),
    )
    return targets, poll
```

- [ ] **Step 4: 테스트 통과 확인**

Run: `cd /Users/sondaegon/source/python/booking && python3 -m pytest tests/test_config.py -v`
Expected: 3개 통과.

- [ ] **Step 5: Commit**

```bash
git add config.py tests/test_config.py
git commit -m "feat: add config loading from .env and targets.yaml"
```

---

### Task 2: 좌석 모델과 연석 매칭 (seats.py)

**Files:**
- Create: `seats.py`
- Test: `tests/test_seats.py`

**Interfaces:**
- Consumes: `config.Target`.
- Produces:
  - `@dataclass(frozen=True) Seat(floor: str, section: str, row: int, number: int, available: bool)`
  - `@dataclass(frozen=True) SeatGroup(floor: str, section: str, row: int, numbers: tuple[int, ...])` with `key() -> tuple` and `label() -> str`
  - `find_available_groups(seats: list[Seat], targets: list[Target]) -> list[SeatGroup]`

- [ ] **Step 1: 실패 테스트 작성 (tests/test_seats.py)**

```python
from config import Target
from seats import Seat, SeatGroup, find_available_groups


def _seat(row, number, available, floor="1F", section="B"):
    return Seat(floor=floor, section=section, row=row, number=number, available=available)


TARGET_2 = Target(floor="1F", section="B", rows=[1, 2], consecutive=2)


def test_finds_two_adjacent_available_seats():
    seats = [_seat(1, 7, True), _seat(1, 8, True), _seat(1, 9, False)]
    groups = find_available_groups(seats, [TARGET_2])
    assert len(groups) == 1
    assert groups[0].numbers == (7, 8)


def test_ignores_non_adjacent_available_seats():
    seats = [_seat(1, 7, True), _seat(1, 12, True)]
    groups = find_available_groups(seats, [TARGET_2])
    assert groups == []


def test_ignores_seats_outside_target_rows_and_section():
    seats = [
        _seat(3, 7, True),  # row 밖
        _seat(1, 7, True, section="A"),  # section 밖
        _seat(1, 8, True, section="A"),
    ]
    groups = find_available_groups(seats, [TARGET_2])
    assert groups == []


def test_maximal_run_returned_as_single_group():
    seats = [_seat(2, 3, True), _seat(2, 4, True), _seat(2, 5, True)]
    groups = find_available_groups(seats, [TARGET_2])
    assert len(groups) == 1
    assert groups[0].numbers == (3, 4, 5)


def test_consecutive_one_allows_singletons():
    target = Target(floor="1F", section="B", rows=[1], consecutive=1)
    seats = [_seat(1, 7, True), _seat(1, 20, True)]
    groups = find_available_groups(seats, [target])
    assert len(groups) == 2


def test_group_key_and_label():
    group = SeatGroup(floor="1F", section="B", row=1, numbers=(7, 8))
    assert group.key() == ("1F", "B", 1, 7, 8)
    assert "1F" in group.label() and "B" in group.label() and "7" in group.label()
```

- [ ] **Step 2: 테스트 실패 확인**

Run: `cd /Users/sondaegon/source/python/booking && python3 -m pytest tests/test_seats.py -v`
Expected: FAIL (`ModuleNotFoundError: No module named 'seats'`)

- [ ] **Step 3: seats.py 구현**

```python
"""좌석 모델과 연석(인접 좌석) 매칭 로직."""

from dataclasses import dataclass

from config import Target


@dataclass(frozen=True)
class Seat:
    floor: str
    section: str
    row: int
    number: int
    available: bool


@dataclass(frozen=True)
class SeatGroup:
    floor: str
    section: str
    row: int
    numbers: tuple[int, ...]

    def key(self) -> tuple:
        """dedupe용 고유 키."""
        return (self.floor, self.section, self.row, self.numbers[0], self.numbers[-1])

    def label(self) -> str:
        """알림용 사람이 읽는 문자열."""
        span = "%d-%d" % (self.numbers[0], self.numbers[-1])
        return "%s %s열 %d행 %s번 (%d연석)" % (
            self.floor,
            self.section,
            self.row,
            span,
            len(self.numbers),
        )


def _runs(numbers: list[int]) -> list[tuple[int, ...]]:
    """정렬된 좌석번호에서 연속 구간(run)들을 뽑는다."""
    if not numbers:
        return []

    runs: list[tuple[int, ...]] = []
    current = [numbers[0]]
    for value in numbers[1:]:
        if value == current[-1] + 1:
            current.append(value)
        else:
            runs.append(tuple(current))
            current = [value]
    runs.append(tuple(current))
    return runs


def find_available_groups(seats: list[Seat], targets: list[Target]) -> list[SeatGroup]:
    """타깃 조건을 만족하는 가용 연석 묶음을 찾는다.

    각 타깃의 (floor, section, rows) 안에서 available 좌석을 열별로 모아
    좌석번호가 연속으로 `consecutive`개 이상 이어지는 최대 구간을 반환한다.
    """
    groups: list[SeatGroup] = []

    for target in targets:
        # 타깃 조건에 맞는 가용 좌석을 열별로 수집
        by_row: dict[int, list[int]] = {}
        for seat in seats:
            matches = (
                seat.available
                and seat.floor == target.floor
                and seat.section == target.section
                and seat.row in target.rows
            )
            if matches:
                by_row.setdefault(seat.row, []).append(seat.number)

        # 열마다 연속 구간을 찾아 consecutive 이상만 채택
        for row, numbers in by_row.items():
            for run in _runs(sorted(numbers)):
                if len(run) >= target.consecutive:
                    groups.append(
                        SeatGroup(
                            floor=target.floor,
                            section=target.section,
                            row=row,
                            numbers=run,
                        )
                    )

    return groups
```

- [ ] **Step 4: 테스트 통과 확인**

Run: `cd /Users/sondaegon/source/python/booking && python3 -m pytest tests/test_seats.py -v`
Expected: 6개 통과.

- [ ] **Step 5: Commit**

```bash
git add seats.py tests/test_seats.py
git commit -m "feat: add seat model and consecutive-seat matching"
```

---

### Task 3: 상태 추적(dedupe) (state.py)

**Files:**
- Create: `state.py`
- Test: `tests/test_state.py`

**Interfaces:**
- Consumes: `seats.SeatGroup`.
- Produces: `SeatState` with `new_groups(current: list[SeatGroup]) -> list[SeatGroup]`.

- [ ] **Step 1: 실패 테스트 작성 (tests/test_state.py)**

```python
from seats import SeatGroup
from state import SeatState


def _group(row, numbers):
    return SeatGroup(floor="1F", section="B", row=row, numbers=numbers)


def test_first_appearance_is_new():
    state = SeatState()
    groups = [_group(1, (7, 8))]
    assert state.new_groups(groups) == groups


def test_same_group_next_round_is_not_new():
    state = SeatState()
    state.new_groups([_group(1, (7, 8))])
    assert state.new_groups([_group(1, (7, 8))]) == []


def test_disappeared_then_reappeared_group_is_new_again():
    state = SeatState()
    state.new_groups([_group(1, (7, 8))])
    state.new_groups([])  # 사라짐
    assert state.new_groups([_group(1, (7, 8))]) == [_group(1, (7, 8))]


def test_only_new_group_reported_when_mixed():
    state = SeatState()
    state.new_groups([_group(1, (7, 8))])
    result = state.new_groups([_group(1, (7, 8)), _group(2, (3, 4))])
    assert result == [_group(2, (3, 4))]
```

- [ ] **Step 2: 테스트 실패 확인**

Run: `cd /Users/sondaegon/source/python/booking && python3 -m pytest tests/test_state.py -v`
Expected: FAIL (`ModuleNotFoundError: No module named 'state'`)

- [ ] **Step 3: state.py 구현**

```python
"""좌석 묶음의 상태 변화를 추적해 신규 항목만 골라낸다."""

from seats import SeatGroup


class SeatState:
    """직전 회차에 살아있던 묶음을 기억해 신규 묶음만 반환한다."""

    def __init__(self) -> None:
        self._alive: set[tuple] = set()

    def new_groups(self, current: list[SeatGroup]) -> list[SeatGroup]:
        """이번 회차에서 직전 대비 새로 나타난 묶음만 반환한다.

        내부 상태를 이번 회차 기준으로 갱신하므로, 사라졌다 다시 나타난
        묶음은 다시 신규로 취급된다.
        """
        current_keys = {group.key() for group in current}
        fresh = [group for group in current if group.key() not in self._alive]
        self._alive = current_keys
        return fresh
```

- [ ] **Step 4: 테스트 통과 확인**

Run: `cd /Users/sondaegon/source/python/booking && python3 -m pytest tests/test_state.py -v`
Expected: 4개 통과.

- [ ] **Step 5: Commit**

```bash
git add state.py tests/test_state.py
git commit -m "feat: add seat-group state dedupe"
```

---

### Task 4: 텔레그램 알림 (notifier.py)

**Files:**
- Create: `notifier.py`
- Test: `tests/test_notifier.py`

**Interfaces:**
- Consumes: `config.TelegramConfig`, `errors.NotifyError`.
- Produces: `send_telegram(cfg: TelegramConfig, text: str) -> None` (실패 시 `NotifyError`).

- [ ] **Step 1: 실패 테스트 작성 (tests/test_notifier.py)**

```python
import pytest

import notifier
from config import TelegramConfig
from errors import NotifyError


class _Resp:
    def __init__(self, ok):
        self.ok = ok
        self.status_code = 200 if ok else 500
        self.text = "" if ok else "error"


def test_send_posts_to_bot_api(monkeypatch):
    captured = {}

    def fake_post(url, data, timeout):
        captured["url"] = url
        captured["data"] = data
        return _Resp(True)

    monkeypatch.setattr(notifier.requests, "post", fake_post)
    send_cfg = TelegramConfig(token="tok123", chat_id="chat456")
    notifier.send_telegram(send_cfg, "hello")

    assert "bottok123/sendMessage" in captured["url"]
    assert captured["data"]["chat_id"] == "chat456"
    assert captured["data"]["text"] == "hello"


def test_send_raises_notifyerror_on_http_failure(monkeypatch):
    monkeypatch.setattr(notifier.requests, "post", lambda url, data, timeout: _Resp(False))
    with pytest.raises(NotifyError):
        notifier.send_telegram(TelegramConfig(token="t", chat_id="c"), "hi")


def test_send_raises_notifyerror_on_network_exception(monkeypatch):
    def boom(url, data, timeout):
        raise notifier.requests.RequestException("network down")

    monkeypatch.setattr(notifier.requests, "post", boom)
    with pytest.raises(NotifyError):
        notifier.send_telegram(TelegramConfig(token="t", chat_id="c"), "hi")
```

- [ ] **Step 2: 테스트 실패 확인**

Run: `cd /Users/sondaegon/source/python/booking && python3 -m pytest tests/test_notifier.py -v`
Expected: FAIL (`ModuleNotFoundError: No module named 'notifier'`)

- [ ] **Step 3: notifier.py 구현**

```python
"""텔레그램 Bot API로 알림을 전송한다."""

import logging

import requests

from config import TelegramConfig
from errors import NotifyError

logger = logging.getLogger(__name__)

_API_TEMPLATE = "https://api.telegram.org/bot%s/sendMessage"


def send_telegram(cfg: TelegramConfig, text: str) -> None:
    """텔레그램으로 메시지를 보낸다.

    Raises:
        NotifyError: HTTP 실패 또는 네트워크 오류.
    """
    url = _API_TEMPLATE % cfg.token
    try:
        resp = requests.post(
            url,
            data={"chat_id": cfg.chat_id, "text": text},
            timeout=10,
        )
    except requests.RequestException as exc:
        raise NotifyError("telegram request failed: %s" % exc) from exc

    if not resp.ok:
        raise NotifyError("telegram returned status %s" % resp.status_code)

    logger.info("Telegram notification sent to chat %s", cfg.chat_id)
```

- [ ] **Step 4: 테스트 통과 확인**

Run: `cd /Users/sondaegon/source/python/booking && python3 -m pytest tests/test_notifier.py -v`
Expected: 3개 통과.

- [ ] **Step 5: Commit**

```bash
git add notifier.py tests/test_notifier.py
git commit -m "feat: add telegram notifier"
```

---

### Task 5: 좌석맵 실측(discovery)

이 태스크는 **실제 페이지를 열어 DOM 구조를 확인**하는 조사 단계다. 자동
테스트 대신 관찰 결과를 문서로 남긴다. 로그인·좌석페이지 진입 흐름과 좌석
가용 판별 규칙이 확정되어야 Task 6을 구현할 수 있다.

**Files:**
- Create: `docs/discovery.md` (관찰 결과 기록)

**전제:** 사용자가 국립극장 계정과 감시 대상 공연(IDPERF/IDTIME)을 알고 있어야 한다.

- [ ] **Step 1: 디버깅 포트로 Chrome 기동 후 수동 로그인**

Run:
```bash
/Applications/Google\ Chrome.app/Contents/MacOS/Google\ Chrome \
  --remote-debugging-port=9222 \
  --user-data-dir="$HOME/source/python/booking/chrome_profile"
```
이 Chrome에서 국립극장에 **수동 로그인**하고, `.env`의 URL+IDPERF+IDTIME에
해당하는 좌석 선택(STEP 02) 페이지까지 직접 이동한다.

- [ ] **Step 2: 로그인 폼 셀렉터 확인**

로그인 페이지에서 개발자도구로 아이디/비밀번호 입력창과 로그인 버튼의
`id`/`name`/CSS 셀렉터를 확인해 `docs/discovery.md`에 기록한다. 캡차 유무도 기록.

- [ ] **Step 3: 좌석맵 컨테이너/iframe 여부 확인**

좌석 선택 페이지에서 좌석맵이 iframe 안에 있는지, 있다면 iframe의
`id`/`name`/`src`를 기록한다. (interpark 사례처럼 iframe일 가능성 있음.)

- [ ] **Step 4: 좌석 엘리먼트 구조·가용 판별 규칙 확인**

개별 좌석 엘리먼트를 조사해 다음을 `docs/discovery.md`에 기록한다:
- 좌석 엘리먼트의 태그·클래스(예: 가용 좌석 vs 매진 좌석 클래스 차이)
- 좌석의 층/구역/열/번호가 어떤 속성(`data-*`, title, id 등)에 담기는지
- "다시조회"/새로고침 트리거 방법(버튼 셀렉터 또는 페이지 reload)

아래 스니펫을 Step 1의 Chrome에 붙어 실행하면 후보 셀렉터를 빠르게 훑을 수 있다:
```python
from selenium import webdriver
from selenium.webdriver.chrome.options import Options

options = Options()
options.add_experimental_option("debuggerAddress", "127.0.0.1:9222")
driver = webdriver.Chrome(options=options)
print("URL:", driver.current_url)
print("IFRAMES:", [(f.get_attribute("id"), f.get_attribute("src")) for f in driver.find_elements("tag name", "iframe")])
# 좌석 후보: 클래스에 seat 포함 엘리먼트 상위 5개의 outerHTML
els = driver.find_elements("css selector", "[class*=seat i], [class*=Seat]")
for el in els[:5]:
    print(el.get_attribute("outerHTML"))
```

- [ ] **Step 5: discovery.md 커밋**

```bash
git add docs/discovery.md
git commit -m "docs: record ntok seat map dom discovery"
```

---

### Task 6: 브라우저 드라이버 (booking_driver.py)

**Files:**
- Create: `booking_driver.py`
- Test: 수동 검증(실제 페이지 대상). 순수 단위테스트는 Task 6b의 파서 분리 함수에 대해서만.

**Interfaces:**
- Consumes: `config.NtokConfig`, `seats.Seat`, `errors.DriverError`, Task 5의 discovery 결과.
- Produces:
  - `class BookingDriver` with:
    - `start() -> None` (Chrome 기동)
    - `login() -> None`
    - `open_seat_page() -> None`
    - `refresh() -> None`
    - `read_available_seats() -> list[Seat]`
    - `is_session_alive() -> bool`
    - `quit() -> None`

**주의:** 아래 셀렉터 상수는 Task 5 `docs/discovery.md`에서 확정한 실제 값으로
반드시 교체한다. 여기 값은 자리표시가 아니라 "discovery 결과로 대체" 지시다.

- [ ] **Step 1: 파서 순수 함수 분리 + 실패 테스트 (tests/test_parser.py)**

DOM 파싱에서 "좌석 식별자 문자열 → Seat" 변환은 순수 함수로 떼어 테스트한다.
discovery에서 좌석 식별자 포맷을 확인한 뒤, 그 실제 포맷에 맞춰 아래 테스트의
입력 문자열과 `parse_seat_token`을 조정한다. (예시는 `"1F-B-1-7:O"` 포맷 가정 —
`O`=가용, `X`=매진.)

```python
from booking_driver import parse_seat_token
from seats import Seat


def test_parse_available_seat_token():
    seat = parse_seat_token("1F-B-1-7:O")
    assert seat == Seat(floor="1F", section="B", row=1, number=7, available=True)


def test_parse_sold_seat_token():
    seat = parse_seat_token("1F-B-1-8:X")
    assert seat.available is False


def test_parse_invalid_token_returns_none():
    assert parse_seat_token("garbage") is None
```

- [ ] **Step 2: 테스트 실패 확인**

Run: `cd /Users/sondaegon/source/python/booking && python3 -m pytest tests/test_parser.py -v`
Expected: FAIL (`ModuleNotFoundError: No module named 'booking_driver'`)

- [ ] **Step 3: booking_driver.py 구현**

discovery 결과에 맞게 상수·셀렉터·`parse_seat_token`·`read_available_seats`를
채운다. 아래는 골격이며, 셀렉터/파싱은 실제 DOM 기준으로 확정한다.

```python
"""국립극장 예매 페이지 Selenium 드라이버."""

import logging

from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait

from config import NtokConfig
from errors import DriverError
from seats import Seat

logger = logging.getLogger(__name__)

# --- discovery.md로 확정할 셀렉터 (실제 값으로 교체) ---
LOGIN_ID_SELECTOR = (By.ID, "REPLACE_login_id")
LOGIN_PW_SELECTOR = (By.ID, "REPLACE_login_pw")
LOGIN_SUBMIT_SELECTOR = (By.CSS_SELECTOR, "REPLACE_login_button")
SEAT_IFRAME_SELECTOR = (By.CSS_SELECTOR, "REPLACE_iframe_or_None")
SEAT_ELEMENT_SELECTOR = (By.CSS_SELECTOR, "REPLACE_seat_css")
REFRESH_SELECTOR = (By.CSS_SELECTOR, "REPLACE_refresh_button")


def parse_seat_token(token: str) -> Seat | None:
    """좌석 식별 문자열을 Seat로 변환한다. 형식 불일치 시 None.

    discovery.md에서 확정한 실제 포맷에 맞춰 파싱 규칙을 조정한다.
    (예시 가정 포맷: "1F-B-1-7:O" — 층-구역-행-번호:가용여부)
    """
    try:
        head, status = token.rsplit(":", 1)
        floor, section, row, number = head.split("-")
        return Seat(
            floor=floor,
            section=section,
            row=int(row),
            number=int(number),
            available=(status.upper() == "O"),
        )
    except (ValueError, AttributeError):
        return None


class BookingDriver:
    """로그인·좌석페이지 진입·좌석맵 파싱을 담당한다."""

    def __init__(self, cfg: NtokConfig) -> None:
        self._cfg = cfg
        self._driver: webdriver.Chrome | None = None
        self._wait: WebDriverWait | None = None

    def start(self) -> None:
        """Chrome을 기동한다."""
        options = Options()
        options.add_argument("--start-maximized")
        self._driver = webdriver.Chrome(options=options)
        self._wait = WebDriverWait(self._driver, 15)
        logger.info("Chrome started")

    def login(self) -> None:
        """`.env` 계정으로 로그인한다."""
        self._require_started()
        try:
            self._driver.get(self._cfg.url)
            self._wait.until(EC.presence_of_element_located(LOGIN_ID_SELECTOR))
            self._driver.find_element(*LOGIN_ID_SELECTOR).send_keys(self._cfg.user_id)
            self._driver.find_element(*LOGIN_PW_SELECTOR).send_keys(self._cfg.password)
            self._driver.find_element(*LOGIN_SUBMIT_SELECTOR).click()
            logger.info("Login submitted for user %s", self._cfg.user_id)
        except Exception as exc:
            raise DriverError("login failed: %s" % exc) from exc

    def open_seat_page(self) -> None:
        """URL+IDPERF+IDTIME 좌석 선택 페이지로 이동한다."""
        self._require_started()
        target = "%s?IdPerf=%s&IdTime=%s" % (
            self._cfg.url,
            self._cfg.id_perf,
            self._cfg.id_time,
        )
        self._driver.get(target)
        logger.info("Opened seat page IdPerf=%s IdTime=%s", self._cfg.id_perf, self._cfg.id_time)

    def refresh(self) -> None:
        """좌석 현황을 갱신한다(다시조회 또는 reload)."""
        self._require_started()
        self._driver.refresh()

    def read_available_seats(self) -> list[Seat]:
        """좌석맵에서 모든 좌석을 읽어 Seat 리스트로 반환한다.

        iframe이 있으면 전환 후 좌석 엘리먼트를 순회하며 discovery에서
        확정한 속성으로 식별 토큰을 만들어 parse_seat_token에 넘긴다.
        """
        self._require_started()
        try:
            self._switch_to_seat_frame()
            elements = self._driver.find_elements(*SEAT_ELEMENT_SELECTOR)
            seats: list[Seat] = []
            for el in elements:
                token = self._element_to_token(el)  # discovery 기준으로 구현
                seat = parse_seat_token(token)
                if seat is not None:
                    seats.append(seat)
            return seats
        except Exception as exc:
            raise DriverError("failed to read seats: %s" % exc) from exc
        finally:
            self._driver.switch_to.default_content()

    def is_session_alive(self) -> bool:
        """로그인 세션이 유효한지(로그인 페이지로 튕기지 않았는지) 확인한다."""
        self._require_started()
        return "login" not in self._driver.current_url.lower()

    def quit(self) -> None:
        """브라우저를 종료한다."""
        if self._driver is not None:
            self._driver.quit()
            self._driver = None

    def _switch_to_seat_frame(self) -> None:
        """좌석맵 iframe으로 전환한다(iframe이 없으면 아무 것도 안 함)."""
        if SEAT_IFRAME_SELECTOR[1] in (None, "REPLACE_iframe_or_None"):
            return
        frame = self._driver.find_element(*SEAT_IFRAME_SELECTOR)
        self._driver.switch_to.frame(frame)

    def _element_to_token(self, element) -> str:
        """좌석 엘리먼트 → 'floor-section-row-number:status' 토큰.

        discovery.md에서 확정한 실제 속성명으로 구현한다.
        """
        raise NotImplementedError("fill from docs/discovery.md")

    def _require_started(self) -> None:
        if self._driver is None or self._wait is None:
            raise DriverError("driver not started; call start() first")
```

- [ ] **Step 4: 파서 테스트 통과 확인 (discovery 포맷 반영 후)**

Run: `cd /Users/sondaegon/source/python/booking && python3 -m pytest tests/test_parser.py -v`
Expected: 3개 통과. (discovery에서 포맷이 다르면 테스트 입력과 파서를 함께 수정)

- [ ] **Step 5: 실제 페이지 수동 검증**

Task 5의 로그인된 상태에서 다음을 임시 스크립트로 실행해 `read_available_seats()`가
실제 가용 좌석을 리스트로 반환하는지 눈으로 확인한다:
```python
import logging
from config import load_config
from booking_driver import BookingDriver

logging.basicConfig(level=logging.INFO)
cfg = load_config(".env", "targets.yaml")
driver = BookingDriver(cfg.ntok)
driver.start(); driver.login(); driver.open_seat_page()
seats = driver.read_available_seats()
print("available:", [s for s in seats if s.available][:20])
driver.quit()
```
Expected: 스크린샷에서 노란칸이던 좌석들이 available=True로 나온다.

- [ ] **Step 6: Commit**

```bash
git add booking_driver.py tests/test_parser.py docs/discovery.md
git commit -m "feat: add ntok booking selenium driver"
```

---

### Task 7: 메인 폴링 루프 (monitor.py)

**Files:**
- Create: `monitor.py`
- Test: `tests/test_monitor.py` (루프 1회 로직을 가짜 드라이버로 검증)

**Interfaces:**
- Consumes: 모든 이전 모듈.
- Produces: `run_once(driver, cfg, state, notify) -> int` (신규 묶음 개수 반환), `main() -> None`.

- [ ] **Step 1: 실패 테스트 작성 (tests/test_monitor.py)**

`run_once`는 드라이버·알림 함수를 주입받아 테스트한다(실제 브라우저·네트워크 없음).

```python
from config import AppConfig, NtokConfig, PollConfig, Target, TelegramConfig
from seats import Seat
from state import SeatState
import monitor


class FakeDriver:
    def __init__(self, seats):
        self._seats = seats
        self.refreshed = False

    def refresh(self):
        self.refreshed = True

    def is_session_alive(self):
        return True

    def read_available_seats(self):
        return self._seats


def _cfg():
    return AppConfig(
        ntok=NtokConfig("u", "1", "2", "id", "pw"),
        telegram=TelegramConfig("t", "c"),
        targets=[Target(floor="1F", section="B", rows=[1], consecutive=2)],
        poll=PollConfig(30, 60),
    )


def test_run_once_notifies_new_group():
    sent = []
    seats = [
        Seat("1F", "B", 1, 7, True),
        Seat("1F", "B", 1, 8, True),
    ]
    driver = FakeDriver(seats)
    count = monitor.run_once(driver, _cfg(), SeatState(), notify=sent.append)
    assert count == 1
    assert driver.refreshed is True
    assert len(sent) == 1
    assert "7-8" in sent[0]


def test_run_once_no_available_does_not_notify():
    sent = []
    driver = FakeDriver([Seat("1F", "B", 1, 7, False)])
    count = monitor.run_once(driver, _cfg(), SeatState(), notify=sent.append)
    assert count == 0
    assert sent == []


def test_run_once_same_group_twice_notifies_once():
    sent = []
    seats = [Seat("1F", "B", 1, 7, True), Seat("1F", "B", 1, 8, True)]
    state = SeatState()
    cfg = _cfg()
    monitor.run_once(FakeDriver(seats), cfg, state, notify=sent.append)
    monitor.run_once(FakeDriver(seats), cfg, state, notify=sent.append)
    assert len(sent) == 1
```

- [ ] **Step 2: 테스트 실패 확인**

Run: `cd /Users/sondaegon/source/python/booking && python3 -m pytest tests/test_monitor.py -v`
Expected: FAIL (`AttributeError: module 'monitor' has no attribute 'run_once'`)

- [ ] **Step 3: monitor.py 구현**

```python
"""국립극장 좌석 모니터 진입점과 폴링 루프."""

import logging
import random
import time
from collections.abc import Callable

from booking_driver import BookingDriver
from config import AppConfig, load_config
from errors import AppBaseError
from notifier import send_telegram
from seats import find_available_groups
from state import SeatState

logger = logging.getLogger(__name__)

ENV_PATH = ".env"
TARGETS_PATH = "targets.yaml"


def run_once(driver, cfg: AppConfig, state: SeatState, notify: Callable[[str], None]) -> int:
    """폴링 1회: 새로고침 → 좌석 수집 → 매칭 → 신규 묶음 알림.

    Returns:
        이번 회차에 알린 신규 묶음 개수.
    """
    driver.refresh()

    if not driver.is_session_alive():
        raise AppBaseError("session expired")

    seats = driver.read_available_seats()
    groups = find_available_groups(seats, cfg.targets)
    fresh = state.new_groups(groups)

    for group in fresh:
        notify("[국립극장] 좌석 발견: %s" % group.label())
        logger.info("New seat group notified: %s", group.label())

    return len(fresh)


def _sleep_with_jitter(cfg: AppConfig) -> None:
    """폴링 간격을 지터를 섞어 대기한다(봇 탐지 완화)."""
    delay = random.uniform(cfg.poll.interval_min, cfg.poll.interval_max)
    logger.debug("Sleeping %.1fs before next poll", delay)
    time.sleep(delay)


def main() -> None:
    """설정 로드 → 로그인 → 좌석페이지 진입 → 무한 폴링."""
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    cfg = load_config(ENV_PATH, TARGETS_PATH)

    driver = BookingDriver(cfg.ntok)
    state = SeatState()

    def notify(text: str) -> None:
        try:
            send_telegram(cfg.telegram, text)
        except AppBaseError as exc:
            logger.error("Notify failed: %s", exc)

    try:
        driver.start()
        driver.login()
        driver.open_seat_page()
        logger.info("Monitor started; polling every %d-%d s", cfg.poll.interval_min, cfg.poll.interval_max)

        while True:
            try:
                run_once(driver, cfg, state, notify)
            except AppBaseError as exc:
                # 세션 만료 등 복구 시도
                logger.warning("Poll error: %s; attempting re-login", exc)
                notify("[국립극장] 모니터 이상: %s (재로그인 시도)" % exc)
                driver.login()
                driver.open_seat_page()

            _sleep_with_jitter(cfg)
    except KeyboardInterrupt:
        logger.info("Interrupted by user")
    finally:
        driver.quit()


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: 테스트 통과 확인**

Run: `cd /Users/sondaegon/source/python/booking && python3 -m pytest tests/test_monitor.py -v`
Expected: 3개 통과.

- [ ] **Step 5: 전체 테스트 실행**

Run: `cd /Users/sondaegon/source/python/booking && python3 -m pytest -v`
Expected: 전 테스트 통과.

- [ ] **Step 6: Commit**

```bash
git add monitor.py tests/test_monitor.py
git commit -m "feat: add polling loop and entrypoint"
```

---

### Task 8: 실제 구동 검증 및 README

**Files:**
- Create: `README.md`

- [ ] **Step 1: 실제 구동 검증**

`.env`와 `targets.yaml`이 채워진 상태에서 실행한다:
```bash
cd /Users/sondaegon/source/python/booking && python3 monitor.py
```
확인 항목:
- 로그인 성공(또는 캡차로 막히면 Task 5 폴백 방식으로 전환 결정)
- 좌석 페이지 진입 로그 출력
- 폴링 주기(30~60초) 대기 로그
- targets.yaml 조건에 맞는 좌석이 있을 때 텔레그램 수신(테스트로 rows/consecutive를 느슨하게 잡아 1건 유도해 알림 도착 확인)

- [ ] **Step 2: README.md 작성**

```markdown
# 국립극장 좌석 모니터

지정한 좌석(층·구역·열·연석 수)이 예매 가능해지면 텔레그램으로 알린다.

## 설정
- `.env` (INI): [NTOK] URL/IDPERF/IDTIME/ID/PASSWORD, [TELEGRAM] TELEGRAM_TOKEN/CHAT_ID
- `targets.yaml`: 감시 좌석 타깃과 폴링 주기(초)

## 실행
    python3 -m pip install -r requirements.txt
    python3 monitor.py

Ctrl+C로 종료. 로그인이 캡차로 막히면 원격 디버깅 포트(9222)로 Chrome을
띄워 수동 로그인 후 붙는 방식으로 전환한다(docs/discovery.md 참고).
```

- [ ] **Step 3: Commit**

```bash
git add README.md
git commit -m "docs: add usage readme"
```

---

## Self-Review

- **스펙 커버리지:** 완전 자동 로그인(Task 6), 좌석맵 파싱(Task 5·6), targets.yaml 설정 파일(Task 1), 연석 수 config(Task 1·2), 30~60초 지터 폴링(Task 7), 상태변화 dedupe(Task 3), 텔레그램 알림(Task 4), 에러 시 재로그인·통지(Task 7) — 모두 태스크로 커버됨.
- **플레이스홀더:** `booking_driver.py`의 `REPLACE_*` 셀렉터와 `_element_to_token`은 자리표시가 아니라 Task 5 discovery 결과로 채우라는 명시적 지시이며, 그 의존 관계를 Task 5→6 순서로 못박음.
- **타입 일관성:** `Seat`, `SeatGroup`, `Target`, `AppConfig` 필드·시그니처가 Task 1·2·3·6·7에서 일치. `find_available_groups`, `new_groups`, `send_telegram`, `run_once` 시그니처가 호출부와 일치.
- **캡차 리스크:** 완전 자동 로그인이 막힐 경우의 폴백(9222 attach)을 Task 5·8·README에 명시.
