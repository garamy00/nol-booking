"""Telegram getUpdates 롱폴링으로 제어 명령을 수신·처리한다(daemon 스레드).

봇 스레드는 ControlState의 플래그/상태만 조작하고 Selenium 드라이버는 만지지
않는다. 설정된 chat_id의 명령만 처리한다(인가).
"""

from __future__ import annotations

import logging
import time
from typing import Callable

import requests

from config import TelegramConfig
from control import ControlSnapshot, ControlState

logger = logging.getLogger(__name__)

_API = "https://api.telegram.org/bot%s/%s"

# getUpdates 롱폴링 대기(초). 이 값만큼 봇 응답이 늦어질 수 있으나 daemon이라
# 프로세스 종료 자체는 지연되지 않는다.
_LONG_POLL_SEC = 20

_USAGE = "사용법: /status /pause /resume /stop"

_STATE_KR = {
    "entering": "진입 중",
    "polling": "폴링 중",
    "paused": "일시정지",
    "holding": "홀드(좌석 발견)",
}


def format_status(snap: ControlSnapshot) -> str:
    """스냅샷을 /status 응답 텍스트로 만든다."""
    state_kr = _STATE_KR.get(snap.state, snap.state)
    if snap.last_success_ts is None:
        last = "-"
    else:
        last = time.strftime("%H:%M:%S", time.localtime(snap.last_success_ts))
    return "[NOL 상태]\n목표: %s %s\n상태: %s\n연속 실패: %d\n마지막 성공: %s" % (
        snap.target_date,
        snap.target_time,
        state_kr,
        snap.consecutive_failures,
        last,
    )


def dispatch(command: str, control: ControlState) -> str:
    """명령을 처리하고 응답 텍스트를 반환한다(순수 함수)."""
    cmd = command.split()[0].lower() if command.strip() else ""
    if cmd == "/status":
        return format_status(control.snapshot())
    if cmd == "/pause":
        control.pause()
        return "일시정지됨"
    if cmd == "/resume":
        control.resume()
        return "재개됨"
    if cmd == "/stop":
        control.request_stop()
        return "종료합니다"
    return _USAGE


def _extract_command(update: dict) -> tuple[str | None, object]:
    """update에서 (명령 텍스트, chat_id)를 뽑는다. 명령이 아니면 (None, None)."""
    message = update.get("message") or update.get("edited_message")
    if not message:
        return None, None
    text = message.get("text", "")
    if not text.startswith("/"):
        return None, None
    chat_id = (message.get("chat") or {}).get("id")
    return text, chat_id


def handle_update(
    update: dict,
    cfg: TelegramConfig,
    control: ControlState,
    send: Callable[[object, str], None],
) -> None:
    """update 하나를 처리한다: 추출 → 인가 → 디스패치 → 응답.

    설정된 chat_id가 아니면 무시한다(응답도 하지 않는다).
    """
    text, chat_id = _extract_command(update)
    if text is None:
        return
    if str(chat_id) != str(cfg.chat_id):
        logger.warning("ignoring command from unauthorized chat %s", chat_id)
        return
    send(chat_id, dispatch(text, control))


def _get_updates(token: str, offset: int | None) -> list:
    """getUpdates 롱폴링으로 새 업데이트 목록을 가져온다."""
    params: dict = {"timeout": _LONG_POLL_SEC}
    if offset is not None:
        params["offset"] = offset
    resp = requests.get(
        _API % (token, "getUpdates"), params=params, timeout=_LONG_POLL_SEC + 10
    )
    resp.raise_for_status()
    return resp.json().get("result", [])


def _send_reply(token: str, chat_id: object, text: str) -> None:
    """명령 응답을 전송한다(실패는 로깅만)."""
    try:
        requests.post(
            _API % (token, "sendMessage"),
            data={"chat_id": chat_id, "text": text},
            timeout=10,
        )
    except requests.RequestException as exc:
        logger.warning("reply send failed: %s", type(exc).__name__)


def serve(cfg: TelegramConfig, control: ControlState) -> None:
    """제어 명령을 처리하는 롱폴링 루프(daemon 스레드 진입점)."""
    offset: int | None = None

    def send(chat_id: object, text: str) -> None:
        _send_reply(cfg.token, chat_id, text)

    logger.info("Telegram control channel started")
    while not control.should_stop():
        try:
            updates = _get_updates(cfg.token, offset)
            for update in updates:
                offset = update["update_id"] + 1
                handle_update(update, cfg, control, send)
        except requests.RequestException as exc:
            logger.warning("getUpdates failed: %s", type(exc).__name__)
            time.sleep(3)
        except (ValueError, KeyError) as exc:
            # 비정상 JSON·형식의 update로 데몬이 죽지 않게 방어한다
            logger.warning("bad update payload: %s", type(exc).__name__)
            time.sleep(1)
