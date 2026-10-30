"""What the bot does with each message. No Telegram here: it takes text and returns a Reply."""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import asdict, dataclass, replace
from datetime import datetime, time, timedelta
from functools import partial
from pathlib import Path
from typing import Any

from . import stats
from .commands import (
    CommandError,
    one_line,
    parse_clock,
    parse_duration,
    parse_energy,
    parse_hours,
    parse_minutes_and_text,
    parse_words,
)
from .config import set_env_value
from .files import atomic_write
from .journal import FOCUS, FOOD, GYM, LEARNED, LOG, NOTE, PHONE, WORDS, Edit, Journal, Undo
from .markdown import section_lines

PENDING_LIFETIME = timedelta(minutes=15)
CONFIRM_AFTER = timedelta(seconds=5)
MAX_TOPICS = 5
MAX_UNDO = 20
MAX_FOCUS_MINUTES = 720

USAGE_FOCUS = "Приклад: /f 50 ML"
USAGE_GYM = "Приклад: /gym 60 ноги"
USAGE_SCREEN = "Приклад: /s 95 або /s 1:35"
USAGE_SLEEP = "Приклад: /sleep 7.5"
USAGE_ENERGY = "Приклад: /e 4"

BUTTON_ROWS = (
    ("🎯 Фокус", "📚 Вивчив", "🔤 Слова"),
    ("😴 Сон", "📱 Екран", "📵 Тікток"),
    ("🏋️ Зал", "🍽 Їжа", "🔋 Енергія"),
    ("📊 Сьогодні", "📝 Нотатка", "↩️ Скасувати"),
)
HELP = """Будь-який текст іде в лог дня.

/f 50 ML — блок фокусу
/l текст — що вивчив
/w borrow, lend — нові слова
/s 95 — час екрана, хвилини
/tt — зірвався на тікток
/sleep 7.5 — сон, години
/gym 60 ноги — зал
/eat текст — їжа
/e 4 — енергія дня, 1–5
/n текст — нотатка дня
/today — підсумок дня
/streak — стріки
/undo — скасувати останній запис
/remind 20:00 — час нагадування

Команди без тексту самі спитають, що записати."""

Handler = Callable[[str, datetime], "Reply"]
Buttons = tuple[tuple[tuple[str, str], ...], ...]


@dataclass(frozen=True)
class Reply:
    text: str
    buttons: Buttons = ()


@dataclass(frozen=True)
class Pending:
    handler: Handler
    created: datetime


@dataclass(frozen=True)
class Unconfirmed:
    edit: Edit
    written: datetime


class State:
    """What survives a restart: recent topics, undo history, the last reminder's day."""

    def __init__(self, path: Path) -> None:
        self.path = path
        try:
            data: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            data = {}
        self.topics: list[str] = data.get("topics", [])
        self.undo: list[Undo] = [
            Undo(item["day"], tuple(map(tuple, item["lines"])), item["previous"], item.get("label", ""))
            for item in data.get("undo", [])
        ]
        self.reminder_sent: str | None = data.get("reminder_sent")

    def save(self) -> None:
        data = {
            "topics": self.topics,
            "undo": [asdict(item) for item in self.undo],
            "reminder_sent": self.reminder_sent,
        }
        self.path.parent.mkdir(parents=True, exist_ok=True)
        atomic_write(self.path, json.dumps(data, ensure_ascii=False, indent=2).encode("utf-8"))


def clock(now: datetime) -> str:
    return now.strftime("%H:%M")


