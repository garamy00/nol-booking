"""디버그 포트로 떠 있는 Chrome이 없으면 전용 프로필로 띄우고 NOL goods
페이지까지 여는 런처. `nol_monitor.py` 실행 전에 한 번 실행한다.

이미 디버그 포트가 응답하면 아무것도 하지 않는다. 최초 로그인은 수동이며,
`chrome_profile`이 영속 프로필이라 이후 자동 실행에도 세션이 유지된다.
"""

from __future__ import annotations

import configparser
import logging
import os
import subprocess
import time

import requests

from errors import LauncherError

logger = logging.getLogger(__name__)

ENV_PATH = ".env"

DEBUG_PORT = 9222

# 이 도구 전용 Chrome 프로필(로그인 세션 영속). 스크립트 위치 기준 절대경로.
PROFILE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "chrome_profile")

# macOS 기본 Chrome 실행 파일. NOL_CHROME_BINARY로 오버라이드 가능.
_DEFAULT_CHROME_BINARY = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"

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


if __name__ == "__main__":
    import sys

    try:
        main()
    except LauncherError as exc:
        logger.error("Launcher failed: %s", exc)
        sys.exit(1)
