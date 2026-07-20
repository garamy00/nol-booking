"""NOL 티켓 좌석 모니터 진입점: 예매창 진입 → 폴링 → 홀드/재진입 상태머신."""

from __future__ import annotations

import logging
import random
import time
from collections.abc import Callable

from config import NolAppConfig, load_nol_config
from errors import AppBaseError, DriverError
from nol_seats import NolSeatGroup, find_nol_groups
from notifier import send_telegram
from state import SeatState

logger = logging.getLogger(__name__)

ENV_PATH = ".env"
NOL_TARGETS_PATH = "nol_targets.yaml"

# 좌석 선택 세션(10분) 만료 전에 여유를 두고 재진입하기 위한 안전 마진
SAFETY_SECONDS = 40

# 페이지 타이머 텍스트를 못 읽을 때를 대비한 벽시계 기반 세션 상한(초).
# 실제 제한(10분)보다 넉넉히 앞서 재진입해 만료로 인한 실패를 피한다.
MAX_SESSION_SECONDS = 9 * 60

# 예매창 진입 실패 시 재시도 전 대기(초)
REENTRY_BACKOFF_SECONDS = 30


def check_once(
    driver, cfg: NolAppConfig, state: SeatState, notify: Callable[[str], None]
) -> list[NolSeatGroup]:
    """폴링 1회: 좌석 수집 → 타깃 매칭 → 신규 묶음 알림.

    Returns:
        이번 회차에 알린(=신규 발견된) 좌석 묶음 목록.
    """
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
    while True:
        # 첫 진입은 enter_booking, 이후엔 goods로 되돌아가 새 세션으로 재진입
        try:
            if first:
                driver.enter_booking()
                first = False
            else:
                driver.reenter()
        except DriverError as exc:
            logger.error(
                "Booking entry failed (%s); retrying in %ds",
                type(exc).__name__,
                REENTRY_BACKOFF_SECONDS,
            )
            notify("[NOL] 예매창 진입 실패: %s (재시도)" % type(exc).__name__)
            time.sleep(REENTRY_BACKOFF_SECONDS)
            continue

        held = _poll_until_hold_or_expiry(driver, cfg, state, notify)
        if held:
            return


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
