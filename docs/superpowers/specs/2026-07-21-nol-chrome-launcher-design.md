# NOL Chrome 런처 설계

작성일: 2026-07-21

## 배경

`nol_monitor.py`는 `--remote-debugging-port=9222`로 이미 떠 있는 Chrome에 attach하는 방식이다
([nol_driver.py](../../../nol_driver.py) `attach()`). Chrome이 안 떠 있으면 `DriverError`로 실패하고,
사용자가 매번 아래 명령을 손으로 실행해야 한다.

```
/Applications/Google\ Chrome.app/Contents/MacOS/Google\ Chrome \
  --remote-debugging-port=9222 \
  --user-data-dir="$HOME/source/python/booking/chrome_profile"
```

이 수동 단계를 없애기 위해, 디버그 포트로 떠 있는 Chrome이 없으면 전용 프로필로 자동 실행하고
NOL goods 페이지까지 여는 런처를 추가한다.

## 목표 / 비목표

**목표**
- 디버그 포트(9222) Chrome이 없으면 전용 프로필(`chrome_profile`)로 새로 띄운다.
- 자동 실행 시 NOL goods 페이지를 함께 연다(attach의 "interpark 창 존재" 조건 충족).
- 이미 떠 있으면 아무것도 하지 않고 정상 종료한다.

**비목표**
- 로그인 자동화. 최초 로그인은 여전히 수동이다(캡차/인증). `chrome_profile`이 영속이라 한 번
  로그인하면 이후 자동 실행에도 세션이 유지된다.
- `nol_monitor.py` / `nol_driver.py` 동작 변경. 두 파일은 그대로 attach 전용으로 둔다.

## 설계

### 새 파일: `nol_chrome.py` (단독 실행 진입점)

함수 4개 + `main()`으로 구성한다.

- `_read_goods_url(env_path) -> str`
  - `configparser.ConfigParser(inline_comment_prefixes=("#",))`로 `.env`의 `[NOL]`에서 `URL`,
    `GOODS_ID`만 읽어 `"{URL}/{GOODS_ID}"`를 반환한다.
  - `load_nol_config` 전체를 쓰지 않는다: 런처는 URL만 필요하며, 텔레그램 토큰·타깃 YAML 유효성에
    의존해서 실패하면 안 된다(단일 책임).
  - 섹션·키 누락 시 명확한 메시지로 예외를 던진다.

- `is_debugger_up() -> bool`
  - `http://127.0.0.1:9222/json/version`에 짧은 타임아웃(약 1s)으로 GET, 성공 시 `True`.
  - 단순 TCP 포트 오픈이 아니라 "DevTools가 실제로 응답하는가"를 판단한다.

- `launch_chrome(goods_url) -> None`
  - `subprocess.Popen(인수_리스트, start_new_session=True)`로 detached 실행. `shell=True` 금지.
  - 인수: `[CHROME_BINARY, "--remote-debugging-port=9222",
    "--user-data-dir={PROFILE_DIR}", goods_url]`.
  - Chrome 바이너리 부재 시 `FileNotFoundError`를 잡아 명확한 에러로 변환한다.

- `wait_for_debugger(timeout=20) -> None`
  - `is_debugger_up()`을 0.5s 간격으로 폴링, 준비되면 반환.
  - 타임아웃 시: "이 프로필이 디버그 포트 없이 이미 열려 있을 수 있다. 해당 Chrome 창을 닫고
    다시 실행하라"는 진단 메시지와 함께 예외.

### `main()` 흐름

1. `is_debugger_up()` → `True`면 "Chrome already running on debug port" 로그 후 종료(0).
2. 아니면: `goods_url = _read_goods_url(".env")` → `launch_chrome(goods_url)` →
   `wait_for_debugger()` → "Chrome ready on debug port" 로그.
3. 예외 발생 시 stderr에 원인을 남기고 비정상 종료(1).

### 상수

- `DEBUG_PORT = 9222` (또는 `nol_driver.DEBUGGER_ADDRESS`와 일관되게 유지).
- `CHROME_BINARY`: 기본 `/Applications/Google Chrome.app/Contents/MacOS/Google Chrome`,
  `NOL_CHROME_BINARY` 환경변수로 오버라이드 가능.
- `PROFILE_DIR`: 스크립트 파일 위치 기준 절대경로 `./chrome_profile`
  (`os.path.dirname(os.path.abspath(__file__))` 기반).

## 실행 순서

```
python3 nol_chrome.py     # 없으면 Chrome 띄우고 goods 페이지 열기(있으면 no-op)
python3 nol_monitor.py    # 기존과 동일하게 attach
```

## 설계 한계

- 최초 로그인은 수동. 이후는 영속 프로필로 세션 유지.
- 같은 `--user-data-dir`을 **디버그 포트 없이** 다른 곳에서 이미 열어두면, Chrome이 새 창을 기존
  인스턴스에 붙이면서 디버그 포트가 안 열린다. `chrome_profile`은 이 도구 전용이라는 전제가
  필요하며, 이 경우 `wait_for_debugger` 타임아웃이 위 진단 메시지로 안내한다.

## 테스트

실동작 검증 위주로 둔다.
- `_read_goods_url`: 인라인 주석 포함 `.env` 샘플에서 올바른 URL 조립, 키 누락 시 예외.
- `is_debugger_up`: 포트 미개방 시 `False`(실제 소켓, 모킹 최소화).
- `main` 흐름의 no-op 분기: 이미 떠 있다고 가정했을 때 `launch_chrome`이 호출되지 않는지.
