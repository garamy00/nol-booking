"""NOL 티켓(인터파크) 예매창 네비게이션 드라이버 (ATTACH 방식).

사용자가 `--remote-debugging-port=9222`로 이미 띄워 로그인까지 마친 Chrome에
attach하여 goods 페이지 진입 → 회차 선택 → 예매창(onestop/seat) 좌석 읽기 →
일정변경(토글) → 재진입까지 능동적으로 네비게이션한다. 새 Chrome을 띄우거나
로그인을 수행하지 않으며, close() 시에도 사용자 브라우저를 닫지 않는다.
"""

from __future__ import annotations

import glob
import logging
import os
import re
import time

from selenium import webdriver
from selenium.common.exceptions import (
    ElementClickInterceptedException,
    ElementNotInteractableException,
    NoSuchElementException,
    TimeoutException,
    WebDriverException,
)
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait

import interpark_dom
from config import NolConfig
from errors import DriverError
from nol_seats import NolSeat, parse_seat_meta

logger = logging.getLogger(__name__)

DEBUGGER_ADDRESS = "127.0.0.1:9222"

# 반응형 레이아웃에서 예매하기 버튼(a.sideBtn.is-primary)이 렌더링되는 최소
# 데스크톱 창 크기. 창이 이보다 좁으면 버튼 자체가 DOM에 그려지지 않아
# 예매 진입이 실패하므로 attach 시 이 크기 이상으로 강제한다.
MIN_DESKTOP_WIDTH = 1440
MIN_DESKTOP_HEIGHT = 1000

# 캘린더가 리렌더링될 시간을 두기 위한 짧은 대기(SPA/jQuery 모두 즉시 반영되지 않음)
CALENDAR_SETTLE_SEC = 0.5

# 월 이동 클릭 무한루프 방지 상한
MAX_MONTH_ADVANCE = 12

# 토글 리로드가 SPA 리렌더로 인한 일시적 실패(stale element 등)로 깨질 때,
# 곧바로 완전 재진입하지 않고 제자리에서 재시도하는 횟수·간격
RELOAD_RETRIES = 3
RELOAD_RETRY_WAIT_SEC = 1.0

_REMAINING_STRIP_RE = re.compile(r"\s+")
_REMAINING_RE = re.compile(r"좌석선택시간(\d+):(\d+)")


def _resolve_service() -> Service:
    """Chrome 버전과 맞는 chromedriver로 Service를 만든다.

    PATH에 구버전 chromedriver가 있으면 Selenium이 그것을 집어 현재 Chrome과
    버전 충돌로 attach가 실패할 수 있다. 이를 피하기 위해 환경변수
    CHROMEDRIVER_PATH가 있으면 그것을, 없으면 Selenium이 캐시해 둔 최신
    chromedriver를 명시적으로 사용한다. 후보가 없으면 기본 해석에 맡긴다.
    """
    override = os.environ.get("CHROMEDRIVER_PATH")
    if override:
        return Service(executable_path=override)

    cache_glob = os.path.expanduser(
        "~/.cache/selenium/chromedriver/*/*/chromedriver"
    )
    candidates = sorted(glob.glob(cache_glob))
    if candidates:
        return Service(executable_path=candidates[-1])
    return Service()


def to_ampm(hhmm: str) -> str:
    """24h "HH:MM"을 12h "H:MM AM/PM" 형식으로 변환한다(일정변경 레이어 매칭용)."""
    hour, minute = (int(part) for part in hhmm.split(":"))
    period = "AM" if hour < 12 else "PM"
    hour12 = hour % 12 or 12
    return "%d:%02d %s" % (hour12, minute, period)


def parse_remaining(card_text: str) -> int | None:
    """scheduleCard 텍스트에서 "좌석 선택 시간 M:SS"를 찾아 총 초를 반환한다.

    공백이 콜론 주변·숫자 사이 어디에 끼어 있어도(예 "5 : 35") 허용하기 위해
    전체 공백을 제거한 뒤 매칭한다. 패턴이 없으면 None.
    """
    compact = _REMAINING_STRIP_RE.sub("", card_text)
    match = _REMAINING_RE.search(compact)
    if match is None:
        return None
    minutes, seconds = int(match.group(1)), int(match.group(2))
    return minutes * 60 + seconds


