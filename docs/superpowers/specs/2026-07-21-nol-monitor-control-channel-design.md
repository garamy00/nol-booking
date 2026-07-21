# NOL 모니터 운영 하드닝 + Telegram 제어 채널 설계

작성일: 2026-07-21

## 배경

DGX 상주 운영을 위해 두 부류의 기능을 추가한다.

- **A. 운영 하드닝**: (A-1) SIGTERM/SIGINT graceful 종료, (A-2) 단일 인스턴스 잠금.
- **C. Telegram 양방향 제어**: `/status` `/pause` `/resume` `/stop` 명령으로 실행 중인
  모니터를 원격 조회·제어.

현재 `nol_monitor.main()`은 모니터 루프를 블로킹으로 돌리고 `KeyboardInterrupt`만
처리한다([nol_monitor.py](../../../nol_monitor.py)). SIGTERM으로는 깔끔히 종료되지
않고, 중복 실행 방지도 없으며, 실행 중 상태를 밖에서 볼 방법이 없다.

참고 패턴: `~/source/python/stock/get_new.py`의 "봇 명령 → 공유 상태 → worker 루프"
구조. 단, 봇 수신은 새 의존성 없이 `requests` getUpdates 롱폴링으로 구현한다
(python-telegram-bot 미사용).

## 목표 / 비목표

**목표**
- SIGTERM/SIGINT 수신 시 드라이버를 정상 해제하고 종료한다.
- 같은 프로필로 두 번 실행되면 두 번째 인스턴스는 즉시 종료한다.
- Telegram에서 `/status`(상태 조회), `/pause`·`/resume`(폴링 일시정지/재개),
  `/stop`(원격 종료)을 처리한다.
- Selenium 드라이버는 **모니터 스레드만** 접근한다(동시성 안전).

**비목표**
- 좌석 발견 아웃바운드 알림 방식 변경(기존 `notifier.send_telegram` 유지).
- 자동 예매, `/reload` 등 이번에 선택되지 않은 명령.
- Windows 지원(fcntl 사용, Mac·Linux 대상).

## 아키텍처

```
main thread ──────────────► 모니터 루프(_run_loop, Selenium 드라이버 소유)
   │                          ▲   ▲
   │ 시작 시 daemon 스레드     │   │ 읽기: should_stop / wait_if_paused / mark_*
   └──► telegram_control.serve ┘   │
        (getUpdates 롱폴링)      ControlState (thread-safe)
        명령 → control 플래그/상태 조작, 응답 전송
```

- **모니터 루프는 메인 스레드**에서 돈다(기존 구조 유지 → KeyboardInterrupt·시그널이
  자연스럽게 도달). **봇 수신 루프는 daemon 스레드**에서 돈다(프로세스 종료 시 함께
  소멸, 별도 join 불필요).
- 두 스레드는 **`ControlState`**로만 통신한다. 봇 스레드는 드라이버를 절대 만지지
  않고 플래그 설정·상태 읽기만 한다.

## 구성 요소

### 새 파일: `control.py` — ControlState

스레드 안전한 제어·상태 객체.

- 내부: `_stop: threading.Event`, `_paused: threading.Event`, `_lock: threading.Lock`,
  상태 필드(target_date/time, state 문자열, last_success_ts, consecutive_failures,
  started_ts).
- API:
  - `request_stop()` / `should_stop() -> bool`
  - `pause()` / `resume()` / `is_paused() -> bool`
  - `wait_if_paused(poll: float = 0.5) -> None` — 일시정지 동안 `poll`초 간격으로
    깨어나며 대기하되 `should_stop()`이면 즉시 반환.
  - `set_state(state: str)` — "entering" | "polling" | "paused" | "holding".
  - `mark_success() -> None` — last_success_ts 갱신, consecutive_failures=0.
  - `mark_failure() -> int` — consecutive_failures 증가 후 값 반환(알림 임계 판단용).
  - `snapshot() -> ControlSnapshot` — lock 하에 상태 사본(dataclass) 반환.
- 시각 필드는 표시용이므로 `time.time()`(wall clock)을 쓴다.

### 새 파일: `telegram_control.py` — 명령 수신 루프

- `serve(cfg: TelegramConfig, control: ControlState) -> None` — daemon 스레드 진입점.
  getUpdates(offset, long-poll timeout≈20s)를 반복하며, **설정된 chat_id의 메시지만**
  처리(그 외 무시 = 인가). `control.should_stop()`이면 반환.
