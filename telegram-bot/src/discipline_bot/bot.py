"""Telegram side of the bot: handlers, buttons, the background loop."""

from __future__ import annotations

import asyncio
import contextlib
import logging
import sys
from collections.abc import Callable
from datetime import datetime
from logging.handlers import RotatingFileHandler
from pathlib import Path

from telegram import Bot, BotCommand, InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup, Update
from telegram.error import BadRequest, NetworkError, TelegramError
from telegram.request import BaseRequest
from telegram.ext import (
    Application,
    ApplicationBuilder,
    ApplicationHandlerStop,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    TypeHandler,
    filters,
)

from .assistant import BUTTON_ROWS, Assistant, DashboardUpdate, Handler, Reply, State
from .commands import CommandError
from .config import Config, ConfigError, load_config
from .journal import Journal, JournalBusy

DATA = Path(__file__).resolve().parents[2] / "data"
TICK_SECONDS = 5
ALLOWED_UPDATES = ["message", "callback_query"]
WRITE_FAILED = "❌ Не вдалося записати в нотатку. Повідомлення лишилось у чаті, спробуй ще раз."

COMMANDS = (
    ("f", "Блок фокусу: /f 50 ML"),
    ("l", "Що вивчив"),
    ("w", "Слова на Anki: /w borrow або /w reluctant: де зустрів"),
    ("tt", "Зірвався на тікток"),
    ("sleep", "Сон, години"),
    ("gym", "Тренування по підходах або /gym 60 ноги"),
    ("eat", "Їжа"),
    ("n", "Нотатка дня"),
    ("today", "Підсумок дня"),
    ("streak", "Стріки"),
    ("undo", "Скасувати останній запис"),
    ("remind", "Час нагадування: /remind 20:00"),
    ("dash", "Закріпити дашборд дня заново"),
    ("help", "Усі команди"),
)

logger = logging.getLogger("discipline_bot")


def is_allowed(update: Update, user_id: int) -> bool:
    user = update.effective_user
    chat = update.effective_chat
    return user is not None and user.id == user_id and chat is not None and chat.type == "private"


def inline_markup(reply: Reply) -> InlineKeyboardMarkup | None:
    if not reply.buttons:
        return None
    rows = [[InlineKeyboardButton(label, callback_data=data) for label, data in row] for row in reply.buttons]
    return InlineKeyboardMarkup(rows)


def main_keyboard() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup([list(row) for row in BUTTON_ROWS], resize_keyboard=True, is_persistent=True)


def command_text(text: str | None) -> str:
    parts = (text or "").split(maxsplit=1)
    return parts[1] if len(parts) > 1 else ""


async def reply_to(update: Update, reply: Reply) -> None:
    await update.effective_message.reply_text(reply.text, reply_markup=inline_markup(reply))


async def show_dashboard(bot: Bot, chat_id: int, update: DashboardUpdate, assistant: Assistant) -> None:
    """Change the pinned dashboard in place, or send and pin a new one when there is none or it is gone.

    One message for all days: a new pin each day would leave a service message in the chat every time.
    """
    if update.edit is not None:
        try:
            await bot.edit_message_text(update.text, chat_id=chat_id, message_id=update.edit)
        except BadRequest as error:
            if "not modified" not in error.message.lower():
                # Deleted by the user: a new one takes its place.
                await show_dashboard(bot, chat_id, DashboardUpdate(update.text, None, update.edit), assistant)
                return
        assistant.dashboard_shown(update.edit, update.text)
        return
    message = await bot.send_message(chat_id, update.text, disable_notification=True)
    assistant.dashboard_shown(message.message_id, update.text)
    if update.replaces is not None:
        with contextlib.suppress(BadRequest):
            await bot.unpin_chat_message(chat_id, message_id=update.replaces)
    await bot.pin_chat_message(chat_id, message.message_id, disable_notification=True)


async def answer(update: Update, action: Callable[[], Reply]) -> None:
    """Run an action; a mistake in the command or a failed write is reported to the user."""
    try:
        reply = action()
    except CommandError as error:
        reply = Reply(str(error))
    except (OSError, JournalBusy, UnicodeDecodeError):
        logger.exception("Could not write the note")
        reply = Reply(WRITE_FAILED)
    await reply_to(update, reply)


