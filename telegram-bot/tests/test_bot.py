"""The real python-telegram-bot pipeline against a fake Telegram server."""

from __future__ import annotations

import asyncio
import json
import logging
from datetime import UTC, datetime, time
from pathlib import Path
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import httpx
import pytest
from telegram import Update
from telegram.error import NetworkError
from telegram.request import HTTPXRequest

from discipline_bot import bot
from discipline_bot.assistant import Assistant, DashboardUpdate, State
from discipline_bot.config import Config
from discipline_bot.journal import FOCUS, LOG, Journal
from discipline_bot.markdown import section_lines

from .conftest import DAY

OWNER = 1001
STRANGER = 2002
TOKEN = "123456:TESTTOKEN"
# 14:32 in Kyiv on the test day.
MESSAGE_TIME = int(datetime(2026, 10, 30, 12, 32, tzinfo=UTC).timestamp())


class FakeTelegram:
    def __init__(self) -> None:
        self.sent: list[dict] = []
        self.calls: list[dict] = []
        self.deleted: set[str] = set()  # message ids the user removed

    def handler(self, request: httpx.Request) -> httpx.Response:
        method = request.url.path.rsplit("/", 1)[-1]
        fields = dict(httpx.QueryParams(request.content.decode()))
        self.calls.append({"method": method, **fields})
        if method == "getMe":
            result: object = {"id": 1, "is_bot": True, "first_name": "Bot", "username": "test_bot"}
        elif method == "editMessageText" and fields.get("message_id") in self.deleted:
            error = {"ok": False, "error_code": 400, "description": "Bad Request: message to edit not found"}
            return httpx.Response(400, json=error)
        elif method in {"sendMessage", "editMessageText"}:
            if "reply_markup" in fields:
                fields["reply_markup"] = json.loads(fields["reply_markup"])
            self.sent.append({"method": method, **fields})
            result = {"message_id": 2, "date": MESSAGE_TIME, "chat": {"id": OWNER, "type": "private"}}
        else:
            result = True
        return httpx.Response(200, json={"ok": True, "result": result})


def message_update(user_id: int, text: str, chat_type: str = "private") -> dict:
    message = {
        "message_id": 1,
        "date": MESSAGE_TIME,
        "chat": {"id": user_id, "type": chat_type},
        "from": {"id": user_id, "is_bot": False, "first_name": "Хтось"},
        "text": text,
    }
    if text.startswith("/"):
        message["entities"] = [{"type": "bot_command", "offset": 0, "length": len(text.split()[0])}]
    return {"update_id": 1, "message": message}


@pytest.fixture
def world(vault: Path, env_file: Path, tmp_path: Path):
    telegram = FakeTelegram()
    config = Config(TOKEN, OWNER, ZoneInfo("Europe/Kyiv"), time(20, 0), vault, env_file)
    journal = Journal(vault)
    assistant = Assistant(journal, State(tmp_path / "data" / "state.json"), config.reminder_time, env_file)
    request = HTTPXRequest(httpx_kwargs={"transport": httpx.MockTransport(telegram.handler)})
    application = bot.build_application(config, assistant, request)

    def deliver(*updates: dict) -> None:
        async def scenario() -> None:
            await application.initialize()
            for update in updates:
                await application.process_update(Update.de_json(update, application.bot))
            await application.shutdown()

        asyncio.run(scenario())

    return SimpleNamespace(
        telegram=telegram, journal=journal, deliver=deliver, assistant=assistant, application=application
    )


def test_owner_text_lands_in_the_note_in_local_time(world) -> None:
    world.deliver(message_update(OWNER, "Привіт, журнале"))
    assert section_lines(world.journal.read(DAY), LOG) == ["- 14:32 Привіт, журнале"]
    assert [item["chat_id"] for item in world.telegram.sent] == [str(OWNER)]


def test_a_command_with_arguments(world) -> None:
    world.deliver(message_update(OWNER, "/f 50 ML"))
    assert section_lines(world.journal.read(DAY), FOCUS) == ["- 14:32 · 50 хв · ML"]


@pytest.mark.parametrize("text", ["Я чужий", "/f 50 ML", "/today", "/undo", "/remind 03:00", "/start"])
def test_a_stranger_gets_nothing(world, text: str) -> None:
    world.deliver(message_update(STRANGER, text))
    assert world.telegram.sent == []
    assert world.journal.read(DAY) is None
    assert "REMINDER_TIME=20:00" in world.assistant.env_file.read_text(encoding="utf-8")


def test_a_stranger_cannot_press_buttons(world) -> None:
    query = {
        "update_id": 2,
        "callback_query": {
            "id": "1",
            "from": {"id": STRANGER, "is_bot": False, "first_name": "Хтось"},
            "chat_instance": "1",
            "data": "energy:5",
            "message": {"message_id": 1, "date": MESSAGE_TIME, "chat": {"id": OWNER, "type": "private"}},
        },
    }
    world.deliver(query)
    assert world.journal.read(DAY) is None


def test_a_group_with_the_owner_is_ignored(world) -> None:
    world.deliver(message_update(OWNER, "у групі", chat_type="group"))
    assert world.telegram.sent == [] and world.journal.read(DAY) is None


def test_start_shows_the_keyboard(world) -> None:
    world.deliver(message_update(OWNER, "/start"))
    keyboard = world.telegram.sent[0]["reply_markup"]
    assert keyboard["resize_keyboard"] is True and keyboard["is_persistent"] is True
    assert keyboard["keyboard"][0][0]["text"] == "🎯 Фокус"


