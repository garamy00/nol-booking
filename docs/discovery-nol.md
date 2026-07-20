# NOL 티켓(인터파크) DOM 실측 결과 (2026-07-20)

대상: `https://tickets.interpark.com/goods/26005135` (연극 베니스의 상인)

## goods 페이지 — 날짜/회차/예매하기 (실측 완료)
좌측 사이드 패널에 관람일 캘린더 + 회차 + 예매하기.

### 캘린더 (jQuery datepicker 구조)
- 컨테이너: `.sideCalendar .datepicker-panel[data-view="days picker"]`
- 선택된 일자 표시: `.selectedData .date` (예: `2026.07.21 (화)`)
- 월 헤더/이동:
  - 현재 월: `li[data-view="month current"]` 텍스트 `2026. 07`
  - 다음 달: `li[data-view="month next"]` (`›`)
  - 이전 달: `li[data-view="month prev"]` (`‹`, 과거면 `.disabled`)
- 일자 셀: `ul[data-view="days"] > li`, 텍스트=일(day) 숫자
  - class `muted`: 다른 달 여백 (클릭 불가)
  - class `disabled`: 공연 없는 날 (클릭 불가)
  - class `picked`: 현재 선택된 날
  - class 없음(`""`): 선택 가능한 공연일

### 날짜 선택 절차 (예: 20260802)
1. 캘린더가 접혀 있으면 `.sideToggleBtn`(관람일 헤더) 클릭해 펼침.
2. `li[data-view="month current"]` 텍스트가 목표 월(`2026. 08`)이 아니면
   `li[data-view="month next"]` 클릭 반복(과도 방지 상한 둠).
3. `ul[data-view="days"] > li`에서 텍스트가 목표 일(`2`)이고 class에
   `muted`/`disabled` 없는 셀 클릭.

### 회차(시간)
- `.sideTimeTable .timeTableItem` / 라벨 `a.timeTableLabel`
  - 속성: `data-seq`(회차코드, 예 `012`), `data-text`(예 `1회 19:30`)
  - 텍스트: `N회 HH:MM`
- 목표 시간(예 `14:00`) 포함 라벨 클릭.

### 예매하기
- `a.sideBtn.is-primary` (텍스트 "예매하기") 클릭 → 새 예매창(팝업) 오픈.

## 예매창 — `/onestop/seat` (실측 완료)
`예매하기` 클릭 시 **새 창이 아니라 같은 탭**이 `https://tickets.interpark.com/onestop/seat`
로 이동한다(최신 NOL React SPA). 옛 인터파크 `ifrmSeat`/`SeatN` 구조는 **더 이상
안 씀**(inter.py는 구버전).

### 좌석 (SVG)
- 좌석맵: `.SeatMap_seatMap__...` 안 `<svg>`, 좌석은 `<circle class="SeatMap_seatSvg__... js-seat">`.
- **가용 판별**: `circle.js-seat` 중 `SeatMap_disabled__...` 클래스가 **없으면 예매가능**.
  - 셀렉터: `circle.js-seat:not([class*=SeatMap_disabled])`
  - 실측: 총 1321석 중 가용 254 / 매진(disabled) 1067.
- **등급 = 채우기 색상(fill)**:
  - VIP석 `#7c68ee` / OP석 `#1ca814` / R석 `#17b3ff` / S석 `#fb7e4e` / A석 `#a0d53f`
  - 매진석은 회색 `#edeff3`.
- **좌석 식별**: circle `id=seat_block_{goodsId}:{scheduleId}:{block}:{seq}`
  (예 `26005135:22000526:023:91`), 부모 `<g id="seat_block_{block}:{group}">`.
  좌표 `cx`,`cy` 보유.
- **주의: 사람이 읽는 구역/열/번호 라벨(title/aria/tooltip)이 없다.** hover 툴팁도 없음.
  → 매칭은 등급(색) + 연석(좌표)만 가능. 열=같은 `cy`, 인접=근접 `cx`.

### 상단/컨트롤
- 일정 카드: `[class*=scheduleCard]` — 선택 공연/일시 + 남은 세션 시간 표시
  (예 "2026.08.02(일) 2:00 PM ... 좌석 선택 시간 5:35"). 남은시간을 이 텍스트에서 파싱 가능.
- **일정변경**: `button.SubHeader_layerDateButton__vncqy` (클릭 시 날짜/회차 재선택 레이어).
- 등급 범례 토글: `button.SeatGradeLayer_toggleButton__ozikg`.
- 좌석선택 후 진행: `선택 완료`(EntButton) 버튼.
- 예매창 나가기: 브라우저 뒤로가기 → 확인 다이얼로그(구현 시 확정).

### 매칭 함의 (중요)
DOM이 구역/열 이름을 안 주므로, NOL 좌석 매칭은:
- 등급(fill 색상) 필터 + 연석 수(같은 cy 행에서 인접 cx 좌석 N개).
- "명명된 구역"(A/B/C구역) 매칭은 불가. 필요 시 좌표 영역(cx/cy 범위)으로 제한 가능.
