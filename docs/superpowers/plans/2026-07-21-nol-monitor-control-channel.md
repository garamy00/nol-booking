# NOL 모니터 운영 하드닝 + Telegram 제어 채널 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** SIGTERM/SIGINT graceful 종료·단일 인스턴스 잠금과 Telegram `/status`·`/pause`·`/resume`·`/stop` 제어 채널을 추가한다.

**Architecture:** 모니터 루프는 메인 스레드(Selenium 드라이버 단독 소유), 봇 수신 루프는 daemon 스레드. 두 스레드는 스레드 안전한 `ControlState`로만 통신한다. 봇 수신은 `requests` getUpdates 롱폴링으로 구현(새 의존성 없음).

**Tech Stack:** Python 3.9+ (`from __future__ import annotations` 필수), 표준 라이브러리(`threading`, `signal`, `fcntl`, `time`, `dataclasses`), `requests`, `pytest`.

## Global Constraints

- 런타임 Python 3.9.6 → 새 모듈에 `from __future__ import annotations` 필수, 3.10 전용 런타임 문법 금지(`X | None` 애노테이션은 stringized라 허용).
- 줄 길이 ≤88, `ruff format`/`ruff check`. `logging`만 사용(print 금지), 로그는 영문·`%` 포매팅.
- 텔레그램 사용자 응답 텍스트는 한국어(기존 알림과 일관).
- 도메인 예외는 `AppBaseError` 상속. 타입 힌트·Google style docstring(public).
- Selenium 드라이버는 모니터 스레드에서만 접근. 봇 스레드는 `ControlState` 플래그/상태만 조작.
- fcntl 사용(Mac·Linux 대상, Windows 비대상). 테스트는 실동작 검증 우선.
- 커밋 메시지 `<type>: <요약>`, 끝에 `Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>`.

---

### Task 1: control.py — ControlState + ControlSnapshot

**Files:**
- Create: `control.py`
- Test: `tests/test_control.py`

**Interfaces:**
- Consumes: 없음
- Produces:
  - `control.ControlSnapshot` (dataclass): `target_date: str`, `target_time: str`, `state: str`, `consecutive_failures: int`, `last_success_ts: float | None`, `started_ts: float`
  - `control.ControlState(target_date: str, target_time: str)` with: `request_stop()`, `should_stop() -> bool`, `pause()`, `resume()`, `is_paused() -> bool`, `wait_if_paused(poll: float = 0.5) -> None`, `set_state(state: str) -> None`, `mark_success() -> None`, `mark_failure() -> int`, `snapshot() -> ControlSnapshot`

- [ ] **Step 1: Write the failing test**

`tests/test_control.py`:

```python
import threading
import time

from control import ControlState


def test_stop_flag_set_and_read():
    c = ControlState("20260802", "14:00")
    assert c.should_stop() is False
    c.request_stop()
    assert c.should_stop() is True


def test_pause_resume_toggles_flag_and_state():
    c = ControlState("20260802", "14:00")
    c.pause()
    assert c.is_paused() is True
    assert c.snapshot().state == "paused"
    c.resume()
    assert c.is_paused() is False
    assert c.snapshot().state == "polling"


def test_wait_if_paused_returns_immediately_when_not_paused():
    c = ControlState("20260802", "14:00")
    c.wait_if_paused(poll=0.01)  # 멈추지 않고 반환해야 한다


def test_wait_if_paused_returns_when_stop_even_if_paused():
    c = ControlState("20260802", "14:00")
    c.pause()
    c.request_stop()
    c.wait_if_paused(poll=0.01)  # stop이면 일시정지여도 즉시 반환


def test_wait_if_paused_unblocks_after_resume():
    c = ControlState("20260802", "14:00")
    c.pause()
    result = {"returned": False}

    def waiter():
        c.wait_if_paused(poll=0.01)
        result["returned"] = True

    t = threading.Thread(target=waiter)
    t.start()
    time.sleep(0.05)
    assert result["returned"] is False  # 아직 일시정지
    c.resume()
    t.join(timeout=1.0)
    assert result["returned"] is True


def test_mark_failure_accumulates_and_success_resets():
    c = ControlState("20260802", "14:00")
    assert c.mark_failure() == 1
    assert c.mark_failure() == 2
    assert c.snapshot().consecutive_failures == 2
    c.mark_success()
    assert c.snapshot().consecutive_failures == 0
    assert c.snapshot().last_success_ts is not None


def test_snapshot_reflects_target_and_state():
    c = ControlState("20260802", "14:00")
    snap = c.snapshot()
    assert snap.target_date == "20260802"
    assert snap.target_time == "14:00"
    assert snap.state == "entering"
    assert snap.last_success_ts is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/test_control.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'control'`

