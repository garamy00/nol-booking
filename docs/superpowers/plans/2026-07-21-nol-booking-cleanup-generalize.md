# nol-booking 정리·범용화 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 저장소를 NOL 전용으로 정리(NTOK 제거)하고, 인터파크 DOM 상수 중앙화·런타임 상수 `.env` 설정화·Linux Chrome 자동 탐지·패키지 문서화 후 디렉토리를 `nol-booking`으로 리네임한다.

**Architecture:** 국립극장(NTOK) 소스·설정·테스트를 제거해 NOL 모듈만 남긴다. 인터파크 CSS 셀렉터·React fiber JS를 `interpark_dom.py`로 모으고, 디버그 포트·창 크기·세션 마진을 `.env [RUNTIME]`으로 노출한다. 런처는 Linux에서 Chrome/Chromium을 자동 탐지한다.

**Tech Stack:** Python 3.9+(`from __future__ import annotations`), 표준 라이브러리(`configparser`, `shutil`, `os`), `selenium`, `PyYAML`, `requests`, `pytest`, `ruff`.

## Global Constraints

- 런타임 Python 3.9.6 → 새 모듈에 `from __future__ import annotations`, 3.10 전용 런타임 문법 금지.
- 줄 길이 ≤88, `ruff format`/`ruff check`. `logging`만(print 금지), 로그 영문·`%` 포매팅.
- 타입 힌트(public), Google style docstring. 도메인 예외는 `AppBaseError` 상속.
- 리팩터링(Task 2)과 기능 변경(Task 3·4)을 섞지 않는다 — 각 작업 독립.
- 커밋 메시지 `<type>: <요약>`, 끝에 `Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>`.
- Selenium 드라이버는 모니터 스레드만 접근(기존 유지). `.env` 실제 내용은 노출하지 않는다.

---

### Task 1: NTOK(국립극장) 제거 → NOL 전용

**Files:**
- Delete: `monitor.py`, `booking_driver.py`, `seats.py`, `targets.yaml`, `tests/test_config.py`, `tests/test_monitor.py`, `tests/test_seats.py`, `tests/test_parser.py`
- Modify: `config.py` (NTOK 심볼 제거), `state.py` (import 교체)
- Test: `tests/test_state.py` (NolSeatGroup으로 갱신)

**Interfaces:**
- Consumes: `nol_seats.NolSeatGroup(grade, section, row, numbers)` (기존)
- Produces: 없음(제거 작업). `config`에서 `NtokConfig`/`Target`/`AppConfig`/`load_config`/`_load_targets` 사라짐.

- [ ] **Step 1: Rewrite tests/test_state.py to use NolSeatGroup (failing after seats.py 삭제 예정)**

`tests/test_state.py` 전체를 아래로 교체:

```python
from nol_seats import NolSeatGroup
from state import SeatState


def _group(row, numbers):
    return NolSeatGroup(grade="R석", section="B", row=row, numbers=numbers)


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

- [ ] **Step 2: Delete NTOK source + test files**

```bash
git rm monitor.py booking_driver.py seats.py targets.yaml \
  tests/test_config.py tests/test_monitor.py tests/test_seats.py tests/test_parser.py
```

- [ ] **Step 3: Remove NTOK symbols from config.py**

`config.py`에서 삭제: `NtokConfig` 클래스(13-19줄), `Target` 클래스(28-33줄),
`AppConfig` 클래스(42-47줄), `load_config` 함수(88-117줄), `_load_targets` 함수
(120줄부터 `load_nol_config` 정의 직전까지 전체).

유지: `TelegramConfig`, `PollConfig`, `_strip_quotes`, `_require`, `NolConfig`,
`NolTarget`, `NolAppConfig`, `load_nol_config`, `_parse_nol_poll`, `_load_nol_targets`,
`_parse_nol_target`, `_parse_nol_rows`. 모듈 docstring을 `"""설정 로딩: .env(INI) +
nol_targets.yaml → NolAppConfig."""`로 갱신.

- [ ] **Step 4: Update state.py import**

`state.py`에서:
- `from seats import SeatGroup` → `from nol_seats import NolSeatGroup`
- `new_groups(self, current: list[SeatGroup]) -> list[SeatGroup]:` →
  `new_groups(self, current: list[NolSeatGroup]) -> list[NolSeatGroup]:`

- [ ] **Step 5: Run full suite**

Run: `python3 -m pytest -q`
Expected: 전체 통과(삭제된 테스트만큼 감소, NOL 관련 전부 green)

- [ ] **Step 6: Lint + commit**

```bash
ruff check config.py state.py tests/test_state.py
git add -A
git commit -m "refactor: 국립극장(NTOK) 모니터 제거 → NOL 전용 패키지

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 2: 인터파크 DOM 상수 중앙화 (interpark_dom.py)

