"""디버그 포트로 떠 있는 Chrome이 없으면 전용 프로필로 띄우고 NOL goods
페이지까지 여는 런처. `nol_monitor.py` 실행 전에 한 번 실행한다.

이미 디버그 포트가 응답하면 아무것도 하지 않는다. 최초 로그인은 수동이며,
`chrome_profile`이 영속 프로필이라 이후 자동 실행에도 세션이 유지된다.
"""

from __future__ import annotations

import configparser
import logging
import os
import shutil
import signal
import subprocess
import sys
import time

import requests

from errors import LauncherError

logger = logging.getLogger(__name__)

ENV_PATH = ".env"

DEBUG_PORT = 9222

# 이 도구 전용 Chrome 프로필(로그인 세션 영속). 스크립트 위치 기준 절대경로.
PROFILE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "chrome_profile")

# launch가 띄운 Chrome PID 기록 파일. stop이 이 PID로 정상 종료(SIGTERM)한다.
PID_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".nol_chrome.pid")

# macOS 기본 Chrome 실행 파일. NOL_CHROME_BINARY로 오버라이드 가능.
_DEFAULT_CHROME_BINARY = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"

# Linux에서 자동 탐지할 Chrome/Chromium 실행 파일 후보(우선순위 순)
_LINUX_CHROME_CANDIDATES = (
    "google-chrome",
    "google-chrome-stable",
    "chromium",
    "chromium-browser",
)

# DevTools 준비 폴링 간격(초)
_POLL_INTERVAL_SEC = 0.5

# is_debugger_up의 HTTP 타임아웃(초)
_PROBE_TIMEOUT_SEC = 1.0


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


def _read_debug_port(env_path: str) -> int:
    """`.env` [RUNTIME] DEBUG_PORT를 읽는다. 없으면 기본 9222.

    런처는 전체 설정에 의존하지 않으므로 최소로만 읽는다.
    """
    parser = configparser.ConfigParser(inline_comment_prefixes=("#",))
    parser.read(env_path)
    if "RUNTIME" not in parser or "DEBUG_PORT" not in parser["RUNTIME"]:
        return DEBUG_PORT
    try:
        return int(parser["RUNTIME"]["DEBUG_PORT"].strip())
    except ValueError:
        return DEBUG_PORT


def is_debugger_up(port: int = DEBUG_PORT) -> bool:
    """DevTools(127.0.0.1:port)가 실제로 응답하면 True.

    단순 포트 오픈이 아니라 /json/version 응답으로 attach 가능 여부를 판단한다.
    """
    url = "http://127.0.0.1:%d/json/version" % port
    try:
        resp = requests.get(url, timeout=_PROBE_TIMEOUT_SEC)
    except requests.RequestException:
        return False
    return resp.status_code == 200


def wait_for_debugger(port: int = DEBUG_PORT, timeout: float = 20.0) -> None:
    """DevTools가 응답할 때까지 폴링한다.

    Raises:
        LauncherError: timeout 내에 응답이 없을 때. 같은 프로필이 디버그 포트
            없이 이미 열려 있으면 이 경로로 실패한다.
    """
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if is_debugger_up(port):
            return
        time.sleep(_POLL_INTERVAL_SEC)

    if is_debugger_up(port):
        return

    raise LauncherError(
        "debug port %d not responding within %.0fs; a Chrome using this "
        "profile may already be open without the debug port — close it and "
        "retry" % (port, timeout)
    )


def _chrome_binary() -> str:
    """Chrome 실행 파일 경로를 결정한다.

    NOL_CHROME_BINARY가 있으면 그 값을, 없으면 플랫폼별로 탐지한다. macOS는 기본
    앱 경로, Linux는 google-chrome/chromium 계열을 PATH에서 찾는다.

    Raises:
        LauncherError: Linux에서 후보를 하나도 찾지 못함.
    """
    override = os.environ.get("NOL_CHROME_BINARY")
    if override:
        return override

    if sys.platform == "darwin":
        return _DEFAULT_CHROME_BINARY

    for candidate in _LINUX_CHROME_CANDIDATES:
        path = shutil.which(candidate)
        if path:
            return path
    raise LauncherError(
        "no Chrome/Chromium found; install one or set NOL_CHROME_BINARY"
    )


