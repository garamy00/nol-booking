"""인터파크 NOL 예매창의 DOM 셀렉터·React fiber 스크립트 모음.

인터파크가 프론트엔드 빌드를 바꾸면(클래스 접두어·구조·fiber 키) 이 파일만
갱신하면 된다. 나머지 코드는 여기 상수만 참조한다.
"""

from __future__ import annotations

# 페이지 식별
SEAT_PAGE_MARKER = "onestop/seat"
SEAT_CIRCLE = "circle.js-seat"

# 헤더 로그인 상태 판별: '로그아웃' 링크가 있으면 로그인 상태('in'),
# '로그인' 링크만 있으면 미로그인('out'), 둘 다 없으면 판단 불가('unknown').
# 미로그인일 때만 확정하고 그 외엔 unknown으로 폴백해 오탐을 피한다.
LOGIN_STATE_JS = """
const texts = [...document.querySelectorAll('a, button')]
    .map((e) => (e.innerText || e.textContent || '').trim());
if (texts.includes('로그아웃')) return 'in';
if (texts.includes('로그인')) return 'out';
return 'unknown';
"""

# goods 페이지 캘린더
GOODS_DAYS = "ul[data-view='days'] > li"
GOODS_SIDE_TOGGLE = ".sideToggleBtn"
GOODS_MONTH_CURRENT = "li[data-view='month current']"
GOODS_MONTH_NEXT = "li[data-view='month next']"
GOODS_TIME_LABEL = "a.timeTableLabel"
GOODS_BOOK_BUTTON = "a.sideBtn.is-primary"

# 예매창 상단/타이머
SCHEDULE_DATE_QUERY = "[class*=scheduleDate]"
SESSION_TIMER_QUERY = "[class*=SessionDwellTimer]"

# 일정변경 레이어
LAYER_DATE_BUTTON = "button[class*='SubHeader_layerDateButton']"
LAYER_CONTAINER = "[class*='LayerDate_container']"
LAYER_MONTH = "[class*='EntCalendar_month']"
LAYER_SWIPER_ACTIVE = ".swiper-slide-active"
LAYER_DATE_ITEM_BUTTON = "button[class*='EntCalendar_dateButton']"
LAYER_DATE_NUMBER = "span[class*='EntCalendar_number']"
LAYER_TIME_BUTTON = "button[class*='TimeBlock_timeButton']"
LAYER_APPLY_BUTTON = "button[class*='EntButton_primary']"
LAYER_SWIPER_NEXT_ID = "swiperButtonNext"
LAYER_SWIPER_PREV_ID = "swiperButtonPrev"

# 좌석 circle의 React fiber에서 seat 메타데이터를 읽는 스크립트
READ_SEATS_JS = """
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
