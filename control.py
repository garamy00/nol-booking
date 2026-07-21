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