def _build_launch_args(goods_url: str, port: int = DEBUG_PORT) -> list[str]:
    """Chrome 실행 인수 리스트를 조립한다(goods_url을 마지막에 둔다)."""
    return [
        _chrome_binary(),
        "--remote-debugging-port=%d" % port,
        "--user-data-dir=%s" % PROFILE_DIR,
        goods_url,
    ]


def launch_chrome(goods_url: str, port: int = DEBUG_PORT) -> None:
    """전용 프로필로 Chrome을 detached 실행하고 goods 페이지를 연다.

    Raises:
        LauncherError: Chrome 실행 파일을 찾지 못함.
    """
    args = _build_launch_args(goods_url, port)
    try:
        # start_new_session으로 런처 종료와 무관하게 Chrome이 계속 뜨게 한다
        proc = subprocess.Popen(
            args,
            start_new_session=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    except FileNotFoundError as exc:
        raise LauncherError("chrome binary not found: %s" % args[0]) from exc

    # stop 명령이 정상 종료할 수 있도록 PID를 기록한다
    _write_pid_file(proc.pid)
    logger.info(
        "Launched Chrome (pid %d) on debug port %d with profile %s",
        proc.pid,
        port,
        PROFILE_DIR,
    )


def _write_pid_file(pid: int) -> None:
    """launch한 Chrome PID를 기록한다(실패해도 실행은 계속한다)."""
    try:
        with open(PID_PATH, "w") as pid_file:
            pid_file.write(str(pid))
    except OSError as exc:
        logger.warning("could not write pid file %s: %s", PID_PATH, type(exc).__name__)


def _remove_pid_file() -> None:
    """PID 파일을 지운다(없어도 무시)."""
    try:
        os.remove(PID_PATH)
    except OSError:
        pass


def stop() -> None:
    """launch가 띄운 디버그 Chrome을 PID 파일 기반으로 정상 종료(SIGTERM)한다.

    PID 파일이 없거나 이미 죽은 프로세스면 조용히 넘어간다. kill -9와 달리
    SIGTERM은 Chrome이 프로필을 정상 저장하고 종료하게 한다.

    Raises:
        LauncherError: PID 파일이 손상됐거나 종료 신호 전송이 실패했을 때.
    """
    if not os.path.exists(PID_PATH):
        logger.info("No launcher pid file (%s); nothing to stop", PID_PATH)
        return

    try:
        with open(PID_PATH) as pid_file:
            pid = int(pid_file.read().strip())
    except (OSError, ValueError) as exc:
        raise LauncherError(
            "cannot read pid file %s: %s" % (PID_PATH, type(exc).__name__)
        ) from exc

    try:
        os.kill(pid, signal.SIGTERM)
        logger.info("Sent SIGTERM to Chrome pid %d", pid)
    except ProcessLookupError:
        logger.info("Chrome pid %d not running; cleaning up pid file", pid)
    except OSError as exc:
        raise LauncherError(
            "failed to stop pid %d: %s" % (pid, type(exc).__name__)
        ) from exc
    finally:
        _remove_pid_file()


def main() -> None:
    """디버그 포트가 비어 있으면 Chrome을 띄우고 준비될 때까지 대기한다."""
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s"
    )

    port = _read_debug_port(ENV_PATH)
    if is_debugger_up(port):
        logger.info("Chrome already running on debug port %d", port)
        return

    goods_url = _read_goods_url(ENV_PATH)
    launch_chrome(goods_url, port)
    wait_for_debugger(port)
    logger.info("Chrome ready on debug port %d", port)


if __name__ == "__main__":
    import sys

    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s"
    )
    try:
        # `python nol_chrome.py stop`이면 종료, 인수 없으면 기존 실행
        if len(sys.argv) > 1 and sys.argv[1] == "stop":
            stop()
        else:
            main()
    except LauncherError as exc:
        logger.error("Launcher failed: %s", exc)
        sys.exit(1)
