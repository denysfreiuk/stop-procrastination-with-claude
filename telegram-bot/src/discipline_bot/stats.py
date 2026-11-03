"""Summaries of a day and streaks. The rules match Dashboard.md and the vault's CLAUDE.md."""

from __future__ import annotations

import re
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from datetime import date, timedelta

from .commands import read_vocabulary_line
from .journal import FOOD, LEARNED, SUMMARY, WORDS, to_number
from .markdown import list_items, properties, section_lines

MONTHS = (
    "січня", "лютого", "березня", "квітня", "травня", "червня",
    "липня", "серпня", "вересня", "жовтня", "листопада", "грудня",
)
WEEKDAYS = ("понеділок", "вівторок", "середа", "четвер", "пʼятниця", "субота", "неділя")
IN_ANKI = "Уже в Anki"
_IN_ANKI_LINE = re.compile(r"^- (\d{4}-\d{2}-\d{2}) · (.+?)\s*$")
# The goals live in Звички.md, in the line `const GOALS = { focusMinutes: 50, sleepHours: 7 };`.
_FOCUS_GOAL = re.compile(r"\bfocusMinutes:\s*(\d+(?:\.\d+)?)")
_SLEEP_GOAL = re.compile(r"\bsleepHours:\s*(\d+(?:\.\d+)?)")
ReadNote = Callable[[date], "str | None"]


@dataclass(frozen=True)
class Goals:
    focus_minutes: float = 50
    sleep_hours: float = 7


@dataclass(frozen=True)
class Day:
    focus_blocks: int
    focus_minutes: int
    screen_minutes: str
    relapse: bool
    sleep_hours: str
    gym: bool
    gym_minutes: int
    new_words: int
    learned: int
    has_words: bool
    has_food: bool


def read_day(text: str | None) -> Day:
    values = properties(text or "")
    return Day(
        focus_blocks=int(to_number(values.get("focus_blocks"))),
        focus_minutes=int(to_number(values.get("focus_minutes"))),
        screen_minutes=values.get("screen_time_min", ""),
        relapse=values.get("tiktok_relapse") == "true",
        sleep_hours=values.get("sleep_hours", ""),
        gym=values.get("gym") == "true",
        gym_minutes=int(to_number(values.get("gym_minutes"))),
        new_words=int(to_number(values.get("new_words"))),
        learned=len(list_items(text or "", LEARNED)),
        has_words=bool(section_lines(text or "", WORDS)),
        has_food=bool(section_lines(text or "", FOOD)),
    )


def format_day(day: date) -> str:
    return f"{day.day} {MONTHS[day.month - 1]}"


def filled(day: Day) -> list[str]:
    parts = []
    if day.focus_minutes:
        parts.append(f"🎯 Фокус: {day.focus_minutes} хв, блоків: {day.focus_blocks}")
    if day.learned:
        parts.append(f"📚 Вивчив: {day.learned}")
    if day.new_words:
        parts.append(f"🔤 Нових слів: {day.new_words}")
    if day.screen_minutes:
        parts.append(f"📱 Екран: {day.screen_minutes} хв")
    if day.relapse:
        parts.append("📵 Тікток: зрив")
    if day.sleep_hours:
        parts.append(f"😴 Сон: {day.sleep_hours} год")
    if day.gym:
        parts.append(f"🏋️ Зал: {day.gym_minutes} хв")
    if day.has_food:
        parts.append("🍽 Їжа: є записи")
    return parts


def missing(day: Day) -> list[str]:
    parts = {
        "фокус": day.focus_minutes,
        "що вивчив": day.learned,
        "нові слова": day.has_words,
        "екран": day.screen_minutes,
        "сон": day.sleep_hours,
        "їжа": day.has_food,
    }
    return [name for name, value in parts.items() if not value]


def summary(text: str | None, day: date) -> str:
    parsed = read_day(text)
    lines = [f"📊 {format_day(day)}", *(filled(parsed) or ["Поки нічого не записано."])]
    gaps = missing(parsed)
    if gaps:
        lines.append(f"Ще немає: {', '.join(gaps)}")
    return "\n".join(lines)


def reminder(text: str | None, day: date, words_for_anki: int = 0) -> str:
    parsed = read_day(text)
    lines = ["🌙 Час заповнити день.", *filled(parsed)]
    gaps = missing(parsed)
    lines.append(f"Ще немає: {', '.join(gaps)}" if gaps else "Усе заповнено 👍")
    if words_for_anki:
        lines.append(f"📥 На Anki чекає слів: {words_for_anki}. У Claude Code: /anki-from-notes")
    return "\n".join(lines)


