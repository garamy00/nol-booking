"""국립극장 좌석 모니터 진입점과 폴링 루프."""

import logging
import random
import time
from collections.abc import Callable

from config import AppConfig, load_config
from errors import AppBaseError
from notifier import send_telegram
from seats import find_available_groups
from state import SeatState

logger = logging.getLogger(__name__)

ENV_PATH = ".env"
TARGETS_PATH = "targets.yaml"


def run_once(
    driver, cfg: AppConfig, state: SeatState, notify: Callable[[str], None]
) -> int:
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
    # booking_driver는 실제 브라우저 제어가 필요한 모듈이므로 진입점에서만 지연 임포트한다
    from booking_driver import BookingDriver

    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s"
    )
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
        logger.info(
            "Monitor started; polling every %d-%d s",
            cfg.poll.interval_min,
            cfg.poll.interval_max,
        )

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
