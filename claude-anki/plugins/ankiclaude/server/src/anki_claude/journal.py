"""The Obsidian journal: reading daily notes and the few changes Claude's commands make.

Claude can read everything here, but in a daily note it can only append to `## Підсумок`
and set `anki_done: true`, plus create a new weekly review and keep the page of words to
study. So the vault's main rule, that the user's entries are never rewritten, holds in code.
Metrics are computed here as well, not by the model. The Telegram bot has its own copy of
the line helpers, because the plugin gets installed apart from the repository.

Words from `## Нові слова` wait for Anki until they are listed in `## Уже в Anki` of the
study page. That list lives outside the daily notes on purpose: the bot appends new words
to the notes on the server, and marking lines next to them would make git conflicts.
"""

from __future__ import annotations

import os
import re
import time
from collections.abc import Callable, Iterable
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from .errors import JournalError

DAILY_FOLDER = Path("Journal") / "Daily"
WEEKLY_FOLDER = Path("Journal") / "Weekly"
WEEKLY_TEMPLATE = Path("Templates") / "Weekly.md"
STUDY_PAGE = Path("Слова на вивчення.md")

LEARNED = "Що вивчив"
WORDS = "Нові слова"
SUMMARY = "Підсумок"
ANKI_SECTIONS = (LEARNED,)
STUDYING = "Вчу зараз"
IN_ANKI = "Уже в Anki"
NOTE_CONTEXT = " — "
STUDY_PAGE_TEXT = """# Слова на вивчення

Таблицю складає /anki-from-notes зі слів, записаних через /w. Вивчи її, а наступний запуск /anki-from-notes
(чи «готово» в тій самій розмові) додасть ці слова в Anki. Сторінку веде Claude: руками її краще не правити.

## Вчу зараз

## Уже в Anki
"""

WEEKDAYS = ("пн", "вт", "ср", "чт", "пт", "сб", "нд")
WEEKLY_PROPERTIES = (
    "focus_minutes", "focus_blocks", "learning_days", "tiktok_free_days", "gym_days", "new_words",
    "avg_sleep_hours",
)

KEY_LINE = re.compile(r"^([A-Za-z_][\w-]*):[ \t]*(.*?)[ \t]*$")
LIST_ITEM = re.compile(r"^\s*(?:[-*+]|\d+\.)\s+\S")
TOP_HEADING = re.compile(r"^#{1,2}\s")
NOTE_NAME = re.compile(r"^\d{4}-\d{2}-\d{2}\.md$")
IN_ANKI_LINE = re.compile(r"^- (\d{4}-\d{2}-\d{2}) · (.+?)\s*$")
FENCE = "```"
WRITE_TRIES = 5
REPLACE_TRIES = 7


def _frontmatter_end(lines: list[str]) -> int | None:
    if not lines or lines[0].lstrip("﻿").rstrip() != "---":
        return None
    for index, line in enumerate(lines[1:], start=1):
        if line.rstrip() == "---":
            return index
    return None


def properties(text: str) -> dict[str, str]:
    lines = text.split("\n")
    end = _frontmatter_end(lines)
    values: dict[str, str] = {}
    if end is not None:
        for line in lines[1:end]:
            match = KEY_LINE.match(line)
            if match:
                values[match[1]] = match[2].strip("\"'")
    return values


def set_property(text: str, key: str, value: str) -> str:
    lines = text.split("\n")
    line = f"{key}: {value}" if value else f"{key}:"
    end = _frontmatter_end(lines)
    if end is None:
        return "\n".join(["---", line, "---", *lines])
    for index in range(1, end):
        match = KEY_LINE.match(lines[index])
        if match and match[1] == key:
            lines[index] = line
            return "\n".join(lines)
    lines.insert(end, line)
    return "\n".join(lines)


def typed(value: str) -> bool | int | float | str | None:
    if value == "":
        return None
    if value in {"true", "false"}:
        return value == "true"
    try:
        number = float(value)
    except ValueError:
        return value
    return int(number) if number.is_integer() else number


