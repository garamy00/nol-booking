"""NOL 티켓 좌석 모니터 진입점: 예매창 진입 → 폴링 → 홀드/재진입 상태머신."""

from __future__ import annotations

import logging
import random
import time
from collections.abc import Callable

from config import NolAppConfig, load_nol_config
from errors import AppBaseError
from nol_seats import NolSeatGroup, find_nol_groups
from notifier import send_telegram
from state import SeatState

logger = logging.getLogger(__name__)

ENV_PATH = ".env"
NOL_TARGETS_PATH = "nol_targets.yaml"

# 좌석 선택 세션(10분) 만료 전에 여유를 두고 재진입하기 위한 안전 마진
SAFETY_SECONDS = 40


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


def _poll_until_hold_or_expiry(
    driver, cfg: NolAppConfig, state: SeatState, notify: Callable[[str], None]
) -> bool:
    """안쪽 루프: 세션 만료 전까지 좌석 확인 → 없으면 토글 리로드 후 재시도.

    Returns:
        True면 타깃 좌석을 찾아 홀드해야 함. False면 세션 만료로 재진입 필요.
    """
    while True:
        rem = driver.remaining_seconds()
        if rem is not None and rem < SAFETY_SECONDS:
            logger.info("Session expiring (remaining=%ss); re-entering", rem)
            return False

        fresh = check_once(driver, cfg, state, notify)
        if fresh:
            logger.info("HOLD: target seat found, monitor paused on seat page")
            return True

        driver.reload_target()
        _sleep_with_jitter(cfg)


def _run_loop(
    driver, cfg: NolAppConfig, state: SeatState, notify: Callable[[str], None]
) -> None:
    """바깥 루프: 예매창 재진입 → 안쪽 폴링. 타깃 발견 시 홀드하고 반환한다."""
    while True:
        driver.enter_booking()
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