**Files:**
- Create: `interpark_dom.py`
- Modify: `nol_driver.py`, `nol_seats.py` (인라인 셀렉터·fiber JS를 상수 참조로 교체)
- Test: `tests/test_interpark_dom.py` (상수 존재·형식 스모크)

**Interfaces:**
- Consumes: 없음
- Produces: `interpark_dom` 모듈의 셀렉터·JS 상수(아래 목록).

**주의:** 순수 상수 추출 리팩터링이다. 값은 현재 코드의 리터럴과 **문자 단위로 동일**해야
하며, 기존 nol_driver/nol_seats 테스트가 그대로 통과해야 한다(동작 무변경).

- [ ] **Step 1: Create interpark_dom.py**

`nol_driver.py`의 `_READ_SEATS_JS` 문자열 전체(현재 66-84줄, `const circles ...`)를
`READ_SEATS_JS`라는 이름으로 이 모듈에 그대로 옮긴다. 그리고 셀렉터 상수를 정의:

```python
"""인터파크 NOL 예매창의 DOM 셀렉터·React fiber 스크립트 모음.

인터파크가 프론트엔드 빌드를 바꾸면(클래스 접두어·구조·fiber 키) 이 파일만
갱신하면 된다. 나머지 코드는 여기 상수만 참조한다.
"""

from __future__ import annotations

# 페이지 식별
SEAT_PAGE_MARKER = "onestop/seat"
SEAT_CIRCLE = "circle.js-seat"

# goods 페이지 캘린더
GOODS_DAYS = "ul[data-view='days'] > li"
GOODS_SIDE_TOGGLE = ".sideToggleBtn"
GOODS_MONTH_CURRENT = "li[data-view='month current']"
GOODS_MONTH_NEXT = "li[data-view='month next']"
GOODS_TIME_LABEL = "a.timeTableLabel"
GOODS_BOOK_BUTTON = "a.sideBtn.is-primary"

# 예매창 상단/타이머
SCHEDULE_DATE_QUERY = "[class*=scheduleDate]"
SESSION_TIMER_QUERY = "[class*=SessionDwellTimer]"

# 일정변경 레이어
LAYER_DATE_BUTTON = "button[class*='SubHeader_layerDateButton']"
LAYER_CONTAINER = "[class*='LayerDate_container']"
LAYER_MONTH = "[class*='EntCalendar_month']"
LAYER_SWIPER_ACTIVE = ".swiper-slide-active"
LAYER_DATE_ITEM_BUTTON = "button[class*='EntCalendar_dateButton']"
LAYER_DATE_NUMBER = "span[class*='EntCalendar_number']"
LAYER_TIME_BUTTON = "button[class*='TimeBlock_timeButton']"
LAYER_APPLY_BUTTON = "button[class*='EntButton_primary']"
LAYER_SWIPER_NEXT_ID = "swiperButtonNext"
LAYER_SWIPER_PREV_ID = "swiperButtonPrev"

# 좌석 circle의 React fiber에서 seat 메타데이터를 읽는 스크립트
READ_SEATS_JS = """<현재 nol_driver.py의 _READ_SEATS_JS 값 전체를 그대로>"""
```

(`READ_SEATS_JS`의 실제 본문은 `nol_driver.py` 현재 `_READ_SEATS_JS` 리터럴을 그대로
복사한다.)

- [ ] **Step 2: Write smoke test (fails: module missing)**

`tests/test_interpark_dom.py`:

```python
import interpark_dom


def test_selectors_present_and_nonempty():
    for name in [
        "SEAT_PAGE_MARKER", "SEAT_CIRCLE", "GOODS_DAYS", "GOODS_SIDE_TOGGLE",
        "GOODS_MONTH_CURRENT", "GOODS_MONTH_NEXT", "GOODS_TIME_LABEL",
        "GOODS_BOOK_BUTTON", "SCHEDULE_DATE_QUERY", "SESSION_TIMER_QUERY",
        "LAYER_DATE_BUTTON", "LAYER_CONTAINER", "LAYER_MONTH",
        "LAYER_SWIPER_ACTIVE", "LAYER_DATE_ITEM_BUTTON", "LAYER_DATE_NUMBER",
        "LAYER_TIME_BUTTON", "LAYER_APPLY_BUTTON", "LAYER_SWIPER_NEXT_ID",
        "LAYER_SWIPER_PREV_ID", "READ_SEATS_JS",
    ]:
        value = getattr(interpark_dom, name)
        assert isinstance(value, str) and value


def test_read_seats_js_targets_seat_circle():
    assert "circle.js-seat" in interpark_dom.READ_SEATS_JS
```

Run: `python3 -m pytest tests/test_interpark_dom.py -v` → FAIL(모듈 없음) → Step 1 후 PASS.

- [ ] **Step 3: Replace literals in nol_driver.py with imports**

`nol_driver.py`에서 `import interpark_dom` 추가. 아래 인라인 리터럴을 대응 상수로 교체:
- `SEAT_PAGE_MARKER = "onestop/seat"` 상수 삭제 → `interpark_dom.SEAT_PAGE_MARKER` 사용
  (기존 `SEAT_PAGE_MARKER` 참조 지점 모두 교체).
- `_READ_SEATS_JS` 상수 삭제 → `interpark_dom.READ_SEATS_JS` 사용.
- 각 `By.CSS_SELECTOR, "..."` / `By.ID, "..."` / `querySelector('...')` 리터럴을 위 상수로:
  `"ul[data-view='days'] > li"`→`interpark_dom.GOODS_DAYS`,
  `".sideToggleBtn"`→`GOODS_SIDE_TOGGLE`, `"li[data-view='month current']"`→
  `GOODS_MONTH_CURRENT`, `"li[data-view='month next']"`→`GOODS_MONTH_NEXT`,
  `"a.timeTableLabel"`→`GOODS_TIME_LABEL`, `"a.sideBtn.is-primary"`→`GOODS_BOOK_BUTTON`,
  `[class*=scheduleDate]`→`SCHEDULE_DATE_QUERY`, `[class*=SessionDwellTimer]`→
  `SESSION_TIMER_QUERY`, `button[class*='SubHeader_layerDateButton']`→`LAYER_DATE_BUTTON`,
  `[class*='LayerDate_container']`→`LAYER_CONTAINER`, `[class*='EntCalendar_month']`→
  `LAYER_MONTH`, `.swiper-slide-active`→`LAYER_SWIPER_ACTIVE`,
  `button[class*='EntCalendar_dateButton']`→`LAYER_DATE_ITEM_BUTTON`,
  `span[class*='EntCalendar_number']`→`LAYER_DATE_NUMBER`,
  `button[class*='TimeBlock_timeButton']`→`LAYER_TIME_BUTTON`,
  `button[class*='EntButton_primary']`→`LAYER_APPLY_BUTTON`,
  `"swiperButtonNext"`/`"swiperButtonPrev"`→`LAYER_SWIPER_NEXT_ID`/`LAYER_SWIPER_PREV_ID`,
  `circle.js-seat`(querySelectorAll 및 wait)→`interpark_dom.SEAT_CIRCLE`.
  JS 문자열 안에 박힌 셀렉터(`document.querySelector('[class*=scheduleDate]')` 등)는
  `"... '%s' ..." % interpark_dom.SCHEDULE_DATE_QUERY` 식으로 조립하거나 f-string 없이
  `%` 포매팅으로 삽입한다.

- [ ] **Step 4: Replace literals in nol_seats.py (fiber 파싱이 셀렉터를 쓰면)**

`nol_seats.py`가 DOM 셀렉터 리터럴을 직접 쓰지 않으면(파싱 전용) 변경 없음. 쓰는 리터럴이
있으면 Step 3과 동일 규칙으로 `interpark_dom` 상수로 교체한다.

- [ ] **Step 5: Run full suite + lint**

Run: `python3 -m pytest -q` → 전체 통과(동작 무변경 확인)
Run: `ruff check interpark_dom.py nol_driver.py nol_seats.py tests/test_interpark_dom.py`

- [ ] **Step 6: Commit**

