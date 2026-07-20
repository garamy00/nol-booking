# 국립극장(NTOK) 좌석 모니터 설계

작성일: 2026-07-20

## 목적
국립극장 예매 사이트(`booking.ntok.go.kr`)의 특정 공연에서, 지정한 좌석
타깃(층·구역·열·연석 수)이 예매 가능 상태로 나오는지 주기적으로 감시하고
발견 시 텔레그램으로 알린다. 실제 좌석 선택·결제는 사람이 직접 한다.

## 실행 방식 결정
- **완전 자동(직접 로그인)**: `.env`의 ID/PASSWORD로 스크립트가 직접
  로그인하고 URL+IDPERF+IDTIME 좌석 페이지로 이동해 폴링한다.
- Selenium(Chrome) 기반. 기존 `~/source/python` 예매 스크립트들과 동일 계열.
- 캡차 등으로 자동 로그인이 막히면 "이미 열린 Chrome에 붙기(원격 디버깅
  포트 9222)" 방식으로 대체한다(폴백).

## 전체 구조
30~60초(랜덤 지터)마다 로그인된 Selenium Chrome으로 좌석 페이지를
새로고침 → 좌석맵 DOM 파싱 → `targets.yaml` 대상과 매칭 → 직전 회차에 없던
신규 가용 좌석/연석 묶음이 있으면 텔레그램 알림. 발견해도 계속 감시한다.

```
booking/
├── .env                  # (기존) INI 형식
├── targets.yaml          # 감시 좌석 타깃 + 폴링 주기
├── monitor.py            # 메인 루프 (진입점)
├── config.py             # .env(configparser) + targets.yaml 로딩·검증
├── booking_driver.py     # Selenium: 로그인 → 좌석페이지 이동 → 좌석맵 파싱
├── notifier.py           # 텔레그램 전송 (requests.post)
└── requirements.txt
```

### 컴포넌트 책임
- **config.py**: `.env`를 `configparser`로, `targets.yaml`을 yaml로 읽어
  검증된 설정 객체(dataclass)로 반환. 누락 키·형식 오류를 시작 시점에 잡는다.
- **booking_driver.py**: Chrome 기동, 로그인, 좌석 페이지 진입, 좌석맵에서
  *예매 가능* 좌석 목록을 구조화해 반환(층·구역·열·좌석번호). 세션만료 시
  재로그인. 좌석맵이 iframe 안이면 iframe 전환 처리.
- **notifier.py**: 텔레그램 Bot API에 `requests.post`로 메시지 전송.
  의존성 최소화를 위해 python-telegram-bot 대신 requests 직접 사용.
- **monitor.py**: 위 세 컴포넌트를 엮는 폴링 루프 + 상태(dedupe) 관리.

## 설정 파일

### .env (기존, INI 형식 → configparser)
```
[NTOK]
URL=https://booking.ntok.go.kr/Pages/kr/Perf/Sale/PerfSaleProcess.aspx
IDPERF=267114
IDTIME=81857
ID=xxx
PASSWORD=xxx
[TELEGRAM]
TELEGRAM_TOKEN="xxxx"
CHAT_ID="xxxx"
```

### targets.yaml
```yaml
targets:
  - floor: "1F"          # 층
    section: "B"         # 구역 (A/B/C)
    rows: [1, 2, 3, 4, 5]   # 감시할 열(또는 좌석) 범위
    consecutive: 2       # 나란히 붙은 좌석 N개 동시 가용 시에만 알림 (기본 1 = 낱개 허용)
poll:
  interval_min: 30       # 초
  interval_max: 60       # 이 사이 랜덤 지터로 봇 탐지 완화
```

좌석 식별 규칙(층·구역·열·번호가 DOM에 어떻게 인코딩되는지)은 실제 페이지를
열어봐야 확정된다. 그에 맞춰 targets.yaml 필드를 최종 조정한다.

## 동작 흐름 (monitor.py)
1. 설정 로드 → Chrome 기동 → ID/PASSWORD 로그인 → 좌석 페이지 진입.
2. 루프: 새로고침(또는 "다시조회" 클릭) → 좌석맵에서 예매 가능 좌석 수집 →
   타깃 구역·열로 필터.
3. 연석 매칭: 타깃 구역·열의 가용 좌석을 좌석번호 순 정렬 → 연속으로
   `consecutive`개 이상 이어지는 묶음을 찾는다. 예: 2연석이면 `[7,8]`은 알림,
   `[7,12]`는 무시.
4. dedupe(묶음 단위): 직전 회차에 없던 신규 연석 묶음만 텔레그램 알림.
   같은 묶음이 계속 살아있으면 반복 알림하지 않고, 새 묶음이 뜨면 알린다.
5. 알림 문구에 찾은 묶음을 표기(예: `1F B열 7-8번`).
6. 30~60초 지터 대기 후 반복. 발견해도 계속 감시.

## 에러 처리
- 로그인 실패·세션만료·페이지 구조 변화·Chrome 다운: 로그(ERROR) +
  텔레그램으로 "모니터 이상" 통지. 세션만료류는 재로그인 시도.
- 가용 좌석 0건은 정상 상태이며 조용히 다음 루프로.
- 설정 오류(누락 키·잘못된 형식)는 시작 시점에 즉시 실패시켜 알린다.

## 미해결/구현 시 확인 사항
- **로그인 폼 필드 ID·캡차 유무**: 미지. 캡차가 있으면 완전 자동이 막히므로
  "열린 Chrome에 붙기" 폴백으로 전환.
- **좌석맵 iframe 여부**: interpark는 iframe을 썼다. 국립극장도 그럴 수 있어
  구현 시 확인.
- **가용/매진 판별 방식**: X표/노란칸이 클래스·이미지·색상 중 무엇으로
  구분되는지 실제 DOM에서 확인.
- **좌석번호 인접 규칙**: 번호가 좌→우로 증가하는지 등 "연속"의 정의를 실제
  좌석맵에서 확정.

## 비범위 (YAGNI)
- 자동 좌석 선택·결제 없음(알림까지만).
- 다중 공연 동시 감시 없음(단일 IDPERF/IDTIME).
- GUI 없음(콘솔 로그 + 텔레그램).
