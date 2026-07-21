import pytest
from selenium.common.exceptions import (
    ElementClickInterceptedException,
    ElementNotInteractableException,
)

import nol_monitor
from config import NolAppConfig, NolConfig, NolTarget, PollConfig, TelegramConfig
from control import ControlState
from errors import DriverError
from nol_driver import NolDriver, parse_remaining, to_ampm
from nol_monitor import check_once
from nol_seats import NolSeat
from state import SeatState


# to_ampm


@pytest.mark.parametrize(
    "hhmm, expected",
    [
        ("14:00", "2:00 PM"),
        ("09:30", "9:30 AM"),
        ("00:00", "12:00 AM"),
        ("12:00", "12:00 PM"),
        ("15:00", "3:00 PM"),
        ("19:30", "7:30 PM"),
    ],
)
def test_to_ampm_converts_24h_to_12h_with_period(hhmm, expected):
    assert to_ampm(hhmm) == expected


# parse_remaining


def test_parse_remaining_plain_colon_returns_total_seconds():
    assert parse_remaining("좌석 선택 시간 5:35") == 335


def test_parse_remaining_spaced_colon_returns_total_seconds():
    assert parse_remaining("좌석 선택 시간 5 : 35") == 335


def test_parse_remaining_missing_pattern_returns_none():
    assert parse_remaining("2026.08.02(일) 2:00 PM VIP석 73") is None


# check_once (nol_monitor)


class FakeDriver:
    def __init__(self, seats, on_target=True):
        self._seats = seats
        self._on_target = on_target

    def is_on_target_schedule(self):
        return self._on_target

    def read_available_seats(self):
        return self._seats


def _cfg(consecutive=2):
    return NolAppConfig(
        nol=NolConfig(
            url="https://tickets.interpark.com/goods",
            goods_id="26005135",
            date="20260802",
            time="14:00",
            toggle_date="20260805",
            toggle_time="15:00",
        ),
        telegram=TelegramConfig("t", "c"),
        targets=[NolTarget(grade="R석", consecutive=consecutive)],
        poll=PollConfig(30, 60),
    )


def test_check_once_notifies_new_consecutive_group():
    sent = []
    seats = [
        NolSeat(section="A", row=15, number=5, grade="R석", seat_id="s1"),
        NolSeat(section="A", row=15, number=6, grade="R석", seat_id="s2"),
    ]
    driver = FakeDriver(seats)
    fresh = check_once(driver, _cfg(), SeatState(), notify=sent.append)
    assert len(fresh) == 1
    assert len(sent) == 1
    assert "R석" in sent[0]


def test_check_once_no_seats_returns_empty_and_no_notify():
    sent = []
    fresh = check_once(FakeDriver([]), _cfg(), SeatState(), notify=sent.append)
    assert fresh == []
    assert sent == []


def test_check_once_same_group_twice_notifies_once():
    sent = []
    seats = [
        NolSeat(section="A", row=15, number=5, grade="R석", seat_id="s1"),
        NolSeat(section="A", row=15, number=6, grade="R석", seat_id="s2"),
    ]
    state = SeatState()
    cfg = _cfg()
    check_once(FakeDriver(seats), cfg, state, notify=sent.append)
    check_once(FakeDriver(seats), cfg, state, notify=sent.append)
    assert len(sent) == 1


def test_check_once_skips_match_when_not_on_target_schedule():
    # 잘못된 날짜(예 토글용 날짜)에 머물러 있으면 좌석이 매칭되어도 알리지 않는다
    sent = []
    seats = [
        NolSeat(section="A", row=15, number=5, grade="R석", seat_id="s1"),
        NolSeat(section="A", row=15, number=6, grade="R석", seat_id="s2"),
    ]
    driver = FakeDriver(seats, on_target=False)
    fresh = check_once(driver, _cfg(), SeatState(), notify=sent.append)
    assert fresh == []
    assert sent == []


# _click_book_button (뷰포트 밖 버튼 처리)


class _FakeButton:
    """네이티브 click을 흉내내는 가짜 예매 버튼."""

    def __init__(self, intercept_native: bool):
        self._intercept = intercept_native
        self.native_click_calls = 0

    def click(self):
        self.native_click_calls += 1
        if self._intercept:
            raise ElementClickInterceptedException("blocked")


class _FakeSeleniumDriver:
    """find_element/execute_script만 흉내내는 최소 Selenium 드라이버 스텁."""

    def __init__(self, button):
        self._button = button
        self.scripts: list[str] = []

    def find_element(self, by, selector):
        return self._button

    def execute_script(self, script, *args):
        self.scripts.append(script)


def _driver_with(button) -> NolDriver:
    driver = NolDriver(_cfg().nol)
    driver._driver = _FakeSeleniumDriver(button)
    return driver


def test_click_book_button_scrolls_into_view_before_native_click():
    button = _FakeButton(intercept_native=False)
    driver = _driver_with(button)

    driver._click_book_button()

    assert button.native_click_calls == 1
    assert any("scrollIntoView" in s for s in driver._driver.scripts)