```bash
git add interpark_dom.py nol_driver.py nol_seats.py tests/test_interpark_dom.py
git commit -m "refactor: 인터파크 DOM 셀렉터·fiber 스크립트를 interpark_dom로 중앙화

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 3: 런타임 상수 설정화 (.env [RUNTIME])

**Files:**
- Modify: `config.py` (`RuntimeConfig` + `_load_runtime` + `NolAppConfig.runtime`),
  `nol_monitor.py` (모듈 상수 대신 cfg.runtime), `nol_driver.py` (포트·창 크기 주입),
  `nol_chrome.py` ([RUNTIME] DEBUG_PORT 참조)
- Test: `tests/test_nol_config.py` (RUNTIME 파싱), `tests/test_nol_chrome.py` (포트 override)

**Interfaces:**
- Consumes: `config.NolAppConfig`, `config._require`
- Produces:
  - `config.RuntimeConfig(debug_port: int, window_width: int, window_height: int, safety_seconds: int, max_session_seconds: int, reentry_backoff_seconds: int, failure_alert_threshold: int)`
  - `config.DEFAULT_RUNTIME` (기본값 상수 인스턴스)
  - `NolAppConfig.runtime: RuntimeConfig`

- [ ] **Step 1: Write failing tests**

`tests/test_nol_config.py`에 추가(기존 ENV_OK 상단 상수 활용):

```python
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
```

`tests/test_nol_chrome.py`에 추가:

```python
def test_debug_port_from_env_section(tmp_path, monkeypatch):
    env = tmp_path / ".env"
    env.write_text("[RUNTIME]\nDEBUG_PORT=9444\n")
    assert nol_chrome._read_debug_port(str(env)) == 9444


def test_debug_port_defaults_when_absent(tmp_path):
    env = tmp_path / ".env"
    env.write_text("[NOL]\nURL=https://x\nGOODS_ID=1\n")
    assert nol_chrome._read_debug_port(str(env)) == 9222
```

Run: `python3 -m pytest tests/test_nol_config.py -k runtime tests/test_nol_chrome.py -k debug_port -v` → FAIL.

- [ ] **Step 2: Add RuntimeConfig + loader to config.py**

`NolAppConfig` 정의 위에 추가:

```python
@dataclass
class RuntimeConfig:
    debug_port: int = 9222
    window_width: int = 1440
    window_height: int = 1000
    safety_seconds: int = 40
    max_session_seconds: int = 540
    reentry_backoff_seconds: int = 30
    failure_alert_threshold: int = 5


DEFAULT_RUNTIME = RuntimeConfig()
```

`NolAppConfig`에 필드 추가: `runtime: RuntimeConfig = field(default_factory=RuntimeConfig)`.

`load_nol_config` 안에서 telegram 파싱 다음에:

```python
    runtime = _load_runtime(parser)
    ...
    return NolAppConfig(
        nol=nol, telegram=telegram, targets=targets, poll=poll, runtime=runtime
    )
```

`_load_nol_targets` 아래에 로더 추가:

```python
def _load_runtime(parser: configparser.ConfigParser) -> RuntimeConfig:
    """[RUNTIME] 섹션(모두 선택)을 읽어 RuntimeConfig를 만든다. 없으면 기본값."""
    if "RUNTIME" not in parser:
        return RuntimeConfig()
    sec = parser["RUNTIME"]

    def _int(key: str, default: int) -> int:
        if key not in sec:
            return default
        try:
            return int(_strip_quotes(sec[key]))
        except ValueError as exc:
            raise ConfigError("invalid [RUNTIME] %s: %s" % (key, str(exc))) from exc

    return RuntimeConfig(
        debug_port=_int("DEBUG_PORT", 9222),
        window_width=_int("WINDOW_WIDTH", 1440),
        window_height=_int("WINDOW_HEIGHT", 1000),
        safety_seconds=_int("SAFETY_SECONDS", 40),
        max_session_seconds=_int("MAX_SESSION_SECONDS", 540),
        reentry_backoff_seconds=_int("REENTRY_BACKOFF_SECONDS", 30),
        failure_alert_threshold=_int("FAILURE_ALERT_THRESHOLD", 5),
    )
