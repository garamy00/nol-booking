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