def build_application(config: Config, assistant: Assistant, request: BaseRequest | None = None) -> Application:
    async def gate(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not is_allowed(update, config.user_id):
            raise ApplicationHandlerStop

    def local_time(update: Update) -> datetime:
        # The message's own time: what waited on Telegram's side lands in the right day and hour.
        return update.effective_message.date.astimezone(config.timezone)

    def command(handler: Handler):
        async def handle(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
            args = command_text(update.effective_message.text)
            now = local_time(update)
            await answer(update, lambda: assistant.on_command(handler, args, now))

        return handle

    async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        reply = assistant.help("", local_time(update))
        await update.effective_message.reply_text(reply.text, reply_markup=main_keyboard())

    async def text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        message_text, now = update.effective_message.text, local_time(update)
        await answer(update, lambda: assistant.on_text(message_text, now))

    async def button(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        query = update.callback_query
        await query.answer()
        now = datetime.now(config.timezone)
        try:
            reply = assistant.on_button(query.data or "", now)
        except (CommandError, IndexError, ValueError):
            reply = Reply("Ця кнопка вже не працює.")
        except (OSError, JournalBusy, UnicodeDecodeError):
            logger.exception("Could not write the note")
            reply = Reply(WRITE_FAILED)
        await query.edit_message_text(reply.text, reply_markup=inline_markup(reply))

    dashboard_lock = asyncio.Lock()

    async def refresh_dashboard(now: datetime, renew: bool = False) -> None:
        async with dashboard_lock:
            update = assistant.dashboard_due(now, renew)
            if update is not None:
                await show_dashboard(application.bot, config.user_id, update, assistant)

    async def dash(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        await refresh_dashboard(local_time(update), renew=True)

    async def unknown_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        await update.effective_message.reply_text("Не знаю такої команди. Усі команди: /help")

    async def not_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        await update.effective_message.reply_text("Поки записую лише текст.")

    async def on_error(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
        # No network is normal for a laptop, and the library keeps retrying by itself.
        if isinstance(context.error, NetworkError):
            logger.warning("Telegram is unreachable: %s", context.error)
        else:
            logger.error("Update failed", exc_info=context.error)

    async def ticker() -> None:
        while True:
            await asyncio.sleep(TICK_SECONDS)
            try:
                now = datetime.now(config.timezone)
                if assistant.confirm_writes(now):
                    logger.warning("A write was lost and has been restored")
                reminder = assistant.reminder_due(now)
                if reminder:
                    await application.bot.send_message(config.user_id, reminder.text)
                    assistant.mark_reminder_sent(now)
                closed = assistant.workout_due(now)
                if closed:
                    await application.bot.send_message(config.user_id, closed.text)
                await refresh_dashboard(now)
            except NetworkError as error:
                logger.warning("Telegram is unreachable: %s", error)
            except (OSError, TelegramError, JournalBusy, UnicodeDecodeError):
                logger.exception("Background check failed, will try again")

    tasks: list[asyncio.Task[None]] = []

    async def on_start(app: Application) -> None:
        with contextlib.suppress(TelegramError):
            await app.bot.set_my_commands([BotCommand(*item) for item in COMMANDS])
        tasks.append(asyncio.create_task(ticker()))

    async def on_stop(app: Application) -> None:
        for task in tasks:
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task

    builder = ApplicationBuilder().token(config.token).post_init(on_start).post_stop(on_stop)
    if request is not None:
        builder = builder.request(request)
    application = builder.build()
    application.add_handler(TypeHandler(Update, gate), group=-1)
    application.add_handler(CommandHandler(["start"], start))
    application.add_handler(CommandHandler(["dash"], dash))

    handlers: dict[str, Handler] = {
        "f": assistant.focus,
        "l": assistant.learned,
        "w": assistant.words,
        "tt": assistant.tiktok,
        "sleep": assistant.sleep,
        "gym": assistant.gym,
        "eat": assistant.eat,
        "n": assistant.note,
        "today": assistant.today,
        "streak": assistant.streak,
        "undo": assistant.undo,
        "remind": assistant.remind,
        "help": assistant.help,
    }
    for name, handler in handlers.items():
        application.add_handler(CommandHandler(name, command(handler)))
    application.add_handler(CallbackQueryHandler(button))
    application.add_handler(MessageHandler(filters.COMMAND, unknown_command))
    application.add_handler(MessageHandler(filters.TEXT, text))
    application.add_handler(MessageHandler(filters.ALL, not_text))
    application.add_error_handler(on_error)
    return application


def configure_logging() -> None:
    DATA.mkdir(parents=True, exist_ok=True)
    handlers: list[logging.Handler] = [
        RotatingFileHandler(DATA / "bot.log", maxBytes=1_000_000, backupCount=2, encoding="utf-8")
    ]
    if sys.stderr is not None:
        handlers.append(logging.StreamHandler())
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s", handlers=handlers)
    # httpx logs every request URL, and a Telegram URL contains the bot token.
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)


def check() -> int:
    """For setup: the dependencies import and the settings make sense."""
    sys.stdout.reconfigure(encoding="utf-8")
    try:
        load_config()
    except ConfigError as error:
        print(error)
        return 1
    print("ok")
    return 0


def main() -> None:
    configure_logging()
    try:
        config = load_config()
    except ConfigError as error:
        logger.error("%s", error)
        raise SystemExit(1) from None
    journal = Journal(config.vault, commit=config.vault_git_commit)
    assistant = Assistant(journal, State(DATA / "state.json"), config.reminder_time, config.env_file)
    application = build_application(config, assistant)
    logger.info("Bot started")
    # Waiting updates are kept on purpose: they are what arrived while the computer was off.
    application.run_polling(allowed_updates=ALLOWED_UPDATES, drop_pending_updates=False, bootstrap_retries=-1)