def test_inline_buttons_reach_telegram_within_the_limit(world) -> None:
    world.deliver(message_update(OWNER, "/f 50 довга тема українською мовою про лінійну алгебру"))
    world.deliver(message_update(OWNER, "/f"), {
        "update_id": 3,
        "callback_query": {
            "id": "1",
            "from": {"id": OWNER, "is_bot": False, "first_name": "Я"},
            "chat_instance": "1",
            "data": "focus:90",
            "message": {"message_id": 1, "date": MESSAGE_TIME, "chat": {"id": OWNER, "type": "private"}},
        },
    })
    edited = world.telegram.sent[-1]
    assert edited["method"] == "editMessageText"
    for row in edited["reply_markup"]["inline_keyboard"]:
        for button in row:
            assert len(button["callback_data"].encode()) <= 64


def test_a_wrong_command_explains_itself_and_writes_nothing(world) -> None:
    world.deliver(message_update(OWNER, "/f багато"))
    assert "Приклад" in world.telegram.sent[0]["text"]
    assert world.journal.read(DAY) is None


def test_a_failed_write_tells_the_user(world, monkeypatch: pytest.MonkeyPatch) -> None:
    def broken(*args: object) -> None:
        raise PermissionError("locked")

    monkeypatch.setattr(world.journal, "apply", broken)
    world.deliver(message_update(OWNER, "важливий запис"))
    assert "Не вдалося записати" in world.telegram.sent[0]["text"]


def test_unknown_command_and_a_photo(world) -> None:
    photo = message_update(OWNER, "x")
    del photo["message"]["text"]
    photo["message"]["photo"] = [{"file_id": "1", "file_unique_id": "1", "width": 1, "height": 1}]
    world.deliver(message_update(OWNER, "/nope"), photo)
    assert "/help" in world.telegram.sent[0]["text"]
    assert "текст" in world.telegram.sent[1]["text"]
    assert world.journal.read(DAY) is None


def test_every_menu_command_is_registered(world) -> None:
    registered = set()
    application = bot.build_application(
        Config(TOKEN, OWNER, ZoneInfo("Europe/Kyiv"), time(20, 0), world.journal.vault, world.assistant.env_file),
        world.assistant,
    )
    for handler in application.handlers[0]:
        registered |= getattr(handler, "commands", frozenset())
    assert {name for name, _ in bot.COMMANDS} | {"start"} == registered


def dashboard_calls(world, *updates: DashboardUpdate) -> list[tuple[str, str]]:
    async def scenario() -> None:
        await world.application.initialize()
        for update in updates:
            await bot.show_dashboard(world.application.bot, OWNER, update, world.assistant)
        await world.application.shutdown()

    asyncio.run(scenario())
    return [(call["method"], call.get("message_id", "")) for call in world.telegram.calls if call["method"] != "getMe"]


def test_a_new_dashboard_is_sent_quietly_and_pinned(world) -> None:
    calls = dashboard_calls(world, DashboardUpdate("📵✅", None))
    assert calls == [("sendMessage", ""), ("pinChatMessage", "2")]
    assert world.telegram.calls[1]["disable_notification"] == "true"
    assert (world.assistant.state.dashboard_message, world.assistant.state.dashboard_text) == (2, "📵✅")


def test_the_dashboard_is_edited_in_place(world) -> None:
    calls = dashboard_calls(world, DashboardUpdate("новий текст", 7))
    assert calls == [("editMessageText", "7")]
    assert world.assistant.state.dashboard_message == 7


def test_a_deleted_dashboard_comes_back_pinned(world) -> None:
    world.telegram.deleted.add("7")
    calls = dashboard_calls(world, DashboardUpdate("текст", 7))
    assert calls == [("editMessageText", "7"), ("sendMessage", ""), ("unpinChatMessage", "7"), ("pinChatMessage", "2")]
    assert world.assistant.state.dashboard_message == 2


def test_dash_command_renews_the_pin(world) -> None:
    world.assistant.dashboard_shown(7, "старий")
    world.deliver(message_update(OWNER, "/dash"))
    methods = [call["method"] for call in world.telegram.calls if call["method"] != "getMe"]
    assert methods == ["sendMessage", "unpinChatMessage", "pinChatMessage"]
    assert world.telegram.sent[0]["text"].startswith("📵✅ 🎯⬜")


def test_lost_network_is_one_quiet_line(world, caplog: pytest.LogCaptureFixture) -> None:
    with caplog.at_level(logging.INFO):
        asyncio.run(world.application.process_error(None, NetworkError("no internet")))
    assert [record.levelname for record in caplog.records] == ["WARNING"]
    assert caplog.records[0].exc_info is None


def test_a_real_failure_keeps_its_traceback(world, caplog: pytest.LogCaptureFixture) -> None:
    with caplog.at_level(logging.INFO):
        asyncio.run(world.application.process_error(None, ValueError("bug")))
    assert caplog.records[0].levelname == "ERROR" and caplog.records[0].exc_info


def test_the_token_never_reaches_the_log(world, caplog: pytest.LogCaptureFixture) -> None:
    bot.configure_logging()
    assert logging.getLogger("httpx").level == logging.WARNING
    assert logging.getLogger("httpcore").level == logging.WARNING
    with caplog.at_level(logging.INFO):
        world.deliver(message_update(OWNER, "запис"))
    assert TOKEN not in caplog.text