def sections(text: str) -> dict[str, list[str]]:
    """Filled sections of a note: heading → its non-empty lines."""
    lines = text.split("\n")
    end = _frontmatter_end(lines)
    found: dict[str, list[str]] = {}
    current = None
    fenced = False
    for line in lines[0 if end is None else end + 1 :]:
        if line.lstrip().startswith(FENCE):
            fenced = not fenced
        elif not fenced and line.startswith("## "):
            current = line[3:].strip()
            found.setdefault(current, [])
            continue
        elif not fenced and TOP_HEADING.match(line):
            current = None
            continue
        if current is not None and line.strip():
            found[current].append(line)
    return {heading: body for heading, body in found.items() if body}


def _section_span(lines: list[str], heading: str) -> tuple[int, int] | None:
    title = f"## {heading}"
    start = None
    fenced = False
    for index, line in enumerate(lines):
        if line.lstrip().startswith(FENCE):
            fenced = not fenced
        elif fenced:
            continue
        elif start is None:
            if line.rstrip() == title:
                start = index
        elif TOP_HEADING.match(line):
            return start, index
    return None if start is None else (start, len(lines))


def append_lines(text: str, heading: str, new_lines: list[str]) -> str:
    lines = text.split("\n")
    span = _section_span(lines, heading)
    if span is None:
        return "\n".join([f"{text.rstrip()}\n\n## {heading}", *new_lines, ""])
    start, end = span
    position = end
    while position > start + 1 and not lines[position - 1].strip():
        position -= 1
    lines[position:position] = new_lines
    return "\n".join(lines)


def replace_section(text: str, heading: str, body: str) -> str:
    """Only for a review being created: the template's placeholders are not the user's text."""
    lines = text.split("\n")
    span = _section_span(lines, heading)
    content = body.strip().split("\n") if body.strip() else []
    if span is None:
        return append_lines(text, heading, content)
    return "\n".join([*lines[: span[0] + 1], *content, "", *lines[span[1] :]])


def vocabulary_entry(line: str) -> tuple[str, str]:
    """The word and its context from a line of «Нові слова», written by the bot or by hand."""
    word, _, context = line.strip().removeprefix("- ").partition(NOTE_CONTEXT)
    return word.strip(), context.strip()


def words_in_anki(page: str) -> set[tuple[str, str]]:
    """(day, word in lower case) of every word the study page lists as already in Anki."""
    lines = sections(page).get(IN_ANKI, [])
    return {(match[1], match[2].lower()) for line in lines if (match := IN_ANKI_LINE.match(line.strip()))}


def parse_date(value: str) -> date:
    try:
        return date.fromisoformat(value.strip())
    except ValueError:
        raise JournalError(f"Дата {value!r} не у форматі YYYY-MM-DD.") from None


def week_label(day: date) -> str:
    year, week, _ = day.isocalendar()
    return f"{year}-W{week:02d}"


def number(value: object) -> float:
    return value if isinstance(value, (int, float)) and not isinstance(value, bool) else 0


def learned_something(day: dict[str, Any]) -> bool:
    items = day["sections"].get(LEARNED, [])
    return number(day["properties"].get("focus_minutes")) > 0 or any(LIST_ITEM.match(line) for line in items)


def totals(days: list[dict[str, Any]]) -> dict[str, Any]:
    """Metrics of a period. The rules match Dashboard.md and the bot's /streak."""

    def total(key: str) -> int:
        return int(sum(number(day["properties"].get(key)) for day in days))

    def average(key: str) -> float | None:
        values = [number(day["properties"][key]) for day in days if day["properties"].get(key) is not None]
        return round(sum(values) / len(values), 1) if values else None

    return {
        "days_with_notes": len(days),
        "focus_minutes": total("focus_minutes"),
        "focus_blocks": total("focus_blocks"),
        "learning_days": sum(learned_something(day) for day in days),
        "tiktok_free_days": sum(day["properties"].get("tiktok_relapse") is not True for day in days),
        "gym_days": sum(day["properties"].get("gym") is True for day in days),
        "new_words": total("new_words"),
        "avg_sleep_hours": average("sleep_hours"),
    }


def _atomic_write(path: Path, data: bytes) -> None:
    # The leading dot keeps Obsidian from indexing the temporary file.
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    try:
        with temporary.open("wb") as file:
            file.write(data)
            file.flush()
            os.fsync(file.fileno())
        for attempt in range(REPLACE_TRIES):
            try:
                os.replace(temporary, path)
                return
            except PermissionError:
                if attempt == REPLACE_TRIES - 1:
                    raise
                time.sleep(0.05 * 2**attempt)
    finally:
        temporary.unlink(missing_ok=True)