def words_for_anki(days: Iterable[date], read: ReadNote, study_page: str) -> int:
    """Words written down for Anki that the study page does not list as already there.

    The plugin's word_queue counts the same way: one word a day, whatever the contexts.
    """
    done = {
        (match[1], match[2].lower())
        for line in section_lines(study_page, IN_ANKI)
        if (match := _IN_ANKI_LINE.match(line.strip()))
    }
    waiting = set()
    for day in days:
        for line in section_lines(read(day) or "", WORDS):
            word, _ = read_vocabulary_line(line)
            if word and (day.isoformat(), word.lower()) not in done:
                waiting.add((day.isoformat(), word.lower()))
    return len(waiting)


def studied(text: str) -> bool:
    day = read_day(text)
    return day.focus_minutes > 0 or day.learned > 0


def tiktok_free(text: str) -> bool:
    return not read_day(text).relapse


def streak(read: ReadNote, today: date, is_good: Callable[[str], bool]) -> int:
    """Today is still going: an empty today keeps the streak, a day without a note breaks it."""
    text = read(today)
    days = 1 if text is not None and is_good(text) else 0
    day = today - timedelta(days=1)
    while (text := read(day)) is not None and is_good(text):
        days += 1
        day -= timedelta(days=1)
    return days


def tiktok_streak(read: ReadNote, today: date) -> int:
    text = read(today)
    if text is not None and read_day(text).relapse:
        return 0
    return streak(read, today, tiktok_free)


def gym_days(read: ReadNote, today: date, days: int = 7) -> int:
    return sum(read_day(read(today - timedelta(days=offset))).gym for offset in range(days))


def habit_goals(habits_page: str) -> Goals:
    """The goals the habit tracker page uses, so the dashboard ticks the same habits."""
    focus = _FOCUS_GOAL.search(habits_page)
    sleep = _SLEEP_GOAL.search(habits_page)
    return Goals(
        float(focus[1]) if focus else Goals.focus_minutes,
        float(sleep[1]) if sleep else Goals.sleep_hours,
    )


def dashboard(read: ReadNote, today: date, goals: Goals, words_for_anki: int, workout: str | None = None) -> str:
    """The pinned message: today's habits as on the Звички page, then the numbers behind them.

    The first line is the habits alone, because the pinned bar in Telegram shows only the start.
    `workout` is a line about a workout that is still going.
    """
    text = read(today) or ""
    day = read_day(text)
    sleep = to_number(day.sleep_hours) if day.sleep_hours else None
    habits = (
        ("📵", not day.relapse),
        ("🎯", day.focus_minutes >= goals.focus_minutes),
        ("📚", day.learned > 0),
        ("🔤", day.new_words > 0),
        ("🏋️", day.gym),
        ("😴", sleep is not None and sleep >= goals.sleep_hours),
        ("📝", bool(section_lines(text, SUMMARY))),
    )
    done = sum(ok for _, ok in habits)

    def shown(value: str, unit: str) -> str:
        return f"{value} {unit}" if value else "—"

    return "\n".join(
        (
            " ".join(f"{icon}{'✅' if ok else '⬜'}" for icon, ok in habits),
            f"{format_day(today)}, {WEEKDAYS[today.weekday()]} · {done} з {len(habits)}",
            *((workout,) if workout else ()),
            "",
            f"🎯 Фокус: {day.focus_minutes} з {goals.focus_minutes:g} хв · блоків: {day.focus_blocks}",
            f"📚 Вивчив: {day.learned} · 🔤 Слів: {day.new_words} · 📥 На Anki: {words_for_anki}",
            f"😴 Сон: {shown(day.sleep_hours, 'год')} · 🏋️ Зал: {f'{day.gym_minutes} хв' if day.gym else '—'}",
            f"📱 Екран: {shown(day.screen_minutes, 'хв')} · 📵 Тікток: {'зрив' if day.relapse else 'без зривів'}",
            "",
            f"🔥 Навчання поспіль: {streak(read, today, studied)} · 📵 Без тіктока: {tiktok_streak(read, today)}",
        )
    )


def streak_report(read: ReadNote, today: date) -> str:
    return "\n".join(
        (
            f"🔥 Навчання поспіль: {streak(read, today, studied)}",
            f"📵 Без тіктока поспіль: {tiktok_streak(read, today)}",
            f"🏋️ Тренувань за 7 днів: {gym_days(read, today)}",
        )
    )