- [ ] **Step 3: Write control.py**

```python
"""모니터 스레드와 봇 스레드가 공유하는 스레드 안전 제어·상태 객체."""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass


@dataclass
class ControlSnapshot:
    """/status 표시용 상태 사본."""

    target_date: str
    target_time: str
    state: str
    consecutive_failures: int
    last_success_ts: float | None
    started_ts: float


class ControlState:
    """pause/stop 이벤트와 상태 스냅샷을 스레드 안전하게 관리한다.

    stop/paused는 threading.Event로, 상태 필드는 Lock으로 보호한다. 드라이버는
    이 객체를 통해 간접적으로만 제어되며 봇 스레드가 직접 만지지 않는다.
    """

    def __init__(self, target_date: str, target_time: str) -> None:
        self._stop = threading.Event()
        self._paused = threading.Event()
        self._lock = threading.Lock()
        self._target_date = target_date
        self._target_time = target_time
        self._state = "entering"
        self._consecutive_failures = 0
        self._last_success_ts: float | None = None
        self._started_ts = time.time()

    def request_stop(self) -> None:
        """종료를 요청한다."""
        self._stop.set()

    def should_stop(self) -> bool:
        """종료 요청 여부."""
        return self._stop.is_set()

    def pause(self) -> None:
        """폴링을 일시정지한다."""
        self._paused.set()
        self.set_state("paused")

    def resume(self) -> None:
        """폴링을 재개한다."""
        self._paused.clear()
        self.set_state("polling")

    def is_paused(self) -> bool:
        """일시정지 여부."""
        return self._paused.is_set()

    def wait_if_paused(self, poll: float = 0.5) -> None:
        """일시정지 동안 대기하되 종료 요청이면 즉시 반환한다."""
        while self._paused.is_set() and not self._stop.is_set():
            time.sleep(poll)

    def set_state(self, state: str) -> None:
        """표시용 상태 문자열을 설정한다(entering/polling/paused/holding)."""
        with self._lock:
            self._state = state

    def mark_success(self) -> None:
        """마지막 성공 시각을 갱신하고 연속 실패 수를 0으로 되돌린다."""
        with self._lock:
            self._last_success_ts = time.time()
            self._consecutive_failures = 0

    def mark_failure(self) -> int:
        """연속 실패 수를 증가시키고 증가 후 값을 반환한다."""
        with self._lock:
            self._consecutive_failures += 1
            return self._consecutive_failures

    def snapshot(self) -> ControlSnapshot:
        """현재 상태의 사본을 반환한다."""
        with self._lock:
            return ControlSnapshot(
                target_date=self._target_date,
                target_time=self._target_time,
                state=self._state,
                consecutive_failures=self._consecutive_failures,
                last_success_ts=self._last_success_ts,
                started_ts=self._started_ts,
            )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m pytest tests/test_control.py -v`
Expected: PASS (7 passed)

- [ ] **Step 5: Commit**

```bash
git add control.py tests/test_control.py
git commit -m "feat: 스레드 안전 ControlState(제어 이벤트·상태 스냅샷) 추가

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 2: 단일 인스턴스 잠금 (nol_monitor.acquire_single_instance_lock)

**Files:**
- Modify: `nol_monitor.py` (import 추가 + 상수 + 함수)
- Test: `tests/test_single_instance.py`

**Interfaces:**
- Consumes: 없음
- Produces:
  - `nol_monitor.LOCK_PATH: str`
  - `nol_monitor.acquire_single_instance_lock(lock_path: str = LOCK_PATH)` — 잠금 획득 시 열린 파일 객체 반환, 이미 잠겨 있으면 `None`.

- [ ] **Step 1: Write the failing test**

`tests/test_single_instance.py`:

```python
import nol_monitor


