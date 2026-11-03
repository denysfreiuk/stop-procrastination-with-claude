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
    parse_hours,
    parse_minutes_and_text,
    parse_sleep_times,
    parse_vocabulary,
    read_vocabulary_line,
    split_clock,
    vocabulary_line,
)
from .config import set_env_value
from .files import atomic_write
from .journal import (
    FOCUS, FOOD, GYM, HABITS_PAGE, LEARNED, LOG, NOTE, PHONE, STUDY_PAGE, WORDS, Edit, Journal, Undo,
)
from .markdown import section_lines
from .workout import Lift, Workout, exercise_name, parse_set, set_text

PENDING_LIFETIME = timedelta(minutes=15)
CONFIRM_AFTER = timedelta(seconds=5)
# Changes from Obsidian on other devices reach the dashboard this often.
DASHBOARD_EVERY = timedelta(minutes=1)
# A workout with nothing done for this long is closed by itself, as of its last set.
WORKOUT_IDLE = timedelta(hours=2)
MAX_TOPICS = 5
MAX_EXERCISES = 8
MAX_FOODS = 6
MAX_UNDO = 20
MAX_FOCUS_MINUTES = 720
# A second press of 😴 sooner than this is a slip of the finger; later than the longest sleep, a forgotten morning.
SHORTEST_SLEEP = timedelta(minutes=30)
LONGEST_SLEEP = timedelta(hours=16)
# Undo steps that change no file: a set of the workout reaches the note only when the workout ends,
# and a bedtime only together with the getting up.
SET_UNDO = "workout"
BEDTIME_UNDO = "bedtime"

USAGE_FOCUS = "Приклад: /f 50 ML"
USAGE_GYM = "Приклад: /gym 60 ноги"
USAGE_SLEEP = "Приклад: /sleep 23:40 7:10 або /sleep 7.5"
FOOD_QUESTION = "Що їв? Якщо не щойно — з часом: 8:30 вівсянка"
USAGE_WORDS = "Приклад: /w borrow, lend або /w reluctant: She was reluctant to leave"
WORDS_QUESTION = """Які слова в Anki? Через кому: borrow, lend

З контекстом — після двокрапки, де зустрів:
reluctant: She was reluctant to leave (Friends)

Кожне слово можна писати з нового рядка."""
GYM_QUESTION = """🏋️ Почати тренування по підходах?

Або запиши одним рядком, скільки хвилин і що робив: 60 ноги"""
SET_HINT = "Після підходу напиши вагу і повторення: 60 10\nБез ваги — лише повторення: 12"