- 명령 디스패치(순수 함수로 분리해 테스트 가능하게):
  `dispatch(command: str, control: ControlState) -> str` — control을 조작하고 응답
  텍스트를 반환.
  - `/status` → `snapshot()`을 사람이 읽는 텍스트로 포맷.
  - `/pause` → `control.pause()`, "일시정지됨".
  - `/resume` → `control.resume()`, "재개됨".
  - `/stop` → `control.request_stop()`, "종료합니다".
  - 알 수 없는 명령 → 사용법 안내.
- 응답 전송·getUpdates는 `requests` 사용. 네트워크 예외는 로깅 후 다음 루프로 계속
  (봇 오류가 모니터를 죽이지 않는다).
- `/status` 포맷 예:
  ```
  [NOL 상태]
  목표: 2026-08-02 14:00
  상태: 폴링 중
  연속 실패: 0
  마지막 성공: 15:30:12
  ```

### `nol_monitor.py` 변경

- **단일 인스턴스 잠금**: `_acquire_single_instance_lock() -> IO` — 프로젝트 경로의
  `.nol_monitor.lock`을 `fcntl.flock(LOCK_EX | LOCK_NB)`로 잠근다. 실패 시
  "already running" 로그 후 `sys.exit(1)`. 파일 핸들은 프로세스 수명 동안 열어 둔다.
- **시그널 핸들러**: `main()`에서 SIGTERM·SIGINT를 `control.request_stop()`으로 연결.
  (KeyboardInterrupt 경로도 유지하되 stop으로 수렴)
- **스레드 기동**: `ControlState` 생성 → 봇 daemon 스레드 시작
  (`threading.Thread(target=telegram_control.serve, args=(cfg.telegram, control),
  daemon=True)`) → `_run_loop(driver, cfg, state, notify, control)` 메인 스레드 실행.
- **루프에 control 반영**:
  - `_run_loop`/`_poll_until_hold_or_expiry`가 `control`을 받아 경계마다
    `control.should_stop()` 확인 → True면 반환. 폴링 경계에서 `control.wait_if_paused()`.
  - 연속 실패 카운트를 `control.mark_failure()`/`mark_success()`로 이관(상태 표시와
    알림 임계 `FAILURE_ALERT_THRESHOLD` 공유). 진입/폴링/홀드 시 `set_state()`.
- **정리**: `finally`에서 `driver.close()` + 잠금 파일 핸들 해제.

## 데이터 흐름

- 명령 수신: Telegram → getUpdates → `serve` → `dispatch` → ControlState 변경 → 응답.
- 상태 표출: 모니터 루프가 진행하며 `set_state`/`mark_*` → `/status`가 `snapshot`을 읽어 응답.
- 종료: SIGTERM/`/stop`/Ctrl-C → `request_stop()` → 모니터 루프가 감지해 반환 →
  `driver.close()` → 프로세스 종료(봇 daemon 스레드 동반 소멸).

## 에러 처리

- 봇 스레드의 네트워크·파싱 예외는 삼켜서 로깅만 하고 계속(모니터 영향 없음).
- 잠금 획득 실패는 명시적 `sys.exit(1)`.
- 인가되지 않은 chat_id 메시지는 무시(응답도 하지 않음).
- 드라이버 정리는 종료 사유와 무관하게 `finally`에서 보장.

## 테스트 (실동작 검증 우선)

- `control.py`: pause→wait_if_paused가 블로킹, resume 시 해제, stop 시 즉시 반환;
  mark_failure 누적/mark_success 리셋; snapshot 필드 정확성.
- `telegram_control.dispatch`: 각 명령이 control을 올바르게 바꾸고 기대 응답 텍스트
  반환; 알 수 없는 명령은 사용법; `/status`가 snapshot을 포맷.
- 인가: 설정 외 chat_id 업데이트는 처리되지 않음(파서 단위 테스트).
- 단일 인스턴스 잠금: 같은 파일에 대해 두 번째 flock이 실패.
- `_run_loop`: `should_stop()`이 True면 루프가 반환; 일시정지 상태에서 seat check가
  일어나지 않음(기존 run_loop 테스트에 control 스텁 확장).
- 시그널 핸들러 함수가 `control`에 stop을 set.

## 설계 한계

- fcntl 기반이라 Windows 미지원(대상 아님).
- pause 중 interpark 세션은 만료될 수 있고, resume 시 다음 사이클에서 재진입한다
  (기존 재진입 경로 재사용).
- getUpdates 롱폴링 타임아웃(≈20s)만큼 `/stop`·SIGTERM에 대한 봇 스레드 반응이
  늦을 수 있으나, 모니터 루프(메인)는 즉시 종료되고 봇은 daemon이라 함께 소멸하므로
  실제 종료는 지연되지 않는다.