def test_second_acquire_on_same_path_returns_none(tmp_path):
    lock_path = str(tmp_path / ".nol_monitor.lock")

    first = nol_monitor.acquire_single_instance_lock(lock_path)
    assert first is not None

    second = nol_monitor.acquire_single_instance_lock(lock_path)
    assert second is None  # 이미 잠겨 있으면 None

    first.close()

    # 해제 후에는 다시 획득 가능해야 한다
    third = nol_monitor.acquire_single_instance_lock(lock_path)
    assert third is not None
    third.close()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/test_single_instance.py -v`
Expected: FAIL — `AttributeError: module 'nol_monitor' has no attribute 'acquire_single_instance_lock'`

- [ ] **Step 3: Add imports, constant, and function to nol_monitor.py**

`import` 블록(파일 상단, 기존 `import time` 인근)에 추가:

```python
import fcntl
import os
```

`NOL_TARGETS_PATH = "nol_targets.yaml"` 아래(상수 영역)에 추가:

```python
# 단일 인스턴스 잠금 파일(스크립트 위치 기준). 중복 실행 시 두 번째는 종료.
LOCK_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".nol_monitor.lock")
```

`main()` 정의 위에 함수 추가:

```python
def acquire_single_instance_lock(lock_path: str = LOCK_PATH):
    """단일 인스턴스 잠금을 시도한다.

    fcntl.flock(비블로킹)으로 배타 잠금을 잡는다. 이미 다른 인스턴스가 잡았으면
    None을 반환한다. 반환된 파일 객체는 프로세스 수명 동안 열어 두어야 잠금이
    유지된다(닫으면 해제).
    """
    lock_file = open(lock_path, "w")
    try:
        fcntl.flock(lock_file, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        lock_file.close()
        return None
    return lock_file
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m pytest tests/test_single_instance.py -v`
Expected: PASS (1 passed)

- [ ] **Step 5: Commit**

```bash
git add nol_monitor.py tests/test_single_instance.py
git commit -m "feat: nol_monitor 단일 인스턴스 잠금(fcntl) 추가

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 3: telegram_control.py — 명령 수신·디스패치

**Files:**
- Create: `telegram_control.py`
- Test: `tests/test_telegram_control.py`

**Interfaces:**
- Consumes: `control.ControlState`, `control.ControlSnapshot`, `config.TelegramConfig`
- Produces:
  - `telegram_control.format_status(snap: ControlSnapshot) -> str`
  - `telegram_control.dispatch(command: str, control: ControlState) -> str`
  - `telegram_control._extract_command(update: dict) -> tuple[str | None, object]`
  - `telegram_control.handle_update(update: dict, cfg: TelegramConfig, control: ControlState, send) -> None` (`send` is `Callable[[object, str], None]`)
  - `telegram_control.serve(cfg: TelegramConfig, control: ControlState) -> None`

- [ ] **Step 1: Write the failing test**

`tests/test_telegram_control.py`:

```python
from config import TelegramConfig
from control import ControlState
import telegram_control


def _cfg():
    return TelegramConfig(token="tok", chat_id="42")


def test_dispatch_status_includes_target_and_state():
    control = ControlState("20260802", "14:00")
    reply = telegram_control.dispatch("/status", control)
    assert "20260802" in reply
    assert "14:00" in reply


def test_dispatch_pause_and_resume_change_control():
    control = ControlState("20260802", "14:00")
    assert telegram_control.dispatch("/pause", control) == "일시정지됨"
    assert control.is_paused() is True
    assert telegram_control.dispatch("/resume", control) == "재개됨"
    assert control.is_paused() is False


def test_dispatch_stop_requests_stop():
    control = ControlState("20260802", "14:00")
    assert telegram_control.dispatch("/stop", control) == "종료합니다"
    assert control.should_stop() is True


def test_dispatch_unknown_returns_usage():
    control = ControlState("20260802", "14:00")
    reply = telegram_control.dispatch("/foo", control)
    assert "/status" in reply


def test_extract_command_reads_text_and_chat_id():
    update = {"update_id": 1, "message": {"text": "/status", "chat": {"id": 42}}}
    text, chat_id = telegram_control._extract_command(update)
    assert text == "/status"
    assert chat_id == 42


def test_extract_command_ignores_non_command_and_empty():
    assert telegram_control._extract_command({"update_id": 1}) == (None, None)
    plain = {"update_id": 2, "message": {"text": "hi", "chat": {"id": 42}}}
    assert telegram_control._extract_command(plain) == (None, None)


def test_handle_update_authorized_dispatches_and_replies():
    control = ControlState("20260802", "14:00")
    sent = []
    update = {"update_id": 1, "message": {"text": "/pause", "chat": {"id": 42}}}
    telegram_control.handle_update(update, _cfg(), control, lambda cid, t: sent.append((cid, t)))
    assert control.is_paused() is True
    assert sent == [(42, "일시정지됨")]


def test_handle_update_unauthorized_chat_ignored():
    control = ControlState("20260802", "14:00")
    sent = []
    update = {"update_id": 1, "message": {"text": "/stop", "chat": {"id": 999}}}
    telegram_control.handle_update(update, _cfg(), control, lambda cid, t: sent.append((cid, t)))
    assert control.should_stop() is False  # 인가되지 않음 → 무시
    assert sent == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/test_telegram_control.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'telegram_control'`

- [ ] **Step 3: Write telegram_control.py**

```python
"""Telegram getUpdates 롱폴링으로 제어 명령을 수신·처리한다(daemon 스레드).

봇 스레드는 ControlState의 플래그/상태만 조작하고 Selenium 드라이버는 만지지
않는다. 설정된 chat_id의 명령만 처리한다(인가).
"""

from __future__ import annotations

import logging
import time
from typing import Callable

import requests

from config import TelegramConfig
from control import ControlSnapshot, ControlState

logger = logging.getLogger(__name__)

_API = "https://api.telegram.org/bot%s/%s"

# getUpdates 롱폴링 대기(초). 이 값만큼 봇 응답이 늦어질 수 있으나 daemon이라
# 프로세스 종료 자체는 지연되지 않는다.
_LONG_POLL_SEC = 20

_USAGE = "사용법: /status /pause /resume /stop"

_STATE_KR = {
    "entering": "진입 중",
    "polling": "폴링 중",
    "paused": "일시정지",
    "holding": "홀드(좌석 발견)",
}


def format_status(snap: ControlSnapshot) -> str:
    """스냅샷을 /status 응답 텍스트로 만든다."""
    state_kr = _STATE_KR.get(snap.state, snap.state)
    if snap.last_success_ts is None:
        last = "-"
    else:
        last = time.strftime("%H:%M:%S", time.localtime(snap.last_success_ts))
    return (
        "[NOL 상태]\n"
        "목표: %s %s\n"
        "상태: %s\n"
        "연속 실패: %d\n"
        "마지막 성공: %s"
        % (
            snap.target_date,
            snap.target_time,
            state_kr,
            snap.consecutive_failures,
            last,
        )
    )


def dispatch(command: str, control: ControlState) -> str:
    """명령을 처리하고 응답 텍스트를 반환한다(순수 함수)."""
    cmd = command.split()[0].lower() if command.strip() else ""
    if cmd == "/status":
        return format_status(control.snapshot())
    if cmd == "/pause":
        control.pause()
        return "일시정지됨"
    if cmd == "/resume":
        control.resume()
        return "재개됨"
    if cmd == "/stop":
        control.request_stop()
        return "종료합니다"
    return _USAGE


def _extract_command(update: dict):
    """update에서 (명령 텍스트, chat_id)를 뽑는다. 명령이 아니면 (None, None)."""
    message = update.get("message") or update.get("edited_message")
    if not message:
        return None, None
    text = message.get("text", "")
    if not text.startswith("/"):
        return None, None
    chat_id = (message.get("chat") or {}).get("id")
    return text, chat_id


def handle_update(
    update: dict,
    cfg: TelegramConfig,
    control: ControlState,
    send: Callable[[object, str], None],
) -> None:
    """update 하나를 처리한다: 추출 → 인가 → 디스패치 → 응답.

    설정된 chat_id가 아니면 무시한다(응답도 하지 않는다).
    """
    text, chat_id = _extract_command(update)
    if text is None:
        return
    if str(chat_id) != str(cfg.chat_id):
        logger.warning("ignoring command from unauthorized chat %s", chat_id)
        return
    send(chat_id, dispatch(text, control))


def _get_updates(token: str, offset: int | None) -> list:
    """getUpdates 롱폴링으로 새 업데이트 목록을 가져온다."""
    params: dict = {"timeout": _LONG_POLL_SEC}
    if offset is not None:
        params["offset"] = offset
    resp = requests.get(
        _API % (token, "getUpdates"), params=params, timeout=_LONG_POLL_SEC + 10
    )
    resp.raise_for_status()
    return resp.json().get("result", [])


def _send_reply(token: str, chat_id: object, text: str) -> None:
    """명령 응답을 전송한다(실패는 로깅만)."""
    try:
        requests.post(
            _API % (token, "sendMessage"),
            data={"chat_id": chat_id, "text": text},
            timeout=10,
        )
    except requests.RequestException as exc:
        logger.warning("reply send failed: %s", type(exc).__name__)


def serve(cfg: TelegramConfig, control: ControlState) -> None:
    """제어 명령을 처리하는 롱폴링 루프(daemon 스레드 진입점)."""
    offset: int | None = None

    def send(chat_id: object, text: str) -> None:
        _send_reply(cfg.token, chat_id, text)

    logger.info("Telegram control channel started")
    while not control.should_stop():
        try:
            updates = _get_updates(cfg.token, offset)
        except requests.RequestException as exc:
            logger.warning("getUpdates failed: %s", type(exc).__name__)
            time.sleep(3)
            continue
        for update in updates:
            offset = update["update_id"] + 1
            handle_update(update, cfg, control, send)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m pytest tests/test_telegram_control.py -v`
Expected: PASS (8 passed)

- [ ] **Step 5: Commit**

```bash
git add telegram_control.py tests/test_telegram_control.py
git commit -m "feat: Telegram 제어 명령 수신(getUpdates 롱폴링)·디스패치 추가

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 4: nol_monitor 배선 (control·시그널·봇 스레드·루프 통합)

**Files:**
- Modify: `nol_monitor.py` (`_run_loop`, `_poll_until_hold_or_expiry`, `main`, 시그널 핸들러 팩토리, import)
- Test: `tests/test_nol_driver.py` (기존 run_loop 테스트 갱신 + stop-exit·signal 테스트 추가)

**Interfaces:**
- Consumes: `control.ControlState`, `telegram_control.serve`, `nol_monitor.acquire_single_instance_lock`
- Produces:
  - `nol_monitor._request_stop_on_signal(control: ControlState)` → `Callable[[int, object], None]`
  - 변경된 시그니처: `_run_loop(driver, cfg, state, notify, control)`,
    `_poll_until_hold_or_expiry(driver, cfg, state, notify, control) -> bool`

- [ ] **Step 1: Update existing run_loop tests + add stop/signal tests (failing)**

`tests/test_nol_driver.py`에서 기존 `_collect_run_loop_notifications` 헬퍼와 두 run_loop 테스트를 아래로 교체하고, stop·signal 테스트를 추가한다.

먼저 상단 import에 추가:

```python
from control import ControlState
```

`_collect_run_loop_notifications`를 교체:

```python
def _collect_run_loop_notifications(driver, monkeypatch) -> list[str]:
    sent: list[str] = []
    control = ControlState("20260802", "14:00")
    # 진입 성공 즉시 홀드로 처리해 바깥 루프를 종료시킨다
    monkeypatch.setattr(nol_monitor, "_poll_until_hold_or_expiry", lambda *a: True)
    monkeypatch.setattr(nol_monitor.time, "sleep", lambda _s: None)
    nol_monitor._run_loop(driver, _cfg(), SeatState(), sent.append, control)
    return sent
```

(두 기존 테스트 `test_run_loop_stays_silent_on_transient_failures`,
`test_run_loop_alerts_once_then_recovers_on_sustained_failure`는 본문 변경 없이 그대로
둔다 — 헬퍼 시그니처만 바뀐다.)

그리고 아래 두 테스트를 추가:

```python
def test_run_loop_exits_immediately_when_stop_requested(monkeypatch):
    # stop이 이미 요청되면 진입을 시도하지 않고 즉시 반환한다
    calls = {"enter": 0}

    class _Driver:
        def enter_booking(self):
            calls["enter"] += 1

        def reenter(self):
            calls["enter"] += 1

    control = ControlState("20260802", "14:00")
    control.request_stop()
    nol_monitor._run_loop(_Driver(), _cfg(), SeatState(), lambda _t: None, control)
    assert calls["enter"] == 0


def test_signal_handler_requests_stop():
    control = ControlState("20260802", "14:00")
    handler = nol_monitor._request_stop_on_signal(control)
    handler(15, None)
    assert control.should_stop() is True
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -m pytest tests/test_nol_driver.py -k "run_loop or signal_handler" -v`
Expected: FAIL — `_run_loop`가 `control` 인자를 받지 않음 / `_request_stop_on_signal` 없음

- [ ] **Step 3: Rewrite _run_loop and _poll_until_hold_or_expiry to take control**

`_poll_until_hold_or_expiry`를 아래로 교체:

```python
def _poll_until_hold_or_expiry(
    driver, cfg: NolAppConfig, state: SeatState, notify: Callable[[str], None], control
) -> bool:
    """안쪽 루프: 세션 만료 전까지 좌석 확인 → 없으면 토글 리로드 후 재시도.

    Returns:
        True면 타깃 좌석을 찾아 홀드해야 함. False면 세션 만료·유실·종료로 재진입/종료.
    """
    session_start = time.monotonic()
    while not control.should_stop():
        control.wait_if_paused()
        if control.should_stop():
            return False
        if _is_session_expiring(driver, session_start):
            return False

        try:
            fresh = check_once(driver, cfg, state, notify)
            if fresh:
                logger.info("HOLD: target seat found, monitor paused on seat page")
                return True
            driver.reload_target()
        except DriverError as exc:
            logger.warning(
                "Seat check/reload failed (%s); assuming session lost, re-entering",
                type(exc).__name__,
            )
            return False

        control.mark_success()
        _sleep_with_jitter(cfg)

    return False
```

`_run_loop`를 아래로 교체:

```python
def _run_loop(
    driver, cfg: NolAppConfig, state: SeatState, notify: Callable[[str], None], control
) -> None:
    """바깥 루프: 예매창 (재)진입 → 안쪽 폴링. 타깃 발견 또는 종료 요청 시 반환한다."""
    first = True
    while not control.should_stop():
        control.wait_if_paused()
        if control.should_stop():
            return
        control.set_state("entering")

        # 첫 진입은 enter_booking, 이후엔 goods로 되돌아가 새 세션으로 재진입
        try:
            if first:
                driver.enter_booking()
                first = False
            else:
                driver.reenter()
        except DriverError as exc:
            count = control.mark_failure()
            logger.error(
                "Booking entry failed (%s); attempt %d, retrying in %ds",
                exc,
                count,
                REENTRY_BACKOFF_SECONDS,
            )
            # 자가복구되는 일시적 실패는 알리지 않고, 임계 도달 시 한 번만 알린다
            if count == FAILURE_ALERT_THRESHOLD:
                notify(
                    "[NOL] 예매창 진입이 %d회 연속 실패했습니다 (확인 필요)" % count
                )
            time.sleep(REENTRY_BACKOFF_SECONDS)
            continue

        # 진입 성공: 지속 장애를 알렸던 경우에만 복구 알림 후 카운터 초기화
        if control.snapshot().consecutive_failures >= FAILURE_ALERT_THRESHOLD:
            notify("[NOL] 예매창 진입 복구됨")
        control.mark_success()
        control.set_state("polling")

        held = _poll_until_hold_or_expiry(driver, cfg, state, notify, control)
        if held:
            control.set_state("holding")
            return
```

- [ ] **Step 4: Add signal-handler factory and rewire main()**

`import` 블록에 추가:

```python
import signal
import threading
```

`main()` 위에 팩토리 추가:

```python
def _request_stop_on_signal(control):
    """SIGTERM/SIGINT 수신 시 control에 종료를 요청하는 핸들러를 만든다."""

    def handler(signum, frame) -> None:
        logger.info("Received signal %d; requesting graceful stop", signum)
        control.request_stop()

    return handler
```

`main()`을 아래로 교체:

```python
def main() -> None:
    """단일 인스턴스 잠금 → 설정 로드 → Chrome attach → 봇 스레드 → 상태머신 실행."""
    # nol_driver는 실제 브라우저 제어가 필요한 모듈이므로 진입점에서만 지연 임포트한다
    import telegram_control
    from control import ControlState
    from nol_driver import NolDriver

    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s"
    )

    lock = acquire_single_instance_lock()
    if lock is None:
        logger.error("Another nol_monitor instance is already running; exiting")
        raise SystemExit(1)

    cfg = load_nol_config(ENV_PATH, NOL_TARGETS_PATH)
    driver = NolDriver(cfg.nol)
    state = SeatState()
    control = ControlState(cfg.nol.date, cfg.nol.time)

    def notify(text: str) -> None:
        try:
            send_telegram(cfg.telegram, text)
        except AppBaseError as exc:
            # 텔레그램 실패의 상세 원인(토큰 포함 가능)을 로그에 남기지 않는다
            logger.error("Notify failed: %s", type(exc).__name__)

    # SIGTERM/SIGINT를 종료 요청으로 수렴시킨다(graceful shutdown)
    handler = _request_stop_on_signal(control)
    signal.signal(signal.SIGTERM, handler)
    signal.signal(signal.SIGINT, handler)

    # 봇 수신은 daemon 스레드: 프로세스 종료 시 함께 소멸(별도 join 불필요)
    bot = threading.Thread(
        target=telegram_control.serve, args=(cfg.telegram, control), daemon=True
    )
    bot.start()

    try:
        driver.attach()
        logger.info(
            "Monitor started for goods_id=%s date=%s time=%s",
            cfg.nol.goods_id,
            cfg.nol.date,
            cfg.nol.time,
        )
        _run_loop(driver, cfg, state, notify, control)
    finally:
        driver.close()
        lock.close()