BUTTON_ROWS = (
    ("🎯 Фокус", "📚 Вивчив", "🔤 Слова"),
    ("🏋️ Зал", "😴 Сон", "📵 Тікток"),
    ("🍽 Їжа", "📝 Нотатка"),
    ("📊 Сьогодні", "↩️ Скасувати"),
)
HELP = """Будь-який текст іде в лог дня.

/f 50 ML — блок фокусу
/l текст — що вивчив
/w borrow, lend — слова в чергу на Anki
/w reluctant: речення, де зустрів — слово з контекстом
(ввечері /anki-from-notes у Claude Code дасть таблицю для вивчення)
/tt — зірвався на тікток
/sleep — ліг спати; ще раз — встав (або кнопка 😴 Сон)
/sleep 23:40 7:10 — сон заднім числом, якщо забув натиснути
/gym — тренування по підходах
/gym 60 ноги — зал одним рядком
/eat борщ — їжа; /eat 8:30 вівсянка — якщо їв раніше
/n текст — нотатка дня
/today — підсумок дня
/streak — стріки
/undo — скасувати останній запис
/remind 20:00 — час нагадування
/dash — закріпити дашборд дня заново

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


@dataclass(frozen=True)
class DashboardUpdate:
    text: str
    edit: int | None  # the pinned message to change in place
    replaces: int | None = None  # an earlier dashboard to unpin once a new one is sent


class State:
    """What survives a restart: recent topics, undo history, the last reminder's day, the dashboard."""

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
        self.dashboard_message: int | None = data.get("dashboard_message")
        self.dashboard_text: str | None = data.get("dashboard_text")
        self.exercises: list[str] = data.get("exercises", [])
        self.workout: Workout | None = Workout.from_dict(data["workout"]) if data.get("workout") else None
        self.foods: list[str] = data.get("foods", [])
        asleep = data.get("asleep_since")
        self.asleep_since: datetime | None = datetime.fromisoformat(asleep) if asleep else None

    def save(self) -> None:
        data = {
            "topics": self.topics,
            "undo": [asdict(item) for item in self.undo],
            "reminder_sent": self.reminder_sent,
            "dashboard_message": self.dashboard_message,
            "dashboard_text": self.dashboard_text,
            "exercises": self.exercises,
            "workout": self.workout.to_dict() if self.workout else None,
            "foods": self.foods,
            "asleep_since": self.asleep_since.isoformat() if self.asleep_since else None,
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
        self.dashboard_dirty = True
        self.dashboard_checked: datetime | None = None
        self.buttons: dict[str, Handler] = {
            "🎯 Фокус": self.focus,
            "📚 Вивчив": self.learned,
            "🔤 Слова": self.words,
            "😴 Сон": self.sleep,
            "📵 Тікток": self.tiktok,
            "🏋️ Зал": self.gym,
            "🍽 Їжа": self.eat,
            "📊 Сьогодні": self.today,
            "📝 Нотатка": self.note,
            "↩️ Скасувати": self.undo,
        }

    # Conversation

    def on_text(self, text: str, now: datetime) -> Reply:
        """A button, the answer to the bot's last question, or an entry for the log."""
        self.dashboard_dirty = True
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
        if self.state.workout and not self.state.workout.paused:
            return self._workout_text(text, now)
        return self.log(text, now)

    def on_command(self, handler: Handler, args: str, now: datetime) -> Reply:
        self.pending = None
        self.dashboard_dirty = True
        return handler(args, now)

    def on_button(self, data: str, now: datetime) -> Reply:
        """An inline button: `kind:value`."""
        self.pending = None
        self.dashboard_dirty = True
        kind, _, value = data.partition(":")
        if kind == "focus":
            return self._ask_topic(int(value), now)
        if kind == "topic":
            pending_minutes, _, index = value.partition(":")
            return self._save_focus(int(pending_minutes), self.state.topics[int(index)], now)
        if kind == "sleep":
            return self.sleep(value, now)
        if kind == "workout":
            return self._workout_button(value, now)
        if kind == "exercise" and self.state.workout:
            return self._start_exercise(self.state.exercises[int(value)], now)
        if kind == "food":
            return self.eat(self.state.foods[int(value)], now)
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
            return self._ask(self.words, WORDS_QUESTION, now)
        entries = parse_vocabulary(args)
        if not entries:
            raise CommandError(f"Не бачу слів. {USAGE_WORDS}")
        noted = [read_vocabulary_line(line) for line in self._section(now, WORDS)]
        known = {(word.lower(), context) for word, context in noted}
        fresh = [(word, context) for word, context in entries if (word.lower(), context) not in known]
        if not fresh:
            return Reply("Ці слова сьогодні вже записані.")
        # The same word met again in another context is one more example, not one more word.
        new_words = {word.lower() for word, _ in fresh} - {word.lower() for word, _ in noted}
        # Words go to Anki through /anki-from-notes' study table, so anki_done stays as it is.
        edit = Edit(
            now.date(),
            lines=tuple((WORDS, vocabulary_line(word, context)) for word, context in fresh),
            add_values={"new_words": len(new_words)} if new_words else {},
        )
        self._write(edit, f"слова: {', '.join(dict.fromkeys(word for word, _ in fresh))}", now)
        waiting = self.words_for_anki()
        with_context = " з контекстом" if any(context for _, context in fresh) else ""
        if not new_words:
            return Reply(f"✅ Додав ще один контекст (у черзі на Anki: {waiting})")
        return Reply(f"📥 +{len(new_words)}{with_context} у черзі на Anki (усього: {waiting})")

    def words_for_anki(self) -> int:
        return stats.words_for_anki(self.journal.days(), self.journal.read, self.journal.read_page(STUDY_PAGE))

    def _section(self, now: datetime, heading: str) -> list[str]:
        return section_lines(self.journal.read(now.date()) or "", heading)

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
        """😴 when going to bed and again when getting up; or the times, or the hours, afterwards."""
        if not args.strip():
            return self._bed_or_up(now)
        times = parse_sleep_times(args, USAGE_SLEEP)
        if times:
            bed_time, up_time = times
            up = now.replace(hour=up_time.hour, minute=up_time.minute, second=0, microsecond=0)
            if up > now:
                raise CommandError(f"О {up_time:%H:%M} ще не було. {USAGE_SLEEP}")
            bed = up.replace(hour=bed_time.hour, minute=bed_time.minute)
            if bed >= up:
                bed -= timedelta(days=1)
            return self._save_sleep(bed, up, now)
        hours = parse_hours(args, USAGE_SLEEP)
        self._write(Edit(now.date(), set_values={"sleep_hours": hours}), f"сон {hours:g} год", now)
        return Reply(f"✅ Сон: {hours:g} год")

    def _bed_or_up(self, now: datetime) -> Reply:
        since = self.state.asleep_since
        if since is not None and now - since < SHORTEST_SLEEP:
            self._forget_bedtime()
            return Reply("↩️ Скасував відбій: минуло менше пів години. Лягаєш — натисни 😴 Сон ще раз.")
        if since is not None and now - since <= LONGEST_SLEEP:
            return self._save_sleep(since, now, now)
        forgotten = "Учорашній відбій без підйому не рахую.\n" if since is not None else ""
        self.state.asleep_since = now
        self.state.undo = [*self.state.undo, Undo(BEDTIME_UNDO, (), {}, f"відбій о {clock(now)}")][-MAX_UNDO:]
        self.state.save()
        return Reply(f"{forgotten}😴 Ліг о {clock(now)}. Добраніч! Коли встанеш — знову 😴 Сон.")

    def _forget_bedtime(self) -> None:
        self.state.asleep_since = None
        self.state.undo = [item for item in self.state.undo if item.day != BEDTIME_UNDO]
        self.state.save()

    def _save_sleep(self, bed: datetime, up: datetime, now: datetime) -> Reply:
        """The night belongs to the day of getting up, as `sleep_hours` is last night's sleep."""
        minutes = round((up - bed).total_seconds() / 60)
        if not 0 < minutes <= LONGEST_SLEEP.total_seconds() / 60:
            raise CommandError(f"Сон має бути до {LONGEST_SLEEP.total_seconds() / 3600:g} годин. {USAGE_SLEEP}")
        self._forget_bedtime()
        hours = round(minutes / 60, 2)
        values = {"sleep_hours": hours, "bedtime": clock(bed), "wake_time": clock(up)}
        self._write(Edit(up.date(), set_values=values), f"сон {clock(bed)}–{clock(up)}", now)
        greeting = "☀️ Доброго ранку! " if up == now else "✅ "
        return Reply(f"{greeting}Спав {minutes // 60} год {minutes % 60:02d} хв ({clock(bed)} → {clock(up)})")

    def gym(self, args: str, now: datetime) -> Reply:
        if not args.strip():
            if self.state.workout:
                return self._workout_button("resume", now)
            start = ((("▶️ Почати тренування", "workout:start"),),)
            return self._ask(self.gym, GYM_QUESTION, now, start)
        minutes, what = parse_minutes_and_text(args, USAGE_GYM)
        line = f"- {clock(now)} · {minutes} хв" + (f" · {what}" if what else "")
        edit = Edit(now.date(), ((GYM, line),), {"gym": True}, {"gym_minutes": minutes})
        self._write(edit, f"зал {minutes} хв", now)
        return Reply(f"✅ Зал: {minutes} хв" + (f" · {what}" if what else ""))

    # The gym mode: while a workout runs, plain text is a set or the name of the next exercise.

    def _workout_button(self, action: str, now: datetime) -> Reply:
        workout = self.state.workout
        if action == "start" and workout is None:
            self.state.workout = Workout(started=now, last=now)
            self.state.save()
            return self._ask_exercise(f"🏋️ Тренування почалось о {clock(now)}. Яка перша вправа?")
        if workout is None:
            return Reply("Тренування вже закінчилось. Нове: /gym")
        workout.last = now
        if action == "finish":
            return self._finish_workout(now, now)
        workout.paused = action == "pause"
        self.state.save()
        if action == "pause":
            return Reply(
                "⏸ Тренування на паузі. Пиши що завгодно, усе піде як зазвичай.\nПовернутись: /gym або кнопка.",
                ((("▶️ Продовжити", "workout:resume"),),),
            )
        if action == "exercise" or workout.exercise is None:
            return self._ask_exercise("Яка вправа? Напиши назву або обери:")
        done = len(workout.sets_of(workout.exercise))
        if action == "set":
            return Reply(f"Підхід {done + 1} · {workout.exercise}: вага і повторення?", self._workout_buttons())
        return Reply(
            f"▶️ Тренування триває з {clock(workout.started)}. Зараз: {workout.exercise}, підходів: {done}.\n"
            "Напиши наступний підхід або назву нової вправи.",
            self._workout_buttons(),
        )

    def _ask_exercise(self, question: str) -> Reply:
        recent = [(name, f"exercise:{index}") for index, name in enumerate(self.state.exercises)]
        return Reply(question, tuple(tuple(recent[start : start + 2]) for start in range(0, len(recent), 2)))

    @staticmethod
    def _workout_buttons() -> Buttons:
        return (
            (("➕ Підхід", "workout:set"), ("🔄 Вправа", "workout:exercise")),
            (("⏸ Пауза", "workout:pause"), ("🏁 Завершити", "workout:finish")),
        )

    def _workout_text(self, text: str, now: datetime) -> Reply:
        workout = self.state.workout
        parsed = parse_set(one_line(text))
        if parsed is None:
            return self._start_exercise(text, now)
        if workout.exercise is None:
            raise CommandError("Спершу напиши назву вправи, а потім вагу і повторення.")
        weight, reps = parsed
        workout.sets.append(Lift(workout.exercise, weight, reps))
        workout.last = now
        label = f"підхід: {workout.exercise} {set_text(weight, reps)}"
        self.state.undo = [*self.state.undo, Undo(SET_UNDO, (), {}, label)][-MAX_UNDO:]
        self.state.save()
        number = len(workout.sets_of(workout.exercise))
        return Reply(
            f"✅ {workout.exercise}, підхід {number}: {set_text(weight, reps)}\nДалі просто напиши наступний підхід.",
            self._workout_buttons(),
        )

    def _start_exercise(self, text: str, now: datetime) -> Reply:
        workout = self.state.workout
        name = exercise_name(one_line(text))
        workout.exercise = name
        workout.paused = False
        workout.last = now
        self.state.exercises = [name, *(item for item in self.state.exercises if item.lower() != name.lower())]
        self.state.exercises = self.state.exercises[:MAX_EXERCISES]
        self.state.save()
        done = len(workout.sets_of(name))
        again = f" (уже підходів: {done})" if done else ""
        return Reply(f"🏋️ {name}{again}\n{SET_HINT}")

    def _finish_workout(self, end: datetime, now: datetime) -> Reply:
        workout, self.state.workout = self.state.workout, None
        # Sets are in the entry now: undo takes the whole workout back, not one set.
        self.state.undo = [item for item in self.state.undo if item.day != SET_UNDO]
        self.state.save()
        if not workout.sets:
            return Reply("🏁 Тренування закрив. Підходів не було, тож нічого не записав.")
        minutes = max(1, round((end - workout.started).total_seconds() / 60))
        lines = tuple((GYM, line) for line in workout.lines(minutes))
        edit = Edit(workout.started.date(), lines, {"gym": True}, {"gym_minutes": minutes})
        self._write(edit, f"тренування {minutes} хв", now)
        return Reply(f"🏁 {workout.summary(minutes)}")

    def workout_due(self, now: datetime) -> Reply | None:
        """Checked regularly: a forgotten workout is closed as of its last set."""
        workout = self.state.workout
        if workout is None or now - workout.last < WORKOUT_IDLE:
            return None
        reply = self._finish_workout(workout.last, now)
        return Reply(f"Закрив тренування сам: дві години без підходів.\n{reply.text}")

    def workout_line(self) -> str | None:
        workout = self.state.workout
        if workout is None:
            return None
        line = f"🏋️ Тренування з {clock(workout.started)} · підходів: {len(workout.sets)}"
        return line + (" · пауза" if workout.paused else "")

    def sleep_line(self) -> str | None:
        since = self.state.asleep_since
        return f"😴 Спиш з {clock(since)}" if since else None

    def eat(self, args: str, now: datetime) -> Reply:
        """What was eaten and when: now, or `8:30 вівсянка` for a meal written down later."""
        at, entry = split_clock(one_line(args))
        if not entry:
            foods = [(food[:30], f"food:{index}") for index, food in enumerate(self.state.foods)]
            rows = tuple(tuple(foods[start : start + 2]) for start in range(0, len(foods), 2))
            return self._ask(self.eat, FOOD_QUESTION, now, rows)
        day = now.date()
        if at is not None and at > now.time():
            # Just after midnight, a late dinner is still yesterday's.
            if now.hour >= 4:
                raise CommandError(f"О {at:%H:%M} ще не було. Час пиши той, коли їв.")
            day -= timedelta(days=1)
        moment = f"{at:%H:%M}" if at else clock(now)
        self._write(Edit(day, ((FOOD, f"- {moment} {entry}"),), by_time=True), f"їжа: {entry}", now)
        self.state.foods = [entry, *(food for food in self.state.foods if food.lower() != entry.lower())][:MAX_FOODS]
        self.state.save()
        return Reply(f"✅ {moment} {entry}")

    def note(self, args: str, now: datetime) -> Reply:
        entry = one_line(args)
        if not entry:
            return self._ask(self.note, "Що записати в нотатку дня?", now)
        self._write(Edit(now.date(), ((NOTE, entry),)), f"нотатка: {entry}", now)
        return Reply("✅ Записав у нотатку дня")

    # Overviews and settings

    def today(self, args: str, now: datetime) -> Reply:
        return Reply(stats.summary(self.journal.read(now.date()), now.date()))

    def streak(self, args: str, now: datetime) -> Reply:
        return Reply(stats.streak_report(self.journal.read, now.date()))

    def undo(self, args: str, now: datetime) -> Reply:
        if not self.state.undo:
            return Reply("Нема що скасовувати.")
        last = self.state.undo[-1]
        if last.day == SET_UNDO:
            if self.state.workout and self.state.workout.sets:
                self.state.workout.sets.pop()
        elif last.day == BEDTIME_UNDO:
            self.state.asleep_since = None
        else:
            self.journal.revert(last)
            self.unconfirmed = [item for item in self.unconfirmed if item.edit.lines != last.lines]
        self.state.undo = self.state.undo[:-1]
        self.state.save()
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
        return Reply(stats.reminder(self.journal.read(now.date()), now.date(), self.words_for_anki()))

    def mark_reminder_sent(self, now: datetime) -> None:
        self.state.reminder_sent = now.date().isoformat()
        self.state.save()

    # The pinned dashboard

    def dashboard_due(self, now: datetime, renew: bool = False) -> DashboardUpdate | None:
        """Checked regularly: right after the user wrote something, and once a minute for other devices.

        renew sends a new message even if the old one is fine, for when the user unpinned it.
        """
        stale = self.dashboard_checked is None or now - self.dashboard_checked >= DASHBOARD_EVERY
        if not (renew or self.dashboard_dirty or stale):
            return None
        self.dashboard_dirty = False
        self.dashboard_checked = now
        goals = stats.habit_goals(self.journal.read_page(HABITS_PAGE))
        going_on = [line for line in (self.workout_line(), self.sleep_line()) if line]
        text = stats.dashboard(self.journal.read, now.date(), goals, self.words_for_anki(), going_on)
        message = self.state.dashboard_message
        if renew or message is None:
            return DashboardUpdate(text, None, message)
        if text == self.state.dashboard_text:
            return None
        return DashboardUpdate(text, message)

    def dashboard_shown(self, message_id: int, text: str) -> None:
        self.state.dashboard_message = message_id
        self.state.dashboard_text = text
        self.state.save()