def test_click_book_button_falls_back_to_js_click_when_intercepted():
    # 스크롤 후에도 뷰포트 밖/가로막힘이면 JS 클릭으로 통과해 예외 없이 진입한다
    button = _FakeButton(intercept_native=True)
    driver = _driver_with(button)

    driver._click_book_button()

    assert any("scrollIntoView" in s for s in driver._driver.scripts)
    assert any(".click()" in s for s in driver._driver.scripts)


# _ensure_desktop_window (좁은 창에서 예매 버튼 미렌더링 방지)


class _FakeWindowDriver:
    """창 크기 조회/설정만 흉내내는 스텁."""

    def __init__(self, width: int, height: int):
        self._size = {"width": width, "height": height}
        self.set_calls: list[tuple[int, int]] = []

    def get_window_size(self):
        return self._size

    def set_window_size(self, width, height):
        self.set_calls.append((width, height))


def test_ensure_desktop_window_enlarges_narrow_window():
    # 좁은 창은 데스크톱 폭 이상으로 확대되어야 한다(예매 버튼이 렌더링되도록)
    driver = NolDriver(_cfg().nol)
    fake = _FakeWindowDriver(800, 600)

    driver._ensure_desktop_window(fake)

    assert len(fake.set_calls) == 1
    width, _height = fake.set_calls[0]
    assert width >= 1440


def test_ensure_desktop_window_leaves_large_window_untouched():
    driver = NolDriver(_cfg().nol)
    fake = _FakeWindowDriver(1920, 1080)

    driver._ensure_desktop_window(fake)

    assert fake.set_calls == []


# _safe_click (뷰포트 밖/가로막힘 클릭의 공통 처리)


class _ClickTargetDriver:
    """execute_script(scrollIntoView/JS click)를 기록하는 스텁."""

    def __init__(self):
        self.scripts: list[str] = []

    def execute_script(self, script, *args):
        self.scripts.append(script)


class _StubElement:
    def __init__(self, raise_exc=None):
        self._raise_exc = raise_exc
        self.native_click_calls = 0

    def click(self):
        self.native_click_calls += 1
        if self._raise_exc is not None:
            raise self._raise_exc


def _driver_for_click() -> NolDriver:
    driver = NolDriver(_cfg().nol)
    driver._driver = _ClickTargetDriver()
    return driver


def test_safe_click_scrolls_then_native_clicks_when_unobstructed():
    driver = _driver_for_click()
    element = _StubElement()

    driver._safe_click(element)

    assert element.native_click_calls == 1
    assert any("scrollIntoView" in s for s in driver._driver.scripts)
    # 네이티브 클릭이 성공하면 JS 폴백 클릭은 없어야 한다
    assert not any(".click()" in s for s in driver._driver.scripts)


@pytest.mark.parametrize(
    "exc",
    [
        ElementClickInterceptedException("intercepted"),
        ElementNotInteractableException("not interactable"),
    ],
)
def test_safe_click_falls_back_to_js_click_on_click_failures(exc):
    driver = _driver_for_click()
    element = _StubElement(raise_exc=exc)

    driver._safe_click(element)  # 예외 없이 통과해야 한다

    assert any("scrollIntoView" in s for s in driver._driver.scripts)
    assert any(".click()" in s for s in driver._driver.scripts)


# _run_loop 실패 알림 스로틀링 (일시적 실패 스팸 방지)


class _FlakyEntryDriver:
    """enter/reenter가 지정 횟수만큼 실패한 뒤 성공하는 드라이버 스텁."""

    def __init__(self, fail_times: int):
        self._fail_times = fail_times
        self.attempts = 0

    def enter_booking(self):
        self.attempts += 1
        if self.attempts <= self._fail_times:
            raise DriverError("entry boom")

    def reenter(self):
        self.enter_booking()


def _collect_run_loop_notifications(driver, monkeypatch) -> list[str]:
    sent: list[str] = []
    control = ControlState("20260802", "14:00")
    # 진입 성공 즉시 홀드로 처리해 바깥 루프를 종료시킨다
    monkeypatch.setattr(nol_monitor, "_poll_until_hold_or_expiry", lambda *a: True)
    monkeypatch.setattr(nol_monitor.time, "sleep", lambda _s: None)
    monkeypatch.setattr(ControlState, "wait_for_stop", lambda self, t: False)
    nol_monitor._run_loop(driver, _cfg(), SeatState(), sent.append, control)
    return sent


def test_run_loop_stays_silent_on_transient_failures(monkeypatch):
    # 임계 미만(자가복구 범위)의 연속 실패는 알림을 보내지 않는다
    driver = _FlakyEntryDriver(fail_times=nol_monitor.FAILURE_ALERT_THRESHOLD - 1)

    sent = _collect_run_loop_notifications(driver, monkeypatch)

    assert sent == []


def test_run_loop_alerts_once_then_recovers_on_sustained_failure(monkeypatch):
    # 임계 도달 시 경보 1회, 이후 진입 성공 시 복구 알림 1회
    driver = _FlakyEntryDriver(fail_times=nol_monitor.FAILURE_ALERT_THRESHOLD)

    sent = _collect_run_loop_notifications(driver, monkeypatch)

    assert len(sent) == 2
    assert "실패" in sent[0]
    assert "복구" in sent[1]


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
