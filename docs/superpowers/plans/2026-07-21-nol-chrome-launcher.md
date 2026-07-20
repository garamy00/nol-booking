# NOL Chrome 런처 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 디버그 포트(9222)로 떠 있는 Chrome이 없으면 전용 프로필로 자동 실행하고 NOL goods 페이지까지 여는 런처 `nol_chrome.py`를 추가한다.

**Architecture:** 단독 실행 진입점 `nol_chrome.py` 한 파일. `.env`의 `[NOL]`에서 URL만 최소로 읽고, `requests`로 DevTools 응답 여부를 확인해 없으면 `subprocess.Popen`으로 Chrome을 detached 실행한다. `nol_monitor.py`/`nol_driver.py`는 변경하지 않는다(계속 attach 전용).

**Tech Stack:** Python 3.10+, 표준 라이브러리(`configparser`, `subprocess`, `os`, `logging`, `time`), `requests`(이미 의존성), 테스트는 `pytest`.

## Global Constraints

- 줄 길이 최대 88자, 포매터 `ruff format` / 린터 `ruff check`.
- 로그는 `logging` 모듈만 사용, `print()` 금지. 로그 메시지는 영문, `%` 포매팅(lazy).
- 도메인 예외는 `AppBaseError`를 상속하는 계층으로 정의(`errors.py`).
- `subprocess`에 `shell=True` 금지, 인수 리스트 사용.
- 타입 힌트: public 함수 파라미터·반환에 작성, `X | None` 사용.
- Docstring은 Google Style, public 심볼에 작성.
- 커밋 메시지 형식 `<type>: <요약>`.
- `nol_monitor.py`/`nol_driver.py`는 이 작업에서 수정하지 않는다.

---

### Task 1: LauncherError 예외 + goods URL 읽기

**Files:**
- Modify: `errors.py` (예외 클래스 1개 추가)
- Create: `nol_chrome.py`
- Test: `tests/test_nol_chrome.py`

**Interfaces:**
- Consumes: 없음
- Produces:
  - `errors.LauncherError(AppBaseError)`
  - `nol_chrome.ENV_PATH: str = ".env"`
  - `nol_chrome._read_goods_url(env_path: str) -> str` — `[NOL]`의 `URL`/`GOODS_ID`로 `"{URL}/{GOODS_ID}"` 반환. 섹션·키 누락 시 `LauncherError`.

- [ ] **Step 1: Write the failing test**

`tests/test_nol_chrome.py`:

```python
import textwrap

import pytest

from errors import LauncherError
import nol_chrome


def _write_env(tmp_path, text):
    env = tmp_path / ".env"
    env.write_text(textwrap.dedent(text))
    return str(env)


ENV_OK = """
    [NOL]
    URL=https://tickets.interpark.com/goods
    GOODS_ID=26005135  # 인라인 주석
    DATE=20260802
    TIME=14:00
    TOGGLE_DATE=2026.08.02
    TOGGLE_TIME=2:00 PM
    [TELEGRAM]
    TELEGRAM_TOKEN="tok123"
    CHAT_ID="chat456"
"""


def test_read_goods_url_joins_url_and_id_ignoring_inline_comment(tmp_path):
    env_path = _write_env(tmp_path, ENV_OK)
    assert nol_chrome._read_goods_url(env_path) == (
        "https://tickets.interpark.com/goods/26005135"
    )


def test_read_goods_url_missing_key_raises(tmp_path):
    bad = ENV_OK.replace("GOODS_ID=26005135  # 인라인 주석\n", "")
    env_path = _write_env(tmp_path, bad)
    with pytest.raises(LauncherError):
        nol_chrome._read_goods_url(env_path)


def test_read_goods_url_missing_section_raises(tmp_path):
    bad = ENV_OK.replace("[NOL]", "[NOPE]")
    env_path = _write_env(tmp_path, bad)
    with pytest.raises(LauncherError):
        nol_chrome._read_goods_url(env_path)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/test_nol_chrome.py -v`
Expected: FAIL — `ImportError`/`ModuleNotFoundError` (`errors.LauncherError`, `nol_chrome` 없음)

- [ ] **Step 3: Add LauncherError to errors.py**

`errors.py`에 아래 클래스를 `DriverError` 다음에 추가:

```python
class LauncherError(AppBaseError):
    """Chrome 런처(디버그 포트 실행·대기) 실패."""
```

- [ ] **Step 4: Write minimal nol_chrome.py**

