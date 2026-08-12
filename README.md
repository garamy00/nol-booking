# nol-booking

인터파크 NOL 예매창의 좌석을 폴링해, 목표 조건(등급·연석·층·구역·열)에 맞는 좌석이
나타나면 Telegram으로 알린다. **알림 전용**이며 자동 결제는 하지 않는다.

## 요구사항
- Python 3.9+
- Google Chrome 또는 Chromium
- Telegram 봇 토큰·chat_id

## 설치
```
python3 -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt
```

## 설정
1. `.env.example`을 `.env`로 복사해 `[NOL]`·`[TELEGRAM]`을 채운다. `[RUNTIME]`은 선택.
2. `nol_targets.example.yaml`을 `nol_targets.yaml`로 복사해 감시할 좌석 조건(등급/연석 등)을 적는다.

## 최초 로그인 (attach 모델)
이 도구는 **이미 로그인된 Chrome에 attach**한다. 새 창을 띄우거나 자동 로그인하지 않는다.
```
python3 nol_chrome.py        # 디버그 포트로 Chrome 실행 + NOL 페이지 열기
# 열린 Chrome에서 인터파크에 직접 로그인 (프로필은 chrome_profile에 영속)
```
Linux는 `NOL_CHROME_BINARY` 없이 chromium을 자동 탐지한다. 필요 시 지정 가능.

## 실행
```
python3 nol_monitor.py       # attach → 폴링 → 좌석 발견 시 Telegram 알림
```
종료: Ctrl-C / SIGTERM / Telegram `/stop`. 중복 실행은 자동 차단(단일 인스턴스 잠금).

## Telegram 제어 명령
- `/status` — 목표 회차·상태·연속 실패·마지막 성공
- `/pause` · `/resume` — 폴링 일시정지/재개
- `/stop` — 원격 종료

## 아키텍처
- `nol_chrome.py` — Chrome 런처(+`stop`)
- `nol_monitor.py` — 진입점·상태머신(메인 스레드, 드라이버 소유)
- `nol_driver.py` — 예매창 네비게이션(attach)
- `nol_seats.py` — React fiber 좌석 파싱·매칭
- `interpark_dom.py` — 인터파크 셀렉터·스크립트(빌드 변경 시 여기만 수정)
- `control.py` / `telegram_control.py` — 제어 상태·봇 수신(daemon 스레드)
- `config.py` / `notifier.py` — 설정 로딩 / Telegram 알림

## 한계·책임
- 인터파크 DOM에 의존하므로 사이트 변경 시 셀렉터 갱신이 필요하다.
- 최초 로그인은 수동이다.
- 상용 사이트 자동화 도구다. **사이트 약관 준수와 사용 결과는 사용자 책임**이며,
  이 프로젝트는 알림 목적의 예시로 제공된다.
