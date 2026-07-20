"""Selenium 기반 좌석 페이지 드라이버 (ATTACH 방식).

사용자가 `--remote-debugging-port=9222` 로 이미 띄워 로그인까지 마친 Chrome에
attach 하여 좌석 정보를 읽기만 한다. 새 Chrome을 띄우거나 로그인을 수행하지
않으며, close() 시에도 사용자 브라우저를 닫지 않는다.
"""

from __future__ import annotations

import logging
import re
import time

from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.support.ui import WebDriverWait

from config import NtokConfig
from errors import DriverError
from seats import Seat

logger = logging.getLogger(__name__)

DEBUGGER_ADDRESS = "127.0.0.1:9222"
SEAT_IFRAME_CSS = "iframe[name=ifrHSD]"
AVAILABLE_SEAT_CSS = "#divSeatArray > div[title]"
SEAT_PAGE_MARKER = "PerfSaleProcess"

_REFRESH_TIMEOUT_SEC = 15
_REFRESH_POLL_INTERVAL_SEC = 0.5

TITLE_RE = re.compile(
    r"^\[(?P<grade>[^\]]+)\]\s*(?P<floor>\d+)층\s*(?P<section>\S+?)구역\s*"
    r"(?P<row>\d+)열\s*(?P<num>\d+)번"
)


def parse_seat_title(title: str) -> Seat | None:
    """좌석 div의 title 속성을 파싱해 Seat로 변환한다.

    형식에 맞지 않으면 None을 반환한다 (호출부에서 스킵 처리).
    """
    match = TITLE_RE.match(title)
    if match is None:
        return None

    floor = "%dF" % int(match.group("floor"))
    return Seat(
        floor=floor,
        section=match.group("section"),
        row=int(match.group("row")),
        number=int(match.group("num")),
        available=True,
    )


class BookingDriver:
    """이미 열려 있는 Chrome(디버그 포트)에 attach해 좌석을 읽는 드라이버."""

    def __init__(self, cfg: NtokConfig) -> None:
        self._cfg = cfg
        self._driver = None
        self._wait = None

    def attach(self) -> None:
        """디버그 포트로 떠 있는 Chrome에 연결하고 좌석 선택 창을 찾는다.

        Raises:
            DriverError: Chrome 연결 실패 또는 좌석 선택 창을 찾지 못함.
        """
        options = Options()
        options.add_experimental_option("debuggerAddress", DEBUGGER_ADDRESS)
        try:
            driver = webdriver.Chrome(options=options)
        except Exception as exc:
            raise DriverError(
                "cannot attach to Chrome on %s; is it running with "
                "--remote-debugging-port=9222?" % DEBUGGER_ADDRESS
            ) from exc

        matched_url = self._find_seat_window(driver)
        if matched_url is None:
            raise DriverError(
                "seat page window not found; open the PerfSaleProcess seat page"
            )

        self._driver = driver
        self._wait = WebDriverWait(self._driver, 15)
        logger.info("Attached to Chrome seat page window: %s", matched_url)

    def _find_seat_window(self, driver) -> str | None:
        """모든 창을 순회해 좌석 선택 페이지 창으로 전환하고 URL을 반환한다."""
        for handle in driver.window_handles:
            driver.switch_to.window(handle)
            url = driver.current_url
            if SEAT_PAGE_MARKER not in url:
                continue
            if self._cfg.id_perf and self._cfg.id_perf not in url:
                continue
            return url
        return None

    def refresh(self) -> None:
        """좌석 iframe을 리로드하고 다시 채워질 때까지 대기한다.

        Raises:
            DriverError: attach되지 않았거나 대기 시간 내에 채워지지 않음.
        """
        self._require_attached()
        self._driver.switch_to.default_content()
        try:
            self._driver.execute_script(
                "document.querySelector(arguments[0]).contentWindow.location.reload()",
                SEAT_IFRAME_CSS,
            )
            self._wait_for_seat_array_populated()
        finally:
            self._driver.switch_to.default_content()

    def _wait_for_seat_array_populated(self) -> None:
        """`#divSeatArray`가 다시 채워질 때까지 iframe 안에서 폴링한다."""
        deadline = time.monotonic() + _REFRESH_TIMEOUT_SEC
        while time.monotonic() < deadline:
            self._driver.switch_to.default_content()
            self._driver.switch_to.frame(
                self._driver.find_element("css selector", SEAT_IFRAME_CSS)
            )
            count = self._driver.execute_script(
                "var el = document.querySelector('#divSeatArray'); "
                "return el ? el.childElementCount : 0;"
            )
            if count and count > 0:
                return
            time.sleep(_REFRESH_POLL_INTERVAL_SEC)

        raise DriverError(
            "seat array not populated within %ds after refresh" % _REFRESH_TIMEOUT_SEC
        )

    def is_session_alive(self) -> bool:
        """세션이 여전히 유효한(로그인 페이지로 튕기지 않은) 상태인지 확인한다."""
        self._require_attached()
        url = self._driver.current_url
        return "booking.ntok.go.kr" in url and "login" not in url.lower()

    def read_available_seats(self) -> list[Seat]:
        """가용 좌석(title 속성이 있는 div) 목록을 읽어 Seat 리스트로 반환한다.

        Raises:
            DriverError: attach되지 않았거나 읽기 중 예상치 못한 실패.
        """
        self._require_attached()
        try:
            self._driver.switch_to.default_content()
            self._driver.switch_to.frame(
                self._driver.find_element("css selector", SEAT_IFRAME_CSS)
            )
            elements = self._driver.find_elements("css selector", AVAILABLE_SEAT_CSS)

            seats: list[Seat] = []
            for element in elements:
                seat = parse_seat_title(element.get_attribute("title") or "")
                if seat is not None:
                    seats.append(seat)
            return seats
        except Exception as exc:
            raise DriverError("failed to read seats: %s" % type(exc).__name__) from exc
        finally:
            self._driver.switch_to.default_content()

    def close(self) -> None:
        """attach를 해제한다. 사용자 Chrome은 닫지 않는다(quit 호출 금지)."""
        if self._driver is None:
            return

        logger.info("Detached from Chrome (browser left open)")
        self._driver = None
        self._wait = None

    def _require_attached(self) -> None:
        """attach 여부를 검증하고 미완료 시 DriverError를 발생시킨다."""
        if self._driver is None:
            raise DriverError("driver not attached; call attach() first")