`nol_chrome.py` 생성:

```python
"""디버그 포트로 떠 있는 Chrome이 없으면 전용 프로필로 띄우고 NOL goods
페이지까지 여는 런처. `nol_monitor.py` 실행 전에 한 번 실행한다.

이미 디버그 포트가 응답하면 아무것도 하지 않는다. 최초 로그인은 수동이며,
`chrome_profile`이 영속 프로필이라 이후 자동 실행에도 세션이 유지된다.
"""

from __future__ import annotations

import configparser
import logging

from errors import LauncherError

logger = logging.getLogger(__name__)

ENV_PATH = ".env"


def _read_goods_url(env_path: str) -> str:
    """`.env`의 [NOL] URL/GOODS_ID를 조립해 goods 페이지 URL을 반환한다.

    런처는 URL만 필요하므로 텔레그램·타깃 설정에 의존하는 load_nol_config를
    쓰지 않는다.

    Raises:
        LauncherError: 파일·[NOL] 섹션·URL/GOODS_ID 키 누락.
    """
    # [NOL] 값에 붙는 "26005135  # 주석" 형태 인라인 주석을 값에서 분리한다
    parser = configparser.ConfigParser(inline_comment_prefixes=("#",))
    if not parser.read(env_path):
        raise LauncherError("cannot read env file: %s" % env_path)

    if "NOL" not in parser:
        raise LauncherError("env must contain [NOL] section: %s" % env_path)

    nol = parser["NOL"]
    if "URL" not in nol or "GOODS_ID" not in nol:
        raise LauncherError("[NOL] must contain URL and GOODS_ID")

    return "%s/%s" % (nol["URL"].strip(), nol["GOODS_ID"].strip())
```

- [ ] **Step 5: Run test to verify it passes**

Run: `python3 -m pytest tests/test_nol_chrome.py -v`
Expected: PASS (3 passed)

- [ ] **Step 6: Commit**

```bash
git add errors.py nol_chrome.py tests/test_nol_chrome.py
git commit -m "feat: NOL Chrome 런처 goods URL 파서·LauncherError 추가"
```

---

### Task 2: 디버거 응답 확인·대기

**Files:**
- Modify: `nol_chrome.py`
- Test: `tests/test_nol_chrome.py`

**Interfaces:**
- Consumes: `nol_chrome.LauncherError`(Task 1의 import)
- Produces:
  - `nol_chrome.DEBUG_PORT: int = 9222`
  - `nol_chrome.is_debugger_up() -> bool` — `http://127.0.0.1:9222/json/version` 응답 성공 시 `True`.
  - `nol_chrome.wait_for_debugger(timeout: float = 20.0) -> None` — 준비될 때까지 폴링, 타임아웃 시 `LauncherError`.

- [ ] **Step 1: Write the failing test**

`tests/test_nol_chrome.py`에 추가:

```python
def test_is_debugger_up_false_when_request_fails(monkeypatch):
    def boom(*args, **kwargs):
        import requests

        raise requests.RequestException("no server")

    import requests

    monkeypatch.setattr(requests, "get", boom)
    assert nol_chrome.is_debugger_up() is False


def test_wait_for_debugger_raises_on_timeout(monkeypatch):
    monkeypatch.setattr(nol_chrome, "is_debugger_up", lambda: False)
    monkeypatch.setattr(nol_chrome.time, "sleep", lambda _s: None)
    with pytest.raises(LauncherError):
        nol_chrome.wait_for_debugger(timeout=0.0)


def test_wait_for_debugger_returns_when_up(monkeypatch):
    monkeypatch.setattr(nol_chrome, "is_debugger_up", lambda: True)
    nol_chrome.wait_for_debugger(timeout=5.0)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/test_nol_chrome.py -v`
Expected: FAIL — `AttributeError` (`is_debugger_up`/`wait_for_debugger`/`time` 없음)

- [ ] **Step 3: Add imports, constant, and functions to nol_chrome.py**

`import` 블록에 추가:

```python
import time

import requests
```

`ENV_PATH` 아래에 상수 추가:

```python
DEBUG_PORT = 9222

# DevTools 준비 폴링 간격(초)
_POLL_INTERVAL_SEC = 0.5

# is_debugger_up의 HTTP 타임아웃(초)
_PROBE_TIMEOUT_SEC = 1.0
```

`_read_goods_url` 아래에 함수 추가:

```python
def is_debugger_up() -> bool:
    """DevTools(127.0.0.1:9222)가 실제로 응답하면 True.

    단순 포트 오픈이 아니라 /json/version 응답으로 attach 가능 여부를 판단한다.
    """
    url = "http://127.0.0.1:%d/json/version" % DEBUG_PORT
    try:
        resp = requests.get(url, timeout=_PROBE_TIMEOUT_SEC)
    except requests.RequestException:
        return False
    return resp.status_code == 200


def wait_for_debugger(timeout: float = 20.0) -> None:
    """DevTools가 응답할 때까지 폴링한다.

    Raises:
        LauncherError: timeout 내에 응답이 없을 때. 같은 프로필이 디버그 포트
            없이 이미 열려 있으면 이 경로로 실패한다.
    """
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if is_debugger_up():
            return
        time.sleep(_POLL_INTERVAL_SEC)

    if is_debugger_up():
        return

    raise LauncherError(
        "debug port %d not responding within %.0fs; a Chrome using this "
        "profile may already be open without the debug port — close it and "
        "retry" % (DEBUG_PORT, timeout)
    )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m pytest tests/test_nol_chrome.py -v`
Expected: PASS (6 passed)

- [ ] **Step 5: Commit**

```bash
git add nol_chrome.py tests/test_nol_chrome.py
git commit -m "feat: NOL Chrome 런처 디버거 응답 확인·대기 추가"
```

---

### Task 3: Chrome 실행 인수 조립·spawn·main 배선

**Files:**
- Modify: `nol_chrome.py`
- Test: `tests/test_nol_chrome.py`

**Interfaces:**
- Consumes: `_read_goods_url`, `is_debugger_up`, `wait_for_debugger`, `DEBUG_PORT`, `LauncherError`
- Produces:
  - `nol_chrome.PROFILE_DIR: str` — 스크립트 위치 기준 `./chrome_profile` 절대경로
  - `nol_chrome._chrome_binary() -> str` — `NOL_CHROME_BINARY` 환경변수 있으면 그 값, 없으면 macOS 기본 경로
  - `nol_chrome._build_launch_args(goods_url: str) -> list[str]`
  - `nol_chrome.launch_chrome(goods_url: str) -> None` — detached spawn, 바이너리 부재 시 `LauncherError`
  - `nol_chrome.main() -> None`

- [ ] **Step 1: Write the failing test**

`tests/test_nol_chrome.py`에 추가:

```python
def test_build_launch_args_has_flags_and_url_last():
    args = nol_chrome._build_launch_args("https://x/goods/1")
    assert args[-1] == "https://x/goods/1"
    assert "--remote-debugging-port=9222" in args
    assert any(
        a.startswith("--user-data-dir=") and a.endswith("chrome_profile")
        for a in args
    )


def test_chrome_binary_env_override(monkeypatch):
    monkeypatch.setenv("NOL_CHROME_BINARY", "/custom/chrome")
    assert nol_chrome._chrome_binary() == "/custom/chrome"


def test_main_noop_when_debugger_already_up(monkeypatch):
    called = {"launch": False}
    monkeypatch.setattr(nol_chrome, "is_debugger_up", lambda: True)
    monkeypatch.setattr(
        nol_chrome,
        "launch_chrome",
        lambda _u: called.__setitem__("launch", True),
    )
    nol_chrome.main()
    assert called["launch"] is False


def test_main_launches_when_debugger_down(monkeypatch):
    calls = {"launch": None, "waited": False}
    monkeypatch.setattr(nol_chrome, "is_debugger_up", lambda: False)
    monkeypatch.setattr(nol_chrome, "_read_goods_url", lambda _p: "https://x/g/1")
    monkeypatch.setattr(
        nol_chrome, "launch_chrome", lambda u: calls.__setitem__("launch", u)
    )
    monkeypatch.setattr(
        nol_chrome,
        "wait_for_debugger",
        lambda: calls.__setitem__("waited", True),
    )
    nol_chrome.main()
    assert calls["launch"] == "https://x/g/1"
    assert calls["waited"] is True
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/test_nol_chrome.py -v`
Expected: FAIL — `AttributeError` (`_build_launch_args`/`_chrome_binary`/`main` 없음)

- [ ] **Step 3: Add imports, constants, and functions to nol_chrome.py**

`import` 블록에 추가:

```python
import os
import subprocess
```

`DEBUG_PORT` 근처 상수 영역에 추가:

```python
# 이 도구 전용 Chrome 프로필(로그인 세션 영속). 스크립트 위치 기준 절대경로.
PROFILE_DIR = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "chrome_profile"
)

# macOS 기본 Chrome 실행 파일. NOL_CHROME_BINARY로 오버라이드 가능.
_DEFAULT_CHROME_BINARY = (
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
)
```

`wait_for_debugger` 아래에 함수 추가:

```python
def _chrome_binary() -> str:
    """Chrome 실행 파일 경로. 환경변수 오버라이드 우선."""
    return os.environ.get("NOL_CHROME_BINARY", _DEFAULT_CHROME_BINARY)


def _build_launch_args(goods_url: str) -> list[str]:
    """Chrome 실행 인수 리스트를 조립한다(goods_url을 마지막에 둔다)."""
    return [
        _chrome_binary(),
        "--remote-debugging-port=%d" % DEBUG_PORT,
        "--user-data-dir=%s" % PROFILE_DIR,
        goods_url,
    ]


def launch_chrome(goods_url: str) -> None:
    """전용 프로필로 Chrome을 detached 실행하고 goods 페이지를 연다.

    Raises:
        LauncherError: Chrome 실행 파일을 찾지 못함.
    """
    args = _build_launch_args(goods_url)
    try:
        # start_new_session으로 런처 종료와 무관하게 Chrome이 계속 뜨게 한다
        subprocess.Popen(
            args,
            start_new_session=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    except FileNotFoundError as exc:
        raise LauncherError("chrome binary not found: %s" % args[0]) from exc

    logger.info(
        "Launched Chrome on debug port %d with profile %s",
        DEBUG_PORT,
        PROFILE_DIR,
    )


def main() -> None:
    """디버그 포트가 비어 있으면 Chrome을 띄우고 준비될 때까지 대기한다."""
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s"
    )

    if is_debugger_up():
        logger.info("Chrome already running on debug port %d", DEBUG_PORT)
        return

    goods_url = _read_goods_url(ENV_PATH)
    launch_chrome(goods_url)
    wait_for_debugger()
    logger.info("Chrome ready on debug port %d", DEBUG_PORT)
```

파일 맨 끝에 진입점 추가:

```python
if __name__ == "__main__":
    import sys

    try:
        main()
    except LauncherError as exc:
        logger.error("Launcher failed: %s", exc)
        sys.exit(1)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m pytest tests/test_nol_chrome.py -v`
Expected: PASS (10 passed)

- [ ] **Step 5: Lint**

Run: `ruff format nol_chrome.py tests/test_nol_chrome.py errors.py && ruff check nol_chrome.py tests/test_nol_chrome.py errors.py`
Expected: 포매팅 정리 후 `check` 통과(에러 0)

- [ ] **Step 6: Full test suite**

Run: `python3 -m pytest -q`
Expected: 전체 통과(기존 테스트 포함)

- [ ] **Step 7: Commit**

```bash
git add nol_chrome.py tests/test_nol_chrome.py
git commit -m "feat: NOL Chrome 런처 실행·main 배선 완성"
```

---

## Self-Review

**Spec coverage:**
- 없으면 전용 프로필로 실행 → Task 3 `launch_chrome`/`main`. ✅
- goods 페이지 열기 → Task 3 `_build_launch_args`(goods_url 마지막 인수). ✅
- 이미 떠 있으면 no-op → Task 3 `main` 분기 + `test_main_noop_when_debugger_already_up`. ✅
- URL만 최소 읽기(load_nol_config 미사용) → Task 1 `_read_goods_url`. ✅
- DevTools 응답 판단 → Task 2 `is_debugger_up`. ✅
- 타임아웃 진단 메시지 → Task 2 `wait_for_debugger`. ✅
- Chrome 바이너리 환경변수 오버라이드 → Task 3 `_chrome_binary`. ✅
- `nol_monitor.py`/`nol_driver.py` 무변경 → 어떤 Task도 수정 대상에 없음. ✅

**Placeholder scan:** TBD/TODO/"적절히 처리" 없음. 모든 코드 스텝에 실제 코드 포함. ✅

**Type consistency:** `is_debugger_up`/`wait_for_debugger`/`launch_chrome`/`_read_goods_url`/`_build_launch_args`/`_chrome_binary`/`main` 이름·시그니처가 세 Task에서 일치. `DEBUG_PORT`, `PROFILE_DIR`, `ENV_PATH` 상수명 일관. ✅
