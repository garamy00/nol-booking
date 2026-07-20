import pytest

import notifier
from config import TelegramConfig
from errors import NotifyError


class _Resp:
    def __init__(self, ok):
        self.ok = ok
        self.status_code = 200 if ok else 500
        self.text = "" if ok else "error"


def test_send_posts_to_bot_api(monkeypatch):
    captured = {}

    def fake_post(url, data, timeout):
        captured["url"] = url
        captured["data"] = data
        return _Resp(True)

    monkeypatch.setattr(notifier.requests, "post", fake_post)
    send_cfg = TelegramConfig(token="tok123", chat_id="chat456")
    notifier.send_telegram(send_cfg, "hello")

    assert "bottok123/sendMessage" in captured["url"]
    assert captured["data"]["chat_id"] == "chat456"
    assert captured["data"]["text"] == "hello"


def test_send_raises_notifyerror_on_http_failure(monkeypatch):
    monkeypatch.setattr(
        notifier.requests, "post", lambda url, data, timeout: _Resp(False)
    )
    with pytest.raises(NotifyError):
        notifier.send_telegram(TelegramConfig(token="t", chat_id="c"), "hi")


def test_send_raises_notifyerror_on_network_exception(monkeypatch):
    def boom(url, data, timeout):
        raise notifier.requests.RequestException("network down")

    monkeypatch.setattr(notifier.requests, "post", boom)
    with pytest.raises(NotifyError):
        notifier.send_telegram(TelegramConfig(token="t", chat_id="c"), "hi")


def test_send_raises_notifyerror_without_leaking_token_on_network_exception(
    monkeypatch,
):
    # 네트워크 예외 메시지에는 URL(토큰 포함)이 담길 수 있으므로 그대로 노출되면 안 된다
    def boom(url, data, timeout):
        raise notifier.requests.ConnectionError(
            "HTTPSConnectionPool: url: /botSECRET123/sendMessage"
        )

    monkeypatch.setattr(notifier.requests, "post", boom)
    with pytest.raises(NotifyError) as excinfo:
        notifier.send_telegram(TelegramConfig(token="SECRET123", chat_id="c"), "hi")

    assert "SECRET123" not in str(excinfo.value)
