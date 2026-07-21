from config import TelegramConfig
from control import ControlState
import telegram_control


def _cfg():
    return TelegramConfig(token="tok", chat_id="42")


def test_dispatch_status_includes_target_and_state():
    control = ControlState("20260802", "14:00")
    reply = telegram_control.dispatch("/status", control)
    assert "20260802" in reply
    assert "14:00" in reply


def test_dispatch_pause_and_resume_change_control():
    control = ControlState("20260802", "14:00")
    assert telegram_control.dispatch("/pause", control) == "일시정지됨"
    assert control.is_paused() is True
    assert telegram_control.dispatch("/resume", control) == "재개됨"
    assert control.is_paused() is False


def test_dispatch_stop_requests_stop():
    control = ControlState("20260802", "14:00")
    assert telegram_control.dispatch("/stop", control) == "종료합니다"
    assert control.should_stop() is True


def test_dispatch_unknown_returns_usage():
    control = ControlState("20260802", "14:00")
    reply = telegram_control.dispatch("/foo", control)
    assert "/status" in reply


def test_extract_command_reads_text_and_chat_id():
    update = {"update_id": 1, "message": {"text": "/status", "chat": {"id": 42}}}
    text, chat_id = telegram_control._extract_command(update)
    assert text == "/status"
    assert chat_id == 42


def test_extract_command_ignores_non_command_and_empty():
    assert telegram_control._extract_command({"update_id": 1}) == (None, None)
    plain = {"update_id": 2, "message": {"text": "hi", "chat": {"id": 42}}}
    assert telegram_control._extract_command(plain) == (None, None)


def test_handle_update_authorized_dispatches_and_replies():
    control = ControlState("20260802", "14:00")
    sent = []
    update = {"update_id": 1, "message": {"text": "/pause", "chat": {"id": 42}}}
    telegram_control.handle_update(
        update, _cfg(), control, lambda cid, t: sent.append((cid, t))
    )
    assert control.is_paused() is True
    assert sent == [(42, "일시정지됨")]


def test_handle_update_unauthorized_chat_ignored():
    control = ControlState("20260802", "14:00")
    sent = []
    update = {"update_id": 1, "message": {"text": "/stop", "chat": {"id": 999}}}
    telegram_control.handle_update(
        update, _cfg(), control, lambda cid, t: sent.append((cid, t))
    )
    assert control.should_stop() is False  # 인가되지 않음 → 무시
    assert sent == []
