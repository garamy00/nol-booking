# nol-booking 정리·범용화 설계

작성일: 2026-07-21

## 배경

현 저장소(`booking`)는 **NOL/인터파크 좌석 모니터**와 예전 **국립극장(NTOK) 모니터**가
섞인 개인 멀티툴이다. 이를 NOL 전용 공개 가능 패키지로 정리한다.

결정 사항(사용자 확정):
- LICENSE: 지금은 넣지 않음(추후 결정).
- 범용성 개선: Linux Chrome 자동 탐지 + 인터파크 DOM 상수 중앙화 + 주요 런타임 상수 설정화(모두).
- 런타임 튜너블은 `.env`에 둔다(YAML 아님).
- git 이력은 그대로 두고 현재 커밋에서 파일만 삭제.

## 목표 / 비목표

**목표**
- NTOK 관련 소스·설정·테스트 완전 제거 → NOL 전용.
- 흩어진 인터파크 셀렉터·색상·fiber를 한 모듈로 모아 유지보수성 향상.
- 디버그 포트·창 크기·세션 마진 등 런타임 상수를 `.env` `[RUNTIME]`로 노출(기본값 유지).
- Linux에서 Chrome/Chromium 자동 탐지(수동 `NOL_CHROME_BINARY` 불필요).
- README·`.env.example`·pyproject 메타데이터로 패키지 완성.
- 디렉토리 `booking` → `nol-booking` 리네임.

**비목표**
- LICENSE 추가, git 이력 재작성.
- 자동 예매(결제) 기능. 알림 전용 유지.
- 인터파크 스크래핑의 근본적 취약성 제거(불가능 — DOM 의존).

## 작업 분해 (구현 순서)

### 1. NTOK 제거 (깨끗한 베이스)
- **삭제**: `monitor.py`, `booking_driver.py`, `seats.py`, `targets.yaml`,
  `tests/test_config.py`, `tests/test_monitor.py`, `tests/test_seats.py`,
  `tests/test_parser.py`.
- **`config.py`**: `NtokConfig`·`Target`·`AppConfig`·`load_config`·`_load_targets` 제거.
  NOL이 쓰는 `TelegramConfig`·`PollConfig`·`_require`·`_strip_quotes`(NOL 사용분)·
  `NolConfig`·`NolTarget`·`NolAppConfig`·`load_nol_config`·`_parse_nol_*`만 유지.
- **`state.py`**: `from seats import SeatGroup` → `from nol_seats import NolSeatGroup`,
  애노테이션 교체(런타임 duck-typed라 동작 동일).
- **`tests/test_state.py`**: `seats.SeatGroup` 대신 `NolSeatGroup` 사용하도록 갱신.
- 검증: 남은 전체 테스트 통과 = NTOK 삭제가 NOL 동작 무영향.

### 2. 인터파크 DOM 상수 중앙화 (`interpark_dom.py` 신규)
- `nol_driver.py`·`nol_seats.py`의 인터파크 특화 문자열을 한 모듈로 추출(순수 이동,
  동작 무변경): CSS 셀렉터(`onestop/seat`, `a.sideBtn.is-primary`,
  `[class*=SubHeader_layerDateButton]`, `[class*=EntCalendar_month]`, `#swiperButtonNext`
  등), React fiber 좌석 읽기 JS, 등급 fill 색상 매핑(VIP `#7c68ee` 등).
- 모듈 상단에 "인터파크 빌드 변경 시 이 파일만 갱신" 주석.
- 검증: 기존 nol_driver/nol_seats 테스트 그대로 통과(상수만 이동).

### 3. 런타임 상수 설정화 (`.env` `[RUNTIME]`)
- **`.env` 새 섹션(모두 선택, 미지정 시 기본값)**:
  ```
  [RUNTIME]
  DEBUG_PORT=9222
  WINDOW_WIDTH=1440
  WINDOW_HEIGHT=1000
  SAFETY_SECONDS=40
  MAX_SESSION_SECONDS=540
  REENTRY_BACKOFF_SECONDS=30
  FAILURE_ALERT_THRESHOLD=5
  ```
- **`config.py`**: `RuntimeConfig` dataclass + `_load_runtime(parser)`(기본값 적용),
  `NolAppConfig`에 `runtime: RuntimeConfig` 추가.
- **`nol_monitor.py`**: 모듈 상수(SAFETY/MAX_SESSION/REENTRY/FAILURE_ALERT) 대신
  `cfg.runtime` 값 사용. `NolDriver`에 runtime 전달.
- **`nol_driver.py`**: 하드코딩된 디버그 포트(`127.0.0.1:9222`)·`MIN_DESKTOP_*`를
  runtime 값으로. 기본 상수는 config 기본값으로 이전.
- **`nol_chrome.py`**: `[RUNTIME] DEBUG_PORT`를 최소 읽기(현재 `_read_goods_url`와 동일
  방식)로 참조해 `nol_driver`와 포트 일치. 미지정 시 기본 9222.
- 검증: 포트/창/마진이 `.env`로 바뀌는지 단위 테스트, 미지정 시 기본값.

### 4. Linux Chrome 자동 탐지 (`nol_chrome.py`)
- `_chrome_binary()`: `NOL_CHROME_BINARY` 우선, 없으면 플랫폼별 탐지 —
  Linux는 `google-chrome`/`google-chrome-stable`/`chromium`/`chromium-browser`를
  `shutil.which`로 순서 검색, macOS는 기존 앱 경로. 못 찾으면 `LauncherError`.
- 검증: `shutil.which`를 스텁해 Linux 후보 탐지·전부 없을 때 에러를 단위 테스트.

### 5. 패키지 완성
- **`README.md`**: 소개, 요구사항(Python 3.9+, Chrome/Chromium), 설치(venv +
  requirements), 설정(`.env`/`nol_targets.yaml`), 최초 수동 로그인(attach 모델),
  실행(`nol_chrome.py` → `nol_monitor.py`), Telegram 제어 명령, 아키텍처 개요,
  **한계·ToS 책임 고지**(알림 전용, 자동 결제 없음, 사이트 약관 준수 사용자 책임).
- **`.env.example`**: `[NOL]`·`[TELEGRAM]`·`[RUNTIME]` 자리표시자(비밀 없음).
- **`pyproject.toml`**: `[project]` 메타데이터(name=`nol-booking`, version, description,
  requires-python, dependencies=requirements 반영). 기존 `[tool.ruff]`/`[tool.pytest]` 유지.

### 6. 디렉토리 리네임
- 코드 완료 후 `~/source/python/booking` → `~/source/python/nol-booking`
  (파일시스템 이동, git 이력 유지). 이후 경로 기준으로 동작 확인.

## `.env` 실파일 처리
- 실제 `.env`에서 `[NTOK]` 섹션 제거, `[RUNTIME]`는 선택(기본값이 있으므로 없어도 됨).
- `.env`가 비밀(텔레그램 토큰)을 포함하므로 편집만 하고 내용은 노출하지 않는다. 접근이
  막히면 사용자 안내로 전환.

## 에러 처리 / 테스트
- 각 작업은 독립 테스트로 무변경(1·2) 또는 신동작(3·4)을 검증.
- Linux 탐지·runtime 파싱은 스텁/tmp `.env`로 실동작 검증.
- 삭제 작업(1)은 남은 전체 스위트 통과로 회귀 없음 증명.

## 설계 한계
- 인터파크 DOM 의존은 남는다(중앙화로 수정 지점만 좁힘).
- attach + 수동 로그인 모델 유지(turnkey 아님).
- git 이력에 NTOK 흔적 잔존(비밀은 없음).