```

- [ ] **Step 3: Add _read_debug_port to nol_chrome.py and use it**

`nol_chrome.py`에 `_read_goods_url` 아래 추가(같은 최소 파싱 방식):

```python
def _read_debug_port(env_path: str) -> int:
    """`.env` [RUNTIME] DEBUG_PORT를 읽는다. 없으면 기본 9222.

    런처는 전체 설정에 의존하지 않으므로 최소로만 읽는다.
    """
    parser = configparser.ConfigParser(inline_comment_prefixes=("#",))
    parser.read(env_path)
    if "RUNTIME" not in parser or "DEBUG_PORT" not in parser["RUNTIME"]:
        return DEBUG_PORT
    try:
        return int(parser["RUNTIME"]["DEBUG_PORT"].strip())
    except ValueError:
        return DEBUG_PORT
```

`main()`에서 `DEBUG_PORT` 대신 `port = _read_debug_port(ENV_PATH)`를 사용하도록
`is_debugger_up`/`wait_for_debugger`/`_build_launch_args`가 포트를 받게 조정한다:
`is_debugger_up(port: int = DEBUG_PORT)`, `wait_for_debugger(port, timeout=20.0)`,
`_build_launch_args(goods_url, port)`. `main()`이 `port`를 계산해 전달. 기본값 유지로
기존 테스트 호환. (DEBUG_PORT 상수는 기본값으로 유지)

- [ ] **Step 4: Use runtime in nol_monitor.py and nol_driver.py**

`nol_monitor.py`: 모듈 상수 `SAFETY_SECONDS`/`MAX_SESSION_SECONDS`/
`REENTRY_BACKOFF_SECONDS`/`FAILURE_ALERT_THRESHOLD` 참조를 `cfg.runtime.<field>`로 바꾼다
(`_is_session_expiring`·`_run_loop`가 `cfg`/`control`을 이미 받으므로 접근 가능; 필요 시
`cfg.runtime`을 인자로 전달). 모듈 상수는 제거하거나 `config.DEFAULT_RUNTIME` 참조로 대체.
`NolDriver` 생성 시 runtime 전달: `NolDriver(cfg.nol, cfg.runtime)`.

`nol_driver.py`: `NolDriver.__init__(self, cfg, runtime=None)` — runtime 없으면
`config.DEFAULT_RUNTIME`. `DEBUGGER_ADDRESS`를 `"127.0.0.1:%d" % runtime.debug_port`로,
`MIN_DESKTOP_WIDTH/HEIGHT`를 `runtime.window_width/height`로 사용
(`_ensure_desktop_window`, `attach`의 debuggerAddress). 모듈 상수는 기본값으로 유지.

- [ ] **Step 5: Run full suite + lint**

Run: `python3 -m pytest -q` → 전체 통과
Run: `ruff check config.py nol_monitor.py nol_driver.py nol_chrome.py tests/test_nol_config.py tests/test_nol_chrome.py`

- [ ] **Step 6: Commit**

```bash
git add config.py nol_monitor.py nol_driver.py nol_chrome.py tests/test_nol_config.py tests/test_nol_chrome.py
git commit -m "feat: 디버그 포트·창 크기·세션 마진을 .env [RUNTIME]으로 설정화

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 4: Linux Chrome 자동 탐지

**Files:**
- Modify: `nol_chrome.py` (`_chrome_binary`)
- Test: `tests/test_nol_chrome.py`

**Interfaces:**
- Consumes: 없음
- Produces: `nol_chrome._chrome_binary() -> str` (플랫폼별 자동 탐지)

- [ ] **Step 1: Write failing tests**

`tests/test_nol_chrome.py`에 추가:

```python
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
```

Run: `python3 -m pytest tests/test_nol_chrome.py -k chrome_binary -v` → FAIL.

- [ ] **Step 2: Rewrite _chrome_binary in nol_chrome.py**

`import` 블록에 `import shutil`, `import sys` 추가. `_DEFAULT_CHROME_BINARY` 아래에
Linux 후보 목록 추가:

```python
# Linux에서 자동 탐지할 Chrome/Chromium 실행 파일 후보(우선순위 순)
_LINUX_CHROME_CANDIDATES = (
    "google-chrome",
    "google-chrome-stable",
    "chromium",
    "chromium-browser",
)
```

`_chrome_binary`를 교체:

