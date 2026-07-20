# 국립극장 좌석 페이지 DOM 실측 결과 (2026-07-20)

대상: `PerfSaleProcess.aspx?IdPerf=267114&IdTime=...` (STEP 02 좌석선택)

## 페이지 구조
- 좌석맵은 **iframe 안**에 렌더링된다.
  - iframe: `<iframe name="ifrHSD" src=".../PerfSaleHtmlSeat.aspx?idtime=...&idhall=...&idperf=...">`
  - 셀렉터: `iframe[name=ifrHSD]`
- iframe 안의 `<svg>`는 **배경 도면 이미지**일 뿐, 좌석이 아니다.
- 실제 좌석: `<div id="divSeatArray">` 밑의 **절대위치 div들** (공연당 ~750개).

## 좌석 엘리먼트
```html
<div class="s86" id="t400011" name="tk" value="400011"
     title="[OP석] 1층 OP구역 1열 01번 " grade="OP석" price="99,000원"
     style="left:180px; top:200px; position:absolute; ..."></div>
```
- `class`: 등급 스프라이트(가용 아님). s86=OP석(ic_seat86.gif), s61=휠체어석, s2=VIP석. **매진석은 전부 s86(회색)로 렌더**.
- `value`: 좌석 내부 ID.
- `title`/`grade`/`price`: **예매 가능한 좌석에만** 채워진다.

## 가용 판별 규칙 (확정)
**`title` 속성이 비어있지 않으면 = 예매 가능. 없으면 = 매진.**
- 실측: 전체 750석 중 titled 87석(가용), bare 663석(매진).
- 셀렉터: `#divSeatArray > div[title]`
- class는 무시(등급용). title 유무만 본다.

## title 파싱
형식: `[{등급}] {N}층 {구역}구역 {M}열 {K}번`
정규식:
```
^\[(?P<grade>[^\]]+)\]\s*(?P<floor>\d+)층\s*(?P<section>\S+?)구역\s*(?P<row>\d+)열\s*(?P<num>\d+)번
```
예: `[OP석] 1층 OP구역 1열 01번` → grade=OP석, floor=1, section=OP, row=1, num=01
- 정규화: floor `1`→`1F`, section은 그대로(`OP`/`A`/`B`/`C`). → targets.yaml의 `1F`,`B`와 매칭.

## 새로고침(폴링)
- iframe 리로드로 좌석 재수집: `document.querySelector('iframe[name=ifrHSD]').contentWindow.location.reload()`
- 리로드 후 `#divSeatArray`가 다시 채워질 때까지 대기(childElementCount>0) 후 재수집.
- 좌측 상단 "다시 선택"(`#btnNRSIReset`)은 좌석초기화용 — 폴링에 쓰지 않음.

## 로그인
- 이번 실측은 **사용자가 디버그 포트 Chrome에서 직접 로그인**한 세션에 attach해 수행.
- 로그인 폼 셀렉터는 별도 조사하지 않음(자동 로그인 대신 attach 방식 검토 — 아래 결정 참조).
- chrome_profile(user-data-dir) 프로필에 로그인 세션이 지속됨.