class Journal:
    def __init__(self, vault: Path, timezone: str) -> None:
        if not vault.is_dir():
            raise JournalError(f"Не знайдено vault: {vault}.", "Перевір VAULT_PATH у .env.")
        self.vault = vault
        try:
            self.zone = ZoneInfo(timezone)
        except (ZoneInfoNotFoundError, ValueError):
            raise JournalError(f"Невідомий часовий пояс {timezone}.", "Перевір TIMEZONE у .env.") from None

    def today(self) -> date:
        return datetime.now(self.zone).date()

    def note_path(self, day: date) -> Path:
        return self.vault / DAILY_FOLDER / f"{day.isoformat()}.md"

    def weekly_path(self, week: str) -> Path:
        return self.vault / WEEKLY_FOLDER / f"{week}.md"

    def _read(self, path: Path) -> str:
        return path.read_bytes().decode("utf-8").replace("\r\n", "\n")

    def _note_days(self) -> list[date]:
        folder = self.vault / DAILY_FOLDER
        names = (path.name for path in folder.glob("*.md")) if folder.is_dir() else ()
        return sorted(date.fromisoformat(name[:10]) for name in names if NOTE_NAME.match(name))

    def _day(self, day: date) -> dict[str, Any]:
        text = self._read(self.note_path(day))
        return {
            "date": day.isoformat(),
            "weekday": WEEKDAYS[day.weekday()],
            "properties": {key: typed(value) for key, value in properties(text).items() if key != "date"},
            "sections": sections(text),
        }

    def read(
        self,
        date_from: str | None = None,
        date_to: str | None = None,
        last_notes: int | None = None,
        only_pending_anki: bool = False,
    ) -> dict[str, Any]:
        today = self.today()
        existing = self._note_days()
        first = parse_date(date_from) if date_from else None
        last = parse_date(date_to) if date_to else None
        if only_pending_anki:
            chosen = [day for day in existing if (not first or day >= first) and (not last or day <= last)]
        elif last_notes:
            chosen = [day for day in existing if day <= (last or today)][-last_notes:]
        else:
            first = first or last or today
            last = last or (today if date_from else first)
            chosen = [day for day in existing if first <= day <= last]

        days = [self._day(day) for day in chosen]
        if only_pending_anki:
            days = [day for day in days if self._pending_anki(day)]
            for day in days:
                day["sections"] = {key: value for key, value in day["sections"].items() if key in ANKI_SECTIONS}

        newest = chosen[-1] if chosen else today
        span_start = first or (chosen[0] if chosen else today)
        span_end = last or newest
        missing_days = [] if only_pending_anki else [
            day.isoformat()
            for offset in range((span_end - span_start).days + 1)
            if (day := span_start + timedelta(days=offset)) not in chosen
        ]
        return {
            "today": today.isoformat(),
            "days": days,
            "missing_days": missing_days,
            "totals": totals(days),
            "week": week_label(newest),
            "weekly_review_exists": self.weekly_path(week_label(newest)).exists(),
        }

    @staticmethod
    def _pending_anki(day: dict[str, Any]) -> bool:
        return day["properties"].get("anki_done") is not True and any(key in day["sections"] for key in ANKI_SECTIONS)

    def _update(self, path: Path, change: Callable[[str], str]) -> None:
        """Change a note, starting over if someone else wrote it between reading and writing."""
        for _ in range(WRITE_TRIES):
            before = path.stat()
            raw = path.read_bytes()
            windows_endings = b"\r\n" in raw
            text = raw.decode("utf-8").replace("\r\n", "\n")
            updated = change(text)
            if updated == text:
                return
            data = (updated.replace("\n", "\r\n") if windows_endings else updated).encode("utf-8")
            after = path.stat()
            if (after.st_mtime_ns, after.st_size) == (before.st_mtime_ns, before.st_size):
                _atomic_write(path, data)
                return
        raise JournalError(f"Нотатка {path.name} весь час змінюється.", "Спробуй ще раз за кілька секунд.")

    def add_summary(self, day_text: str, summary: str) -> dict[str, Any]:
        day = parse_date(day_text)
        path = self.note_path(day)
        if not path.is_file():
            raise JournalError(f"Немає нотатки за {day.isoformat()}.")
        new_lines = [line.rstrip() for line in summary.strip().split("\n") if line.strip()]
        if not new_lines:
            raise JournalError("Порожній підсумок.")
        self._update(path, lambda text: append_lines(text, SUMMARY, new_lines))
        return {"path": str(path), "lines_added": len(new_lines)}

    def mark_anki_done(self, days: Iterable[str]) -> dict[str, Any]:
        marked: list[str] = []
        missing: list[str] = []
        for value in days:
            day = parse_date(value)
            path = self.note_path(day)
            if not path.is_file():
                missing.append(day.isoformat())
                continue
            self._update(path, lambda text: set_property(text, "anki_done", "true"))
            marked.append(day.isoformat())
        return {"marked": marked, "missing": missing}

    def study_page(self) -> Path:
        return self.vault / STUDY_PAGE

    def _study_text(self) -> str:
        path = self.study_page()
        return self._read(path) if path.is_file() else ""

    def word_queue(self) -> dict[str, Any]:
        """Words written down for Anki and not in it yet, oldest first, and the table being studied now."""
        page = self._study_text()
        done = words_in_anki(page)
        queue: dict[tuple[str, str], dict[str, Any]] = {}
        for day in self._note_days():
            for line in sections(self._read(self.note_path(day))).get(WORDS, []):
                word, context = vocabulary_entry(line)
                key = (day.isoformat(), word.lower())
                if not word or key in done:
                    continue
                entry = queue.setdefault(key, {"date": day.isoformat(), "word": word, "contexts": []})
                if context and context not in entry["contexts"]:
                    entry["contexts"].append(context)
        return {
            "words": list(queue.values()),
            "study_table": "\n".join(sections(page).get(STUDYING, [])),
            "study_page": str(self.study_page()),
        }

    def _change_study_page(self, change: Callable[[str], str]) -> Path:
        path = self.study_page()
        if not path.is_file():
            _atomic_write(path, STUDY_PAGE_TEXT.encode("utf-8"))
        self._update(path, change)
        return path

    def save_study_table(self, table: str) -> dict[str, Any]:
        if not table.strip():
            raise JournalError("Порожня таблиця.")
        path = self._change_study_page(lambda text: replace_section(text, STUDYING, table))
        return {"path": str(path)}

    def mark_words_in_anki(self, words: Iterable[tuple[str, str]], clear_study_table: bool = True) -> dict[str, Any]:
        """List words as already in Anki, so they leave the queue; by default the studied table goes too."""
        done = words_in_anki(self._study_text())
        new_lines: list[str] = []
        for day_text, raw_word in words:
            day = parse_date(day_text).isoformat()
            word = " ".join(raw_word.split())
            if not word:
                raise JournalError("Порожнє слово.")
            if (day, word.lower()) not in done:
                done.add((day, word.lower()))
                new_lines.append(f"- {day} · {word}")

        def change(text: str) -> str:
            if new_lines:
                text = append_lines(text, IN_ANKI, new_lines)
            return replace_section(text, STUDYING, "") if clear_study_table else text

        path = self._change_study_page(change)
        return {"path": str(path), "marked": len(new_lines), "left_in_queue": len(self.word_queue()["words"])}

    def save_weekly_review(self, review_sections: dict[str, str], last_notes: int = 7) -> dict[str, Any]:
        report = self.read(last_notes=last_notes)
        if not report["days"]:
            raise JournalError("Немає щоденних нотаток, огляд робити ні з чого.")
        week = report["week"]
        path = self.weekly_path(week)
        template = self.vault / WEEKLY_TEMPLATE
        text = self._read(template) if template.is_file() else "---\n---\n"
        text = set_property(text, "week", week)
        for key in WEEKLY_PROPERTIES:
            value = report["totals"][key]
            text = set_property(text, key, "" if value is None else f"{value:g}")
        for heading, body in review_sections.items():
            text = replace_section(text, heading, body)
        path.parent.mkdir(parents=True, exist_ok=True)
        try:
            # Exclusive: an existing review may already have the user's own notes in it.
            with path.open("xb") as file:
                file.write(text.encode("utf-8"))
        except FileExistsError:
            raise JournalError(f"Огляд {week} уже є: {path}.", "Він не перезаписується: спершу видали чи перейменуй його.") from None
        return {"path": str(path), "week": week, "totals": report["totals"]}