class Assistant:
    def __init__(self, journal: Journal, state: State, reminder_time: time, env_file: Path) -> None:
        self.journal = journal
        self.state = state
        self.reminder_time = reminder_time
        self.env_file = env_file
        self.pending: Pending | None = None
        self.unconfirmed: list[Unconfirmed] = []
        self.buttons: dict[str, Handler] = {
            "🎯 Фокус": self.focus,
            "📚 Вивчив": self.learned,
            "🔤 Слова": self.words,
            "😴 Сон": self.sleep,
            "📱 Екран": self.screen,
            "📵 Тікток": self.tiktok,
            "🏋️ Зал": self.gym,
            "🍽 Їжа": self.eat,
            "🔋 Енергія": self.energy,
            "📊 Сьогодні": self.today,
            "📝 Нотатка": self.note,
            "↩️ Скасувати": self.undo,
        }

    # Conversation

    def on_text(self, text: str, now: datetime) -> Reply:
        """A button, the answer to the bot's last question, or an entry for the log."""
        action = self.buttons.get(text.strip())
        if action:
            self.pending = None
            return action("", now)
        pending, self.pending = self.pending, None
        if pending and now - pending.created <= PENDING_LIFETIME:
            try:
                return pending.handler(text, now)
            except CommandError:
                self.pending = pending
                raise
        return self.log(text, now)

    def on_command(self, handler: Handler, args: str, now: datetime) -> Reply:
        self.pending = None
        return handler(args, now)

    def on_button(self, data: str, now: datetime) -> Reply:
        """An inline button: `kind:value`."""
        self.pending = None
        kind, _, value = data.partition(":")
        if kind == "focus":
            return self._ask_topic(int(value), now)
        if kind == "topic":
            pending_minutes, _, index = value.partition(":")
            return self._save_focus(int(pending_minutes), self.state.topics[int(index)], now)
        if kind == "sleep":
            return self.sleep(value, now)
        if kind == "energy":
            return self.energy(value, now)
        return Reply("Ця кнопка вже не працює.")

    def _ask(self, handler: Handler, question: str, now: datetime, buttons: Buttons = ()) -> Reply:
        self.pending = Pending(handler, now)
        return Reply(question, buttons)

    def _write(self, edit: Edit, label: str, now: datetime) -> None:
        undo = self.journal.apply(edit, label)
        self.state.undo = [*self.state.undo, undo][-MAX_UNDO:]
        self.state.save()
        # A newer value of the same property is not a lost write.
        self.unconfirmed = [
            replace(item, edit=replace(item.edit, set_values={
                key: value for key, value in item.edit.set_values.items() if key not in edit.set_values
            }))
            for item in self.unconfirmed
        ]
        self.unconfirmed.append(Unconfirmed(edit, now))

    def confirm_writes(self, now: datetime) -> list[Edit]:
        """Called regularly; returns the edits that had to be written again."""
        due = [item for item in self.unconfirmed if now - item.written >= CONFIRM_AFTER]
        self.unconfirmed = [item for item in self.unconfirmed if now - item.written < CONFIRM_AFTER]
        return [item.edit for item in due if self.journal.restore_if_lost(item.edit)]

    # Entries

    def log(self, text: str, now: datetime) -> Reply:
        entry = one_line(text)
        if not entry:
            return Reply("Тут порожньо, нічого не записав.")
        self._write(Edit(now.date(), ((LOG, f"- {clock(now)} {entry}"),)), f"лог: {entry}", now)
        return Reply(f"✅ Лог · {clock(now)}")

    def focus(self, args: str, now: datetime) -> Reply:
        if not args.strip():
            options = tuple((str(minutes), f"focus:{minutes}") for minutes in (25, 50, 90))
            return self._ask(self.focus, "Скільки хвилин і яка тема? Наприклад: 50 ML", now, (options,))
        minutes, topic = parse_minutes_and_text(args, USAGE_FOCUS, high=MAX_FOCUS_MINUTES)
        topic = topic or (self.state.topics[0] if self.state.topics else "")
        if not topic:
            return self._ask_topic(minutes, now)
        return self._save_focus(minutes, topic, now)

    def _ask_topic(self, minutes: int, now: datetime) -> Reply:
        rows = tuple(((topic, f"topic:{minutes}:{index}"),) for index, topic in enumerate(self.state.topics))
        return self._ask(partial(self._focus_topic, minutes), "Яка тема?", now, rows)

    def _focus_topic(self, minutes: int, text: str, now: datetime) -> Reply:
        topic = one_line(text)
        if not topic:
            raise CommandError("Напиши тему одним словом або кількома.")
        return self._save_focus(minutes, topic, now)

    def _save_focus(self, minutes: int, topic: str, now: datetime) -> Reply:
        edit = Edit(
            now.date(),
            lines=((FOCUS, f"- {clock(now)} · {minutes} хв · {topic}"),),
            add_values={"focus_blocks": 1, "focus_minutes": minutes},
        )
        self.state.topics = [topic, *(item for item in self.state.topics if item != topic)][:MAX_TOPICS]
        self._write(edit, f"фокус {minutes} хв · {topic}", now)
        day = stats.read_day(self.journal.read(now.date()))
        return Reply(f"✅ {minutes} хв · {topic}\nСьогодні: {day.focus_minutes} хв, блоків: {day.focus_blocks}")

    def learned(self, args: str, now: datetime) -> Reply:
        entry = one_line(args)
        if not entry:
            return self._ask(self.learned, "Що вивчив?", now)
        edit = Edit(now.date(), ((LEARNED, f"- {clock(now)} {entry}"),), {"anki_done": False})
        self._write(edit, f"вивчив: {entry}", now)
        return Reply("✅ Записав у «Що вивчив»")

    def words(self, args: str, now: datetime) -> Reply:
        if not args.strip():
            return self._ask(self.words, "Які слова? Через кому: borrow, lend", now)
        known = {line.removeprefix("- ").strip().lower() for line in self._section(now, WORDS)}
        fresh = [word for word in parse_words(args) if word.lower() not in known]
        if not fresh:
            return Reply("Ці слова сьогодні вже записані.")
        edit = Edit(
            now.date(),
            lines=tuple((WORDS, f"- {word}") for word in fresh),
            set_values={"anki_done": False},
            add_values={"new_words": len(fresh)},
        )
        self._write(edit, f"слова: {', '.join(fresh)}", now)
        total = stats.read_day(self.journal.read(now.date())).new_words
        return Reply(f"✅ +{len(fresh)} (за сьогодні: {total})")

    def _section(self, now: datetime, heading: str) -> list[str]:
        return section_lines(self.journal.read(now.date()) or "", heading)

    def screen(self, args: str, now: datetime) -> Reply:
        if not args.strip():
            return self._ask(self.screen, "Скільки часу екрана? У хвилинах або 1:35", now)
        minutes = parse_duration(args, USAGE_SCREEN)
        self._write(Edit(now.date(), set_values={"screen_time_min": minutes}), f"екран {minutes} хв", now)
        return Reply(f"✅ Екран: {minutes} хв")

    def tiktok(self, args: str, now: datetime) -> Reply:
        reason = one_line(args)
        lines = ((PHONE, f"- {clock(now)} зрив: {reason}"),) if reason else ()
        self._write(Edit(now.date(), lines, {"tiktok_relapse": True}), "зрив на тікток", now)
        if reason:
            return Reply("📵 Записав зрив і причину")
        return self._ask(self._tiktok_reason, "📵 Записав. Чому так вийшло?", now)

    def _tiktok_reason(self, text: str, now: datetime) -> Reply:
        reason = one_line(text)
        if not reason:
            raise CommandError("Напиши причину кількома словами.")
        self._write(Edit(now.date(), ((PHONE, f"- {clock(now)} зрив: {reason}"),)), f"причина: {reason}", now)
        return Reply("✅ Причину записав")

    def sleep(self, args: str, now: datetime) -> Reply:
        if not args.strip():
            options = tuple((value, f"sleep:{value}") for value in ("6", "6.5", "7", "7.5", "8", "8.5"))
            return self._ask(self.sleep, "Скільки спав?", now, (options[:3], options[3:]))
        hours = parse_hours(args, USAGE_SLEEP)
        self._write(Edit(now.date(), set_values={"sleep_hours": hours}), f"сон {hours:g} год", now)
        return Reply(f"✅ Сон: {hours:g} год")

    def gym(self, args: str, now: datetime) -> Reply:
        if not args.strip():
            return self._ask(self.gym, "Скільки хвилин і що робив? Наприклад: 60 ноги", now)
        minutes, what = parse_minutes_and_text(args, USAGE_GYM)
        line = f"- {clock(now)} · {minutes} хв" + (f" · {what}" if what else "")
        edit = Edit(now.date(), ((GYM, line),), {"gym": True}, {"gym_minutes": minutes})
        self._write(edit, f"зал {minutes} хв", now)
        return Reply(f"✅ Зал: {minutes} хв" + (f" · {what}" if what else ""))

    def eat(self, args: str, now: datetime) -> Reply:
        entry = one_line(args)
        if not entry:
            return self._ask(self.eat, "Що їв?", now)
        self._write(Edit(now.date(), ((FOOD, f"- {clock(now)} {entry}"),)), f"їжа: {entry}", now)
        return Reply("✅ Записав їжу")

    def note(self, args: str, now: datetime) -> Reply:
        entry = one_line(args)
        if not entry:
            return self._ask(self.note, "Що записати в нотатку дня?", now)
        self._write(Edit(now.date(), ((NOTE, entry),)), f"нотатка: {entry}", now)
        return Reply("✅ Записав у нотатку дня")

    def energy(self, args: str, now: datetime) -> Reply:
        if not args.strip():
            options = tuple((str(value), f"energy:{value}") for value in range(1, 6))
            return self._ask(self.energy, "Яка енергія сьогодні?", now, (options,))
        value = parse_energy(args, USAGE_ENERGY)
        self._write(Edit(now.date(), set_values={"energy": value}), f"енергія {value}", now)
        return Reply(f"✅ Енергія: {value}")

    # Overviews and settings

    def today(self, args: str, now: datetime) -> Reply:
        return Reply(stats.summary(self.journal.read(now.date()), now.date()))

    def streak(self, args: str, now: datetime) -> Reply:
        return Reply(stats.streak_report(self.journal.read, now.date()))

    def undo(self, args: str, now: datetime) -> Reply:
        if not self.state.undo:
            return Reply("Нема що скасовувати.")
        last = self.state.undo[-1]
        self.journal.revert(last)
        self.state.undo = self.state.undo[:-1]
        self.state.save()
        self.unconfirmed = [item for item in self.unconfirmed if item.edit.lines != last.lines]
        return Reply(f"↩️ Скасовано: {last.label}")

    def remind(self, args: str, now: datetime) -> Reply:
        if not args.strip():
            return Reply(f"Нагадую о {self.reminder_time:%H:%M}. Змінити: /remind 21:30")
        self.reminder_time = parse_clock(args)
        set_env_value(self.env_file, "REMINDER_TIME", f"{self.reminder_time:%H:%M}")
        if now.time() < self.reminder_time:
            self.state.reminder_sent = None
            self.state.save()
        return Reply(f"✅ Нагадуватиму о {self.reminder_time:%H:%M}")

    def help(self, args: str, now: datetime) -> Reply:
        return Reply(HELP)

    def reminder_due(self, now: datetime) -> Reply | None:
        """Checked regularly, so a reminder missed in sleep mode comes right after waking up."""
        if now.time() < self.reminder_time or self.state.reminder_sent == now.date().isoformat():
            return None
        return Reply(stats.reminder(self.journal.read(now.date()), now.date()))

    def mark_reminder_sent(self, now: datetime) -> None:
        self.state.reminder_sent = now.date().isoformat()
        self.state.save()