```python
def _chrome_binary() -> str:
    """Chrome 실행 파일 경로를 결정한다.

    NOL_CHROME_BINARY가 있으면 그 값을, 없으면 플랫폼별로 탐지한다. macOS는 기본
    앱 경로, Linux는 google-chrome/chromium 계열을 PATH에서 찾는다.

    Raises:
        LauncherError: Linux에서 후보를 하나도 찾지 못함.
    """
    override = os.environ.get("NOL_CHROME_BINARY")
    if override:
        return override

    if sys.platform == "darwin":
        return _DEFAULT_CHROME_BINARY

    for candidate in _LINUX_CHROME_CANDIDATES:
        path = shutil.which(candidate)
        if path:
            return path
    raise LauncherError(
        "no Chrome/Chromium found; install one or set NOL_CHROME_BINARY"
    )
```

- [ ] **Step 3: Run tests + full suite + lint**

Run: `python3 -m pytest tests/test_nol_chrome.py -v` → PASS
Run: `python3 -m pytest -q` → 전체 통과
Run: `ruff check nol_chrome.py tests/test_nol_chrome.py`

- [ ] **Step 4: Commit**

```bash
git add nol_chrome.py tests/test_nol_chrome.py
git commit -m "feat: Linux Chrome/Chromium 자동 탐지(NOL_CHROME_BINARY 불필요)

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 5: 패키지 완성 (README · .env.example · pyproject)

**Files:**
- Create: `README.md`, `.env.example`
- Modify: `pyproject.toml`
- Test: 없음(문서/메타데이터). `python3 -c "import tomllib; tomllib.load(open('pyproject.toml','rb'))"`로 파싱 검증.

**Interfaces:** 없음.

- [ ] **Step 1: Create .env.example**

```ini
[NOL]
URL=https://tickets.interpark.com/goods
GOODS_ID=00000000
DATE=20260101
TIME=14:00
TOGGLE_DATE=20260108
TOGGLE_TIME=15:00

[TELEGRAM]
TELEGRAM_TOKEN="123456789:your-bot-token"
CHAT_ID="your-chat-id"

[RUNTIME]
# 모두 선택(생략 시 기본값). 필요할 때만 조정.
DEBUG_PORT=9222
WINDOW_WIDTH=1440
WINDOW_HEIGHT=1000
SAFETY_SECONDS=40
MAX_SESSION_SECONDS=540
REENTRY_BACKOFF_SECONDS=30
FAILURE_ALERT_THRESHOLD=5
```

- [ ] **Step 2: Update pyproject.toml**

기존 `[tool.ruff]`/`[tool.pytest.ini_options]`는 유지하고 상단에 추가:

```toml
[project]
name = "nol-booking"
version = "0.1.0"
description = "인터파크 NOL 좌석 모니터 — 목표 좌석 발견 시 Telegram 알림"
requires-python = ">=3.9"
dependencies = [
    "selenium>=4.20",
    "PyYAML>=6.0",
    "requests>=2.31",
]

[project.optional-dependencies]
dev = ["pytest>=8.0", "ruff>=0.5"]
```

- [ ] **Step 3: Create README.md**

아래 내용으로 작성(섹션: 소개 / 요구사항 / 설치 / 설정 / 최초 로그인 / 실행 / 제어 명령 / 아키텍처 / 한계·책임):

```markdown
# nol-booking

인터파크 NOL 예매창의 좌석을 폴링해, 목표 조건(등급·연석·구역·열)에 맞는 좌석이
나타나면 Telegram으로 알린다. **알림 전용**이며 자동 결제는 하지 않는다.

## 요구사항
- Python 3.9+
- Google Chrome 또는 Chromium
- Telegram 봇 토큰·chat_id

## 설치
```
python3 -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt
```

## 설정
1. `.env.example`을 `.env`로 복사해 `[NOL]`·`[TELEGRAM]`을 채운다. `[RUNTIME]`은 선택.
2. `nol_targets.yaml`에 감시할 좌석 조건(등급/연석 등)을 적는다.

## 최초 로그인 (attach 모델)
이 도구는 **이미 로그인된 Chrome에 attach**한다. 새 창을 띄우거나 자동 로그인하지 않는다.
```
python3 nol_chrome.py        # 디버그 포트로 Chrome 실행 + NOL 페이지 열기
# 열린 Chrome에서 인터파크에 직접 로그인 (프로필은 chrome_profile에 영속)
```
Linux는 `NOL_CHROME_BINARY` 없이 chromium을 자동 탐지한다. 필요 시 지정 가능.

## 실행
```
python3 nol_monitor.py       # attach → 폴링 → 좌석 발견 시 Telegram 알림
```
종료: Ctrl-C / SIGTERM / Telegram `/stop`. 중복 실행은 자동 차단(단일 인스턴스 잠금).

