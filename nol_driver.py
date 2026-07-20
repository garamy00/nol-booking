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
    NoSuchElementException,
    TimeoutException,
    WebDriverException,
)
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait

from config import NolConfig
from errors import DriverError
from nol_seats import NolSeat, parse_seat_meta

logger = logging.getLogger(__name__)

DEBUGGER_ADDRESS = "127.0.0.1:9222"
SEAT_PAGE_MARKER = "onestop/seat"

# 캘린더가 리렌더링될 시간을 두기 위한 짧은 대기(SPA/jQuery 모두 즉시 반영되지 않음)
CALENDAR_SETTLE_SEC = 0.5

# 월 이동 클릭 무한루프 방지 상한
MAX_MONTH_ADVANCE = 12

_REMAINING_STRIP_RE = re.compile(r"\s+")
_REMAINING_RE = re.compile(r"좌석선택시간(\d+):(\d+)")

# WHY: NOL 좌석 SVG 자체에는 구역/열/번호 라벨이 없다. 대신 각 가용 좌석
# circle의 React fiber(내부 프로퍼티 `__reactFiber$...`)에 렌더링 이전의
# 원본 seat 메타데이터(memoizedProps.seat: floor/rowNo/seatNo/seatGradeName)가
# 그대로 보존되어 있어 이를 직접 읽어낸다. React 내부 구현(비공개 API)에
# 의존하므로 interpark가 빌드를 바꾸면(fiber 키 접두어, prop 구조 등)
# 이 스크립트도 함께 갱신해야 한다.
_READ_SEATS_JS = """
const circles = [...document.querySelectorAll('circle.js-seat')];
const out = [];
for (const c of circles) {
    if ([...c.classList].some((x) => /disabled/i.test(x))) continue;
    const fiberKey = Object.keys(c).find((k) => k.startsWith('__reactFiber$'));
    if (!fiberKey) continue;
    let fiber = c[fiberKey];
    let seat = null;
    for (let i = 0; i < 4 && fiber; i++) {
        if (fiber.memoizedProps && fiber.memoizedProps.seat) {
            seat = fiber.memoizedProps.seat;
            break;
        }
        fiber = fiber.return;
    }
    if (!seat) continue;
    out.push({
        id: c.id,
        floor: seat.floor,
        rowNo: seat.rowNo,
        seatNo: seat.seatNo,
        grade: seat.seatGradeName,
    });
}
return out;
"""


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

        self._driver = driver
        self._wait = WebDriverWait(driver, 15)
        logger.info("Attached to Chrome window: %s", matched_url)

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
        return SEAT_PAGE_MARKER in self._driver.current_url

    def enter_booking(self) -> None:
        """goods 페이지에서 목표 날짜·회차를 선택해 예매창으로 진입한다.

        이미 예매창이면 아무 것도 하지 않는다.

        Raises:
            DriverError: 각 단계 실패 시, 어떤 단계인지 메시지에 포함해 발생.
        """
        self._require_attached()
        if self.is_on_seat_page():
            logger.info("Already on seat page; skip booking entry")
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
                By.CSS_SELECTOR, "ul[data-view='days'] > li"
            )
            if days and days[0].is_displayed():
                return
            self._driver.find_element(By.CSS_SELECTOR, ".sideToggleBtn").click()
            self._wait.until(
                lambda d: d.find_elements(By.CSS_SELECTOR, "ul[data-view='days'] > li")
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
                    By.CSS_SELECTOR, "li[data-view='month current']"
                ).text.strip()
                if current == target_label:
                    return
                self._driver.find_element(
                    By.CSS_SELECTOR, "li[data-view='month next']"
                ).click()
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
                By.CSS_SELECTOR, "ul[data-view='days'] > li"
            )
            for cell in cells:
                classes = cell.get_attribute("class") or ""
                if "muted" in classes or "disabled" in classes:
                    continue
                if cell.text.strip() == day_num:
                    cell.click()
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
            labels = self._driver.find_elements(By.CSS_SELECTOR, "a.timeTableLabel")
            for label in labels:
                data_text = label.get_attribute("data-text") or ""
                if time_hhmm in data_text:
                    label.click()
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
        """예매하기 버튼을 클릭한다."""
        try:
            self._driver.find_element(By.CSS_SELECTOR, "a.sideBtn.is-primary").click()
        except (NoSuchElementException, WebDriverException) as exc:
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
            self._wait.until(lambda d: SEAT_PAGE_MARKER in d.current_url)
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
                "return document.querySelectorAll('circle.js-seat').length;"
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
            raw_seats = self._driver.execute_script(_READ_SEATS_JS)
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
                "const e = document.querySelector('[class*=SessionDwellTimer]');"
                "return e ? (e.innerText || e.textContent || '') : null;"
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
        """일정변경 버튼을 눌러 레이어를 연다."""
        self._driver.find_element(
            By.CSS_SELECTOR, "button.SubHeader_layerDateButton__vncqy"
        ).click()
        self._wait.until(
            EC.presence_of_element_located(
                (By.CSS_SELECTOR, "[class*='LayerDate_container']")
            )
        )

    def _advance_layer_calendar_to_month(self, yyyymmdd: str) -> None:
        """레이어(EntCalendar) 월을 목표 월까지 next/prev로 이동한다."""
        target_label = _month_label(yyyymmdd, ".")
        for _ in range(MAX_MONTH_ADVANCE):
            current = self._driver.find_element(
                By.CSS_SELECTOR, "h3.EntCalendar_month__9tEIV"
            ).text.strip()
            if current == target_label:
                return
            # "YYYY.MM" 고정폭 형식이라 문자열 비교로 방향 판단이 가능하다
            btn_id = (
                "swiperButtonNext" if current < target_label else "swiperButtonPrev"
            )
            btn = self._driver.find_element(By.ID, btn_id)
            if "disabled" in (btn.get_attribute("class") or ""):
                raise DriverError(
                    "change_schedule: calendar navigation disabled before "
                    "reaching %s (at %s)" % (target_label, current)
                )
            btn.click()
            time.sleep(CALENDAR_SETTLE_SEC)
        raise DriverError(
            "change_schedule: could not reach target month %s" % target_label
        )

    def _click_layer_day(self, yyyymmdd: str) -> None:
        """활성 슬라이드에서 목표 일(day) 버튼을 클릭한다(disabled 제외)."""
        day_num = _day_number(yyyymmdd)
        active_slide = self._driver.find_element(
            By.CSS_SELECTOR, ".swiper-slide-active"
        )
        buttons = active_slide.find_elements(
            By.CSS_SELECTOR, "button.EntCalendar_dateButton__6TxQi"
        )
        for button in buttons:
            if button.get_attribute("disabled"):
                continue
            numbers = button.find_elements(
                By.CSS_SELECTOR, "span.EntCalendar_number__5Ag2T"
            )
            if numbers and numbers[0].text.strip() == day_num:
                button.click()
                return
        raise DriverError(
            "change_schedule: day %s not found or not selectable in layer" % day_num
        )

    def _click_layer_time(self, time_hhmm: str) -> None:
        """목표 시각(12h AM/PM)으로 시작하는 TimeBlock 버튼을 클릭한다."""
        target = to_ampm(time_hhmm)
        self._wait.until(
            EC.presence_of_element_located(
                (By.CSS_SELECTOR, "button.TimeBlock_timeButton__79vnB")
            )
        )
        buttons = self._driver.find_elements(
            By.CSS_SELECTOR, "button.TimeBlock_timeButton__79vnB"
        )
        for button in buttons:
            if button.text.strip().startswith(target):
                button.click()
                return
        raise DriverError(
            "change_schedule: time %s (%s) not found among time buttons"
            % (time_hhmm, target)
        )

    def _click_apply_button(self) -> None:
        """변경하기 버튼(EntButton_primary)을 클릭한다."""
        buttons = self._driver.find_elements(
            By.CSS_SELECTOR, "button[class*='EntButton_primary']"
        )
        for button in buttons:
            if "변경하기" in button.text:
                if button.get_attribute("disabled"):
                    raise DriverError(
                        "change_schedule: apply button (변경하기) is disabled"
                    )
                button.click()
                return
        raise DriverError("change_schedule: apply button (변경하기) not found")

    def _wait_for_layer_closed(self) -> None:
        """레이어가 사라지고 좌석 circle이 다시 렌더링될 때까지 대기한다."""
        self._wait.until(
            EC.invisibility_of_element_located(
                (By.CSS_SELECTOR, "[class*='LayerDate_container']")
            )
        )
        self._wait.until(lambda d: d.find_elements(By.CSS_SELECTOR, "circle.js-seat"))

    def reload_target(self) -> None:
        """TOGGLE 날짜/시간으로 갔다가 TARGET으로 복귀해 좌석맵을 리로드한다."""
        self.change_schedule(self._cfg.toggle_date, self._cfg.toggle_time)
        self.change_schedule(self._cfg.date, self._cfg.time)

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