```

(기존 `except KeyboardInterrupt` 블록은 제거된다 — SIGINT가 이제 핸들러로 종료를 요청하고 `finally`가 정리를 보장한다.)

- [ ] **Step 5: Run the updated/added tests**

Run: `python3 -m pytest tests/test_nol_driver.py -k "run_loop or signal_handler" -v`
Expected: PASS (기존 2 + 신규 2 = 4 passed)

- [ ] **Step 6: Full suite + lint**

Run: `python3 -m pytest -q`
Expected: 전체 통과(기존 + 신규 포함)

Run: `ruff format control.py telegram_control.py nol_monitor.py tests/test_control.py tests/test_telegram_control.py tests/test_single_instance.py tests/test_nol_driver.py && ruff check control.py telegram_control.py nol_monitor.py tests/`
Expected: 포매팅 정리 후 check 통과(에러 0)

- [ ] **Step 7: Commit**

```bash
git add nol_monitor.py tests/test_nol_driver.py
git commit -m "feat: 모니터에 control·시그널 graceful 종료·Telegram 제어 스레드 배선

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Self-Review

**Spec coverage:**
- A-1 SIGTERM/SIGINT graceful 종료 → Task 4 `_request_stop_on_signal` + main 시그널 배선 + finally. ✅
- A-2 단일 인스턴스 잠금 → Task 2 `acquire_single_instance_lock`. ✅
- C `/status` → Task 3 `dispatch`/`format_status`. ✅
- C `/pause`·`/resume` → Task 3 `dispatch` + Task 1 pause/resume. ✅
- C `/stop` → Task 3 `dispatch`(request_stop) → Task 4 루프 종료. ✅
- 봇 daemon 스레드 + getUpdates 롱폴링 → Task 3 `serve` + Task 4 스레드 기동. ✅
- chat_id 인가 → Task 3 `handle_update`. ✅
- ControlState 스레드 안전 + 상태 스냅샷 → Task 1. ✅
- 드라이버는 모니터 스레드만 접근(봇은 control만) → Task 3/4 설계상 준수(봇 핸들러는 control만 조작). ✅
- 아웃바운드 알림 기존 유지 → `notify`/`send_telegram` 변경 없음. ✅
- pause 중 세션 만료 시 재진입 → Task 4 `_poll_until_hold_or_expiry`가 wait_if_paused 후 `_is_session_expiring`로 재진입 유도. ✅

**Placeholder scan:** TBD/TODO/"적절히 처리" 없음. 모든 코드 스텝에 실제 코드 포함. ✅

**Type consistency:** `ControlState`/`ControlSnapshot` 필드·메서드가 Task 1 정의와 Task 3·4 사용에서 일치(`request_stop`/`should_stop`/`pause`/`resume`/`is_paused`/`wait_if_paused`/`set_state`/`mark_success`/`mark_failure`/`snapshot`). `_run_loop`/`_poll_until_hold_or_expiry`의 새 `control` 인자가 Task 4 정의·테스트·main 호출에서 일관. `dispatch`/`handle_update`/`serve`/`format_status` 시그니처 일치. ✅