def _month_label(yyyymmdd: str, sep: str) -> str:
    """ "YYYYMMDD"를 "YYYY{sep}MM" 월 라벨로 변환한다.

    goods 캘린더는 "2026. 07"(sep=". "), 일정변경 레이어는 "2026.08"(sep=".")
    형식을 쓴다.
    """
    return "%s%s%s" % (yyyymmdd[:4], sep, yyyymmdd[4:6])


def _day_number(yyyymmdd: str) -> str:
    """ "YYYYMMDD"에서 앞자리 0을 뗀 일(day) 문자열을 뽑는다(셀 텍스트 매칭용)."""
    return str(int(yyyymmdd[6:8]))


class NolDriver:
    """이미 열려 있는 Chrome(디버그 포트)에 attach해 NOL 예매창을 네비게이션한다."""

    def __init__(self, cfg: NolConfig) -> None:
        self._cfg = cfg
        self._driver = None
        self._wait = None

    @property
    def goods_url(self) -> str:
        """goods 상세 페이지 URL."""
        return "%s/%s" % (self._cfg.url, self._cfg.goods_id)

    def attach(self) -> None:
        """디버그 포트로 떠 있는 Chrome에 연결하고 interpark.com 창을 찾는다.

        Raises:
            DriverError: Chrome 연결 실패 또는 interpark.com 창을 찾지 못함.
        """
        options = Options()
        options.add_experimental_option("debuggerAddress", DEBUGGER_ADDRESS)
        try:
            driver = webdriver.Chrome(options=options, service=_resolve_service())
        except WebDriverException as exc:
            raise DriverError(
                "cannot attach to Chrome on %s; is it running with "
                "--remote-debugging-port=9222?" % DEBUGGER_ADDRESS
            ) from exc

        matched_url = self._find_interpark_window(driver)
        if matched_url is None:
            raise DriverError(
                "no interpark.com window found; open NOL and log in first"
            )

        self._ensure_desktop_window(driver)

        self._driver = driver
        self._wait = WebDriverWait(driver, 15)
        logger.info("Attached to Chrome window: %s", matched_url)

    def _ensure_desktop_window(self, driver) -> None:
        """예매하기 버튼이 렌더링되도록 창을 데스크톱 크기 이상으로 확대한다.

        창이 좁으면 반응형 레이아웃에서 a.sideBtn.is-primary가 DOM에 나타나지
        않아 예매 진입이 실패한다. 이미 충분히 큰 창은 건드리지 않는다.
        """
        try:
            size = driver.get_window_size()
            if size["width"] < MIN_DESKTOP_WIDTH or size["height"] < MIN_DESKTOP_HEIGHT:
                driver.set_window_size(MIN_DESKTOP_WIDTH, MIN_DESKTOP_HEIGHT)
                logger.info(
                    "Resized window to desktop layout %dx%d",
                    MIN_DESKTOP_WIDTH,
                    MIN_DESKTOP_HEIGHT,
                )
        except WebDriverException as exc:
            logger.warning(
                "could not ensure desktop window size: %s", type(exc).__name__
            )

    def _safe_click(self, element) -> None:
        """요소를 화면 안으로 스크롤한 뒤 클릭한다(가로막힘/미상호작용 폴백 포함).

        환경(Chromium·RDP 등)에 따라 요소가 뷰포트 밖이거나 레이어 애니메이션·
        오버레이에 순간적으로 가려 네이티브 click이 ElementClickIntercepted·
        ElementNotInteractable로 실패한다. scrollIntoView로 화면에 넣고
        클릭하되, 그래도 막히면 이벤트를 직접 디스패치(JS click)해 통과시킨다.
        """
        self._driver.execute_script(
            "arguments[0].scrollIntoView({block:'center'});", element
        )
        try:
            element.click()
        except (
            ElementClickInterceptedException,
            ElementNotInteractableException,
        ):
            logger.warning("native click blocked; falling back to JS click")
            self._driver.execute_script("arguments[0].click();", element)

    def _find_interpark_window(self, driver) -> str | None:
        """모든 창을 순회해 interpark.com 창으로 전환하고 URL을 반환한다."""
        for handle in driver.window_handles:
            driver.switch_to.window(handle)
            url = driver.current_url
            if "interpark.com" in url:
                return url
        return None

    def is_on_seat_page(self) -> bool:
        """현재 창이 예매창(onestop/seat)인지 확인한다."""
        self._require_attached()
        return interpark_dom.SEAT_PAGE_MARKER in self._driver.current_url

    def current_schedule_text(self) -> str:
        """상단에 표시된 현재 선택 일정 텍스트를 반환한다.

        예: "2026.08.02(일) 2:00 PM". 요소가 없으면 빈 문자열.
        """
        self._require_attached()
        return (
            self._driver.execute_script(
                "const e = document.querySelector('%s');"
                "return e ? (e.innerText || e.textContent || '') : '';"
                % interpark_dom.SCHEDULE_DATE_QUERY
            )
            or ""
        )

    def is_on_target_schedule(self) -> bool:
        """현재 예매창이 목표 날짜/회차(cfg.date/time)를 보여주는지 확인한다.

        토글 리로드가 복귀에 실패해 다른 날짜(예 토글용 날짜)에 머무를 때
        그 좌석을 잘못 매칭·알림하는 것을 막기 위한 안전장치다.
        """
        text = self.current_schedule_text()
        date_str = "%s.%s.%s" % (
            self._cfg.date[:4],
            self._cfg.date[4:6],
            self._cfg.date[6:8],
        )
        return date_str in text and to_ampm(self._cfg.time) in text

    def enter_booking(self) -> None:
        """goods 페이지에서 목표 날짜·회차를 선택해 예매창으로 진입한다.

        이미 예매창이면 아무 것도 하지 않는다.

        Raises:
            DriverError: 각 단계 실패 시, 어떤 단계인지 메시지에 포함해 발생.
        """
        self._require_attached()
        # 목표 일정의 좌석페이지일 때만 스킵한다. 잘못된 날짜(예 토글용)에
        # 갇혀 있으면 스킵하지 말고 goods부터 다시 진입해 목표로 되돌린다.
        if self.is_on_seat_page() and self.is_on_target_schedule():
            logger.info("Already on target seat page; skip booking entry")
            return

        if "/goods/" not in self._driver.current_url:
            logger.info("Navigating to goods page: %s", self.goods_url)
            self._driver.get(self.goods_url)

        self._open_calendar_if_collapsed()
        self._advance_goods_calendar_to_month(self._cfg.date)
        self._click_goods_day(self._cfg.date)
        self._click_goods_time(self._cfg.time)
        self._click_book_button()
        self._wait_for_seat_page()
        logger.info(
            "Entered booking for date=%s time=%s", self._cfg.date, self._cfg.time
        )

    def _open_calendar_if_collapsed(self) -> None:
        """goods 캘린더가 접혀 있으면 sideToggleBtn을 눌러 펼친다."""
        try:
            days = self._driver.find_elements(
                By.CSS_SELECTOR, interpark_dom.GOODS_DAYS
            )
            if days and days[0].is_displayed():
                return
            self._safe_click(
                self._driver.find_element(
                    By.CSS_SELECTOR, interpark_dom.GOODS_SIDE_TOGGLE
                )
            )
            self._wait.until(
                lambda d: d.find_elements(By.CSS_SELECTOR, interpark_dom.GOODS_DAYS)
            )
        except (NoSuchElementException, TimeoutException, WebDriverException) as exc:
            raise DriverError(
                "enter_booking: failed to open calendar: %s" % type(exc).__name__
            ) from exc

    def _advance_goods_calendar_to_month(self, yyyymmdd: str) -> None:
        """goods 캘린더 월을 목표 월까지 next 클릭으로 이동한다."""
        target_label = _month_label(yyyymmdd, ". ")
        try:
            for _ in range(MAX_MONTH_ADVANCE):
                current = self._driver.find_element(
                    By.CSS_SELECTOR, interpark_dom.GOODS_MONTH_CURRENT
                ).text.strip()
                if current == target_label:
                    return
                self._safe_click(
                    self._driver.find_element(
                        By.CSS_SELECTOR, interpark_dom.GOODS_MONTH_NEXT
                    )
                )
                time.sleep(CALENDAR_SETTLE_SEC)
        except (NoSuchElementException, TimeoutException, WebDriverException) as exc:
            raise DriverError(
                "enter_booking: failed to navigate calendar month: %s"
                % type(exc).__name__
            ) from exc
        raise DriverError(
            "enter_booking: could not reach target month %s within %d clicks"
            % (target_label, MAX_MONTH_ADVANCE)
        )

    def _click_goods_day(self, yyyymmdd: str) -> None:
        """goods 캘린더에서 목표 일(day) 셀을 클릭한다(muted/disabled 제외)."""
        day_num = _day_number(yyyymmdd)
        try:
            cells = self._driver.find_elements(
                By.CSS_SELECTOR, interpark_dom.GOODS_DAYS
            )
            for cell in cells:
                classes = cell.get_attribute("class") or ""
                if "muted" in classes or "disabled" in classes:
                    continue
                if cell.text.strip() == day_num:
                    self._safe_click(cell)
                    return
        except (NoSuchElementException, TimeoutException, WebDriverException) as exc:
            raise DriverError(
                "enter_booking: failed to click day %s: %s"
                % (day_num, type(exc).__name__)
            ) from exc
        raise DriverError("enter_booking: day %s not found or not selectable" % day_num)

    def _click_goods_time(self, time_hhmm: str) -> None:
        """목표 24h 시각을 포함하는 timeTableLabel을 클릭한다."""
        try:
            labels = self._driver.find_elements(
                By.CSS_SELECTOR, interpark_dom.GOODS_TIME_LABEL
            )
            for label in labels:
                data_text = label.get_attribute("data-text") or ""
                if time_hhmm in data_text:
                    self._safe_click(label)
                    return
        except (NoSuchElementException, TimeoutException, WebDriverException) as exc:
            raise DriverError(
                "enter_booking: failed to click time %s: %s"
                % (time_hhmm, type(exc).__name__)
            ) from exc
        raise DriverError(
            "enter_booking: time %s not found among schedule options" % time_hhmm
        )

    def _click_book_button(self) -> None:
        """예매하기 버튼을 클릭한다.

        이 버튼(사이드 패널)은 페이지 하단이라 뷰포트 밖일 수 있어 _safe_click
        으로 스크롤 후 클릭한다.
        """
        try:
            btn = self._driver.find_element(
                By.CSS_SELECTOR, interpark_dom.GOODS_BOOK_BUTTON
            )
        except NoSuchElementException as exc:
            raise DriverError("enter_booking: book button not found") from exc

        try:
            self._safe_click(btn)
        except WebDriverException as exc:
            raise DriverError(
                "enter_booking: failed to click book button: %s" % type(exc).__name__
            ) from exc

    def _wait_for_seat_page(self) -> None:
        """URL 전환 + 좌석 SVG 렌더링 완료까지 대기한다.

        URL이 onestop/seat로 바뀐 직후엔 React가 좌석 circle을 아직 그리지
        않아 곧바로 읽으면 0석이 된다. circle.js-seat가 실제로 나타날 때까지
        기다린다.
        """
        try:
            self._wait.until(lambda d: interpark_dom.SEAT_PAGE_MARKER in d.current_url)
            self._wait_for_seats_rendered()
        except TimeoutException as exc:
            raise DriverError(
                "enter_booking: seat page did not load within timeout (url=%s)"
                % self._driver.current_url
            ) from exc

    def _wait_for_seats_rendered(self) -> None:
        """좌석 circle.js-seat가 하나 이상 렌더링될 때까지 대기한다."""
        self._wait.until(
            lambda d: d.execute_script(
                "return document.querySelectorAll('%s').length;"
                % interpark_dom.SEAT_CIRCLE
            )
            > 0
        )

    def read_available_seats(self) -> list[NolSeat]:
        """예매창 SVG에서 가용 좌석(circle.js-seat, disabled 제외)의 React fiber
        라벨(구역/열/번호/등급)을 읽어 NolSeat 목록으로 변환한다.

        Raises:
            DriverError: attach되지 않았거나 스크립트 실행 실패.
        """
        self._require_attached()
        try:
            raw_seats = self._driver.execute_script(interpark_dom.READ_SEATS_JS)
        except WebDriverException as exc:
            raise DriverError("failed to read seats: %s" % type(exc).__name__) from exc

        seats = [
            seat
            for seat in (parse_seat_meta(raw) for raw in raw_seats or [])
            if seat is not None
        ]
        logger.info("Read %d available seats", len(seats))
        return seats

    def remaining_seconds(self) -> int | None:
        """SessionDwellTimer의 남은 좌석 선택 시간을 초 단위로 반환한다(없으면 None).

        타이머 텍스트는 "좌석 선택 시간 2 : 3 1"처럼 숫자 사이에 공백이 끼므로
        parse_remaining이 공백을 제거해 파싱한다.
        """
        self._require_attached()
        # Selenium의 .text는 이 SPA 타이머 요소에서 빈 값을 주는 경우가 있어
        # execute_script의 innerText로 직접 읽는다.
        try:
            text = self._driver.execute_script(
                "const e = document.querySelector('%s');"
                "return e ? (e.innerText || e.textContent || '') : null;"
                % interpark_dom.SESSION_TIMER_QUERY
            )
        except WebDriverException as exc:
            raise DriverError(
                "failed to read session timer: %s" % type(exc).__name__
            ) from exc
        if not text:
            logger.debug("SessionDwellTimer not found; cannot read remaining time")
            return None
        return parse_remaining(text)

    def change_schedule(self, date: str, time_hhmm: str) -> None:
        """일정변경 레이어로 날짜·회차를 바꾸고 변경하기를 눌러 좌석맵을 리로드한다.

        Raises:
            DriverError: 레이어 조작 중 어느 단계라도 실패.
        """
        self._require_attached()
        logger.info("Changing schedule to date=%s time=%s", date, time_hhmm)
        try:
            self._open_date_layer()
            self._advance_layer_calendar_to_month(date)
            self._click_layer_day(date)
            self._click_layer_time(time_hhmm)
            self._click_apply_button()
            self._wait_for_layer_closed()
        except DriverError:
            raise
        except (NoSuchElementException, TimeoutException, WebDriverException) as exc:
            raise DriverError(
                "change_schedule(%s, %s) failed: %s"
                % (date, time_hhmm, type(exc).__name__)
            ) from exc
        logger.info("Schedule changed to date=%s time=%s", date, time_hhmm)

    def _open_date_layer(self) -> None:
        """일정변경 버튼이 준비되면 눌러 레이어를 연다.

        새로 진입한 직후엔 좌석은 렌더됐어도 상단 일정변경 버튼이 아직
        안 떠 있을 수 있어, 클릭 가능해질 때까지 기다린 뒤 누른다.
        """
        button = self._wait.until(
            EC.element_to_be_clickable(
                (By.CSS_SELECTOR, interpark_dom.LAYER_DATE_BUTTON)
            )
        )
        self._safe_click(button)
        self._wait.until(
            EC.presence_of_element_located(
                (By.CSS_SELECTOR, interpark_dom.LAYER_CONTAINER)
            )
        )
        # 레이어 컨테이너가 떠도 내부 캘린더(월 헤더)는 잠시 뒤 렌더되므로 대기한다
        self._wait.until(
            EC.presence_of_element_located(
                (By.CSS_SELECTOR, interpark_dom.LAYER_MONTH)
            )
        )

    def _advance_layer_calendar_to_month(self, yyyymmdd: str) -> None:
        """레이어(EntCalendar) 월을 목표 월까지 next/prev로 이동한다."""
        target_label = _month_label(yyyymmdd, ".")
        for _ in range(MAX_MONTH_ADVANCE):
            # Selenium .text가 이 SPA 요소에서 빈 값을 주는 경우가 있어
            # textContent로 직접 읽는다(렌더링 상태와 무관).
            current = (
                self._driver.find_element(
                    By.CSS_SELECTOR, interpark_dom.LAYER_MONTH
                ).get_attribute("textContent")
                or ""
            ).strip()
            if current == target_label:
                return
            # "YYYY.MM" 고정폭 형식이라 문자열 비교로 방향 판단이 가능하다
            btn_id = (
                interpark_dom.LAYER_SWIPER_NEXT_ID
                if current < target_label
                else interpark_dom.LAYER_SWIPER_PREV_ID
            )
            btn = self._driver.find_element(By.ID, btn_id)
            if "disabled" in (btn.get_attribute("class") or ""):
                raise DriverError(
                    "change_schedule: calendar navigation disabled before "
                    "reaching %s (at %s)" % (target_label, current)
                )
            self._safe_click(btn)
            time.sleep(CALENDAR_SETTLE_SEC)
        raise DriverError(
            "change_schedule: could not reach target month %s" % target_label
        )

    def _click_layer_day(self, yyyymmdd: str) -> None:
        """활성 슬라이드에서 목표 일(day) 버튼을 클릭한다(disabled 제외)."""
        day_num = _day_number(yyyymmdd)
        active_slide = self._driver.find_element(
            By.CSS_SELECTOR, interpark_dom.LAYER_SWIPER_ACTIVE
        )
        buttons = active_slide.find_elements(
            By.CSS_SELECTOR, interpark_dom.LAYER_DATE_ITEM_BUTTON
        )
        for button in buttons:
            if button.get_attribute("disabled"):
                continue
            numbers = button.find_elements(
                By.CSS_SELECTOR, interpark_dom.LAYER_DATE_NUMBER
            )
            if not numbers:
                continue
            number_text = (numbers[0].get_attribute("textContent") or "").strip()
            if number_text == day_num:
                self._safe_click(button)
                return
        raise DriverError(
            "change_schedule: day %s not found or not selectable in layer" % day_num
        )

    def _click_layer_time(self, time_hhmm: str) -> None:
        """목표 시각(12h AM/PM)의 TimeBlock 버튼이 나타나면 클릭한다.

        레이어에서 날짜를 바꾸면 회차 목록이 비동기로 갱신되므로, 곧바로
        조회하면 이전 날짜의 회차가 잡혀 목표 시각을 못 찾을 수 있다.
        목표 시각 버튼이 실제로 나타날 때까지 기다린 뒤 클릭한다.
        """
        target = to_ampm(time_hhmm)

        def _find_target_time(driver):
            selector = interpark_dom.LAYER_TIME_BUTTON
            for button in driver.find_elements(By.CSS_SELECTOR, selector):
                text = (button.get_attribute("textContent") or "").strip()
                if text.startswith(target):
                    return button
            return False

        try:
            button = self._wait.until(_find_target_time)
        except TimeoutException as exc:
            raise DriverError(
                "change_schedule: time %s (%s) not found among time buttons"
                % (time_hhmm, target)
            ) from exc
        self._safe_click(button)

    def _click_apply_button(self) -> None:
        """변경하기 버튼(EntButton_primary)을 클릭한다."""
        buttons = self._driver.find_elements(
            By.CSS_SELECTOR, interpark_dom.LAYER_APPLY_BUTTON
        )
        for button in buttons:
            if "변경하기" in button.text:
                if button.get_attribute("disabled"):
                    raise DriverError(
                        "change_schedule: apply button (변경하기) is disabled"
                    )
                self._safe_click(button)
                return
        raise DriverError("change_schedule: apply button (변경하기) not found")

    def _wait_for_layer_closed(self) -> None:
        """레이어가 사라지고 좌석 circle이 다시 렌더링될 때까지 대기한다."""
        self._wait.until(
            EC.invisibility_of_element_located(
                (By.CSS_SELECTOR, interpark_dom.LAYER_CONTAINER)
            )
        )
        self._wait.until(
            lambda d: d.find_elements(By.CSS_SELECTOR, interpark_dom.SEAT_CIRCLE)
        )

    def reload_target(self) -> None:
        """TOGGLE 날짜/시간으로 갔다가 TARGET으로 복귀해 좌석맵을 리로드한다.

        일정변경 레이어 조작은 SPA 리렌더로 인한 일시적 실패(stale element 등)가
        간헐적으로 발생하므로, 제자리에서 몇 번 재시도한다. 재시도까지 모두
        실패해야 예외를 올려 호출부가 완전 재진입으로 폴백하게 한다.
        """
        last_exc: DriverError | None = None
        for attempt in range(1, RELOAD_RETRIES + 1):
            try:
                self.change_schedule(self._cfg.toggle_date, self._cfg.toggle_time)
                self.change_schedule(self._cfg.date, self._cfg.time)
                return
            except DriverError as exc:
                last_exc = exc
                logger.warning(
                    "reload_target attempt %d/%d failed: %s; retrying",
                    attempt,
                    RELOAD_RETRIES,
                    exc,
                )
                time.sleep(RELOAD_RETRY_WAIT_SEC)
        raise last_exc

    def reenter(self) -> None:
        """세션 만료 후 goods 페이지부터 예매창 진입을 다시 수행한다."""
        self._require_attached()
        self._driver.get(self.goods_url)
        self.enter_booking()

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
