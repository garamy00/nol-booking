"""NOL 티켓 좌석 모니터 진입점: 예매창 진입 → 폴링 → 홀드/재진입 상태머신."""

from __future__ import annotations

import fcntl
import logging
import os
import random
import time
from collections.abc import Callable
from typing import TextIO

from config import NolAppConfig, load_nol_config
from errors import AppBaseError, DriverError
from nol_seats import NolSeatGroup, find_nol_groups
from notifier import send_telegram
from state import SeatState

logger = logging.getLogger(__name__)

ENV_PATH = ".env"
NOL_TARGETS_PATH = "nol_targets.yaml"

# 단일 인스턴스 잠금 파일(스크립트 위치 기준). 중복 실행 시 두 번째는 종료.
LOCK_PATH = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), ".nol_monitor.lock"
)

# 좌석 선택 세션(10분) 만료 전에 여유를 두고 재진입하기 위한 안전 마진
SAFETY_SECONDS = 40

# 페이지 타이머 텍스트를 못 읽을 때를 대비한 벽시계 기반 세션 상한(초).
# 실제 제한(10분)보다 넉넉히 앞서 재진입해 만료로 인한 실패를 피한다.
MAX_SESSION_SECONDS = 9 * 60

# 예매창 진입 실패 시 재시도 전 대기(초)
REENTRY_BACKOFF_SECONDS = 30

# 예매창 진입 실패는 재진입 과정에서 1~3회 발생 후 자가복구되는 일이 잦다.
# 매 실패마다 알리면 텔레그램이 스팸이 되므로, 연속 실패가 이 임계에 도달해
# 지속 장애로 판단될 때만 한 번 알린다.
FAILURE_ALERT_THRESHOLD = 5


def check_once(
    driver, cfg: NolAppConfig, state: SeatState, notify: Callable[[str], None]
) -> list[NolSeatGroup]:
    """폴링 1회: 좌석 수집 → 타깃 매칭 → 신규 묶음 알림.

    Returns:
        이번 회차에 알린(=신규 발견된) 좌석 묶음 목록.
    """
    # 토글 리로드 실패 등으로 잘못된 날짜(예 토글용 날짜)에 머물러 있으면
    # 그 좌석을 매칭하지 않는다(다른 날짜 좌석을 잘못 알리는 것을 막는다).
    if not driver.is_on_target_schedule():
        logger.warning(
            "Not on target schedule (want %s %s); skipping seat match this round",
            cfg.nol.date,
            cfg.nol.time,
        )
        return []

    seats = driver.read_available_seats()
    groups = find_nol_groups(seats, cfg.targets)
    fresh = state.new_groups(groups)

    for group in fresh:
        notify("[NOL] 좌석 발견: %s" % group.label())
        logger.info("New seat group notified: %s", group.label())

    return fresh


def _sleep_with_jitter(cfg: NolAppConfig) -> None:
    """폴링 간격을 지터를 섞어 대기한다(봇 탐지 완화)."""
    delay = random.uniform(cfg.poll.interval_min, cfg.poll.interval_max)
    logger.debug("Sleeping %.1fs before next poll", delay)
    time.sleep(delay)


def _is_session_expiring(driver, session_start: float) -> bool:
    """페이지 타이머(가능하면) 또는 벽시계 상한으로 세션 만료 임박을 판단한다."""
    elapsed = time.monotonic() - session_start
    if elapsed > MAX_SESSION_SECONDS:
        logger.info("Session wall-clock limit reached (%.0fs); re-entering", elapsed)
        return True

    rem = driver.remaining_seconds()
    if rem is not None and rem < SAFETY_SECONDS:
        logger.info("Session timer low (remaining=%ss); re-entering", rem)
        return True

    return False


def _poll_until_hold_or_expiry(
    driver, cfg: NolAppConfig, state: SeatState, notify: Callable[[str], None]
) -> bool:
    """안쪽 루프: 세션 만료 전까지 좌석 확인 → 없으면 토글 리로드 후 재시도.

    좌석 읽기·토글 중 DriverError가 나면 세션이 유실된 것으로 보고 재진입을
    요청한다(타이머 텍스트가 안 보여도 만료를 사후 감지할 수 있게 한다).

    Returns:
        True면 타깃 좌석을 찾아 홀드해야 함. False면 세션 만료·유실로 재진입 필요.
    """
    session_start = time.monotonic()
    while True:
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

        _sleep_with_jitter(cfg)


def _run_loop(
    driver, cfg: NolAppConfig, state: SeatState, notify: Callable[[str], None]
) -> None:
    """바깥 루프: 예매창 (재)진입 → 안쪽 폴링. 타깃 발견 시 홀드하고 반환한다."""
    first = True
    consecutive_failures = 0
    while True:
        # 첫 진입은 enter_booking, 이후엔 goods로 되돌아가 새 세션으로 재진입
        try:
            if first:
                driver.enter_booking()
                first = False
            else:
                driver.reenter()
        except DriverError as exc:
            consecutive_failures += 1
            # 어느 단계에서 깨졌는지(캘린더/날짜/시각/예매버튼/좌석대기) 진단하려면
            # 예외 타입명이 아니라 단계·URL이 담긴 전체 메시지를 남겨야 한다
            logger.error(
                "Booking entry failed (%s); attempt %d, retrying in %ds",
                exc,
                consecutive_failures,
                REENTRY_BACKOFF_SECONDS,
            )
            # 자가복구되는 일시적 실패는 알리지 않고, 임계 도달 시 한 번만 알린다
            if consecutive_failures == FAILURE_ALERT_THRESHOLD:
                notify(
                    "[NOL] 예매창 진입이 %d회 연속 실패했습니다 (확인 필요)"
                    % consecutive_failures
                )
            time.sleep(REENTRY_BACKOFF_SECONDS)
            continue

        # 진입 성공: 지속 장애를 알렸던 경우에만 복구 알림 후 카운터를 초기화한다
        if consecutive_failures >= FAILURE_ALERT_THRESHOLD:
            notify("[NOL] 예매창 진입 복구됨")
        consecutive_failures = 0

        held = _poll_until_hold_or_expiry(driver, cfg, state, notify)
        if held:
            return


def acquire_single_instance_lock(lock_path: str = LOCK_PATH) -> TextIO | None:
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


def main() -> None:
    """설정 로드 → Chrome attach → 예매창 상태머신 실행."""
    # nol_driver는 실제 브라우저 제어가 필요한 모듈이므로 진입점에서만 지연 임포트한다
    from nol_driver import NolDriver

    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s"
    )
    cfg = load_nol_config(ENV_PATH, NOL_TARGETS_PATH)

    driver = NolDriver(cfg.nol)
    state = SeatState()

    def notify(text: str) -> None:
        try:
            send_telegram(cfg.telegram, text)
        except AppBaseError as exc:
            # 텔레그램 실패의 상세 원인(토큰 포함 가능)을 로그에 남기지 않는다
            logger.error("Notify failed: %s", type(exc).__name__)

    try:
        driver.attach()
        logger.info(
            "Monitor started for goods_id=%s date=%s time=%s",
            cfg.nol.goods_id,
            cfg.nol.date,
            cfg.nol.time,
        )
        _run_loop(driver, cfg, state, notify)
    except KeyboardInterrupt:
        logger.info("Interrupted by user")
    finally:
        driver.close()


if __name__ == "__main__":
    main()
