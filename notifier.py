"""텔레그램 Bot API로 알림을 전송한다."""

import logging

import requests

from config import TelegramConfig
from errors import NotifyError

logger = logging.getLogger(__name__)

_API_TEMPLATE = "https://api.telegram.org/bot%s/sendMessage"


def send_telegram(cfg: TelegramConfig, text: str) -> None:
    """텔레그램으로 메시지를 보낸다.

    Raises:
        NotifyError: HTTP 실패 또는 네트워크 오류.
    """
    url = _API_TEMPLATE % cfg.token
    try:
        resp = requests.post(
            url,
            data={"chat_id": cfg.chat_id, "text": text},
            timeout=10,
        )
    except requests.RequestException as exc:
        raise NotifyError("telegram request failed: %s" % exc) from exc

    if not resp.ok:
        raise NotifyError("telegram returned status %s" % resp.status_code)

    logger.info("Telegram notification sent to chat %s", cfg.chat_id)