## Telegram 제어 명령
- `/status` — 목표 회차·상태·연속 실패·마지막 성공
- `/pause` · `/resume` — 폴링 일시정지/재개
- `/stop` — 원격 종료

## 아키텍처
- `nol_chrome.py` — Chrome 런처(+`stop`)
- `nol_monitor.py` — 진입점·상태머신(메인 스레드, 드라이버 소유)
- `nol_driver.py` — 예매창 네비게이션(attach)
- `nol_seats.py` — React fiber 좌석 파싱·매칭
- `interpark_dom.py` — 인터파크 셀렉터·스크립트(빌드 변경 시 여기만 수정)
- `control.py` / `telegram_control.py` — 제어 상태·봇 수신(daemon 스레드)
- `config.py` / `notifier.py` — 설정 로딩 / Telegram 알림

## 한계·책임
- 인터파크 DOM에 의존하므로 사이트 변경 시 셀렉터 갱신이 필요하다.
- 최초 로그인은 수동이다.
- 상용 사이트 자동화 도구다. **사이트 약관 준수와 사용 결과는 사용자 책임**이며,
  이 프로젝트는 알림 목적의 예시로 제공된다.
```

- [ ] **Step 4: Verify pyproject parses + commit**

Run: `python3 -c "import tomllib; tomllib.load(open('pyproject.toml','rb'))"` (Python 3.11+) 또는 `ruff check .`로 전체 이상 없음 확인.
Run: `python3 -m pytest -q` → 전체 통과(영향 없음 확인)

```bash
git add README.md .env.example pyproject.toml
git commit -m "docs: README·.env.example·pyproject 메타데이터 추가

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 6: 디렉토리 리네임 booking → nol-booking

**Files:** 없음(파일시스템 이동). 코드 변경 없음.

**Interfaces:** 없음.

- [ ] **Step 1: 실제 .env에서 [NTOK] 제거 (가능한 경우)**

실제 `.env`를 열어 `[NTOK]` 섹션을 제거한다. `[NOL]`·`[TELEGRAM]`은 유지, `[RUNTIME]`은
선택. 접근이 막히면 사용자에게 "`.env`의 `[NTOK]` 섹션을 직접 제거하라"고 안내한다.
(`.env`는 gitignore라 커밋 대상 아님)

- [ ] **Step 2: 최종 전체 검증**

Run: `python3 -m pytest -q` → 전체 통과
Run: `ruff check .` → clean

- [ ] **Step 3: 디렉토리 이동**

```bash
cd ~/source/python
mv booking nol-booking
cd nol-booking
git status   # 리포 정상 인식 확인(폴더명은 git 추적 대상 아님)
```

- [ ] **Step 4: 이동 후 재검증 + 커밋(변경 있으면)**

Run: `python3 -m pytest -q` (새 경로에서) → 전체 통과
디렉토리 이동은 git 변경을 만들지 않으므로 별도 커밋 불필요. 코드 변경이 있었다면 커밋.

---

## Self-Review

**Spec coverage:**
- NTOK 제거(파일·config·state·테스트) → Task 1. ✅
- 인터파크 DOM 상수 중앙화 → Task 2(색상 상수는 코드에 없음 → 셀렉터·fiber JS 중앙화로 반영). ✅
- 런타임 상수 `.env [RUNTIME]` 설정화(포트·창·마진) → Task 3. ✅
- Linux Chrome 자동 탐지 → Task 4. ✅
- README·.env.example·pyproject → Task 5. ✅
- 디렉토리 리네임 + 실제 .env [NTOK] 제거 → Task 6. ✅

**Placeholder scan:** Task 2의 `READ_SEATS_JS` 본문은 "현재 _READ_SEATS_JS 값 그대로 복사"로
명시(리터럴 이동). 그 외 TBD/추상 지시 없음. 모든 코드 스텝에 실제 코드 포함. ✅

**Type consistency:** `RuntimeConfig` 필드명(debug_port/window_width/window_height/
safety_seconds/max_session_seconds/reentry_backoff_seconds/failure_alert_threshold)이
Task 3의 config·nol_monitor·nol_driver 사용에서 일관. `interpark_dom` 상수명이 Task 2
정의·교체·테스트에서 일치. `_read_debug_port`/`_chrome_binary` 시그니처가 Task 3·4와
테스트에서 일관. ✅
