"""Parsing of command arguments. Bad input raises CommandError with text for the user."""

from __future__ import annotations

import re
from datetime import time

MAX_DAY_MINUTES = 1440
_INTEGER = re.compile(r"^\d+$")
_CLOCK = re.compile(r"^(\d{1,2})[:.](\d{2})$")
_LEADING_CLOCK = re.compile(r"^(\d{1,2})[:.](\d{2})\s+(\S.*)$")
_TWO_CLOCKS = re.compile(r"^(\d{1,2}[:.]\d{2})\s*(?:[-–—]|\s)\s*(\d{1,2}[:.]\d{2})$")
_WORD_SEPARATORS = re.compile(r"[,;\n]")
# "word: context" or "word — context". A colon must be followed by a space, so links stay whole.
_CONTEXT = re.compile(r"^(.*?)\s*(?::\s|\s[—–-]\s)\s*(.+)$")
NOTE_CONTEXT = " — "


class CommandError(Exception):
    """The message is shown to the user as it is."""


def one_line(text: str) -> str:
    """Every entry stays one line, so sections, /undo and statistics can rely on it."""
    return " / ".join(part.strip() for part in text.splitlines() if part.strip())


def parse_minutes_and_text(args: str, usage: str, *, high: int = MAX_DAY_MINUTES) -> tuple[int, str]:
    """`50 ML` or `ML 50`: the first whole number is the minutes, the rest is the text."""
    words = one_line(args).split()
    for index, word in enumerate(words):
        if _INTEGER.match(word):
            minutes = int(word)
            if not 1 <= minutes <= high:
                raise CommandError(f"Хвилин має бути від 1 до {high}. {usage}")
            return minutes, " ".join(words[:index] + words[index + 1:])
    raise CommandError(f"Не бачу хвилин. {usage}")


def parse_words(args: str) -> list[str]:
    unique: dict[str, str] = {}
    for part in _WORD_SEPARATORS.split(args):
        word = part.strip()
        if word:
            unique.setdefault(word.lower(), word)
    return list(unique.values())


def parse_vocabulary(args: str) -> list[tuple[str, str]]:
    """Words with the context they were met in, if any.

    Each line is read on its own: `borrow, lend` gives two words without context,
    `reluctant: She was reluctant to leave (Friends)` gives one word with its context,
    and a context after several words belongs to each of them.
    """
    entries: dict[tuple[str, str], tuple[str, str]] = {}
    for line in args.splitlines():
        match = _CONTEXT.match(line.strip())
        words, context = (match[1], match[2].strip()) if match else (line, "")
        for word in parse_words(words):
            entries.setdefault((word.lower(), context), (word, context))
    return list(entries.values())


def vocabulary_line(word: str, context: str) -> str:
    return f"- {word}{NOTE_CONTEXT}{context}" if context else f"- {word}"


def read_vocabulary_line(line: str) -> tuple[str, str]:
    """The word and its context from a line of «Нові слова», written by the bot or by hand."""
    word, _, context = line.strip().removeprefix("- ").partition(NOTE_CONTEXT)
    return word.strip(), context.strip()


def parse_hours(args: str, usage: str) -> float:
    """Hours: `7.5`, `7,5`, `7:30`."""
    text = args.strip().replace(",", ".")
    clock = _CLOCK.match(text) if ":" in text else None
    try:
        hours = int(clock[1]) + int(clock[2]) / 60 if clock else float(text)
    except ValueError:
        raise CommandError(f"Не розумію число. {usage}") from None
    if not 0 <= hours <= 24:
        raise CommandError(f"Годин має бути від 0 до 24. {usage}")
    return round(hours, 2)


def parse_clock(text: str, usage: str = "Час пиши так: /remind 20:00") -> time:
    match = _CLOCK.match(text.strip())
    if match and int(match[1]) < 24 and int(match[2]) < 60:
        return time(int(match[1]), int(match[2]))
    raise CommandError(usage)


def split_clock(text: str) -> tuple[time | None, str]:
    """`8:30 вівсянка` → (08:30, `вівсянка`): an entry written later than it happened."""
    match = _LEADING_CLOCK.match(text.strip())
    if match and int(match[1]) < 24 and int(match[2]) < 60:
        return time(int(match[1]), int(match[2])), match[3].strip()
    return None, text.strip()


def parse_sleep_times(text: str, usage: str) -> tuple[time, time] | None:
    """`23:40 7:10` or `23:40-7:10`: when the user went to bed and got up; None for anything else."""
    match = _TWO_CLOCKS.match(text.strip())
    if not match:
        return None
    return parse_clock(match[1], usage), parse_clock(match[2], usage)
