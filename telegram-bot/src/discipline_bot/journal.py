"""Daily notes on disk: creating them from the template and changing them safely."""

from __future__ import annotations

import re
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path

from .files import atomic_write
from .markdown import append_line, properties, remove_line, render_value, section_lines, set_property

DAILY_FOLDER = Path("Journal") / "Daily"
TEMPLATE = Path("Templates") / "Daily.md"

FOCUS = "Фокус"
LEARNED = "Що вивчив"
WORDS = "Нові слова"
PHONE = "Телефон / тікток"
GYM = "Зал"
FOOD = "Їжа"
NOTE = "Нотатка дня"
LOG = "Лог"

WRITE_TRIES = 5
_QUOTED_VARIABLE = re.compile(r'"(\{\{[^{}]*\}\})"')
_VARIABLE = re.compile(r"\{\{\s*(date|time|title)\s*(?::([^{}]*))?\}\}")
_MOMENT_TOKEN = re.compile("YYYY|MM|DD|HH|mm|ss")
_MOMENT = {"YYYY": "%Y", "MM": "%m", "DD": "%d", "HH": "%H", "mm": "%M", "ss": "%S"}


class JournalBusy(Exception):
    """The note kept changing under us; nothing was written."""


@dataclass(frozen=True)
class Edit:
    day: date
    lines: tuple[tuple[str, str], ...] = ()  # (section, line)
    set_values: Mapping[str, object] = field(default_factory=dict)
    add_values: Mapping[str, int] = field(default_factory=dict)


@dataclass(frozen=True)
class Undo:
    day: str
    lines: tuple[tuple[str, str], ...]
    previous: Mapping[str, str | None]
    label: str = ""


def render_template(template: str, day: date, now: datetime) -> str:
    """Fill in the variables of Obsidian's Templates plugin, which the bot shares with it."""
    moment = datetime.combine(day, now.time())

    def variable(match: re.Match[str]) -> str:
        if match[1] == "title":
            return day.isoformat()
        tokens = (match[2] or ("YYYY-MM-DD" if match[1] == "date" else "HH:mm")).strip()
        return moment.strftime(_MOMENT_TOKEN.sub(lambda token: _MOMENT[token[0]], tokens))

    # Quotes only protect the variable from Obsidian's Properties editor in the template itself.
    return _VARIABLE.sub(variable, _QUOTED_VARIABLE.sub(r"\1", template))


def to_number(value: str | None) -> float:
    try:
        return float(value or 0)
    except ValueError:
        return 0


class Journal:
    def __init__(self, vault: Path) -> None:
        self.vault = vault

    def note_path(self, day: date) -> Path:
        return self.vault / DAILY_FOLDER / f"{day.isoformat()}.md"

    def read(self, day: date) -> str | None:
        try:
            return self.note_path(day).read_bytes().decode("utf-8").replace("\r\n", "\n")
        except FileNotFoundError:
            return None

    def _create(self, day: date, now: datetime) -> None:
        path = self.note_path(day)
        template = self.vault / TEMPLATE
        if template.is_file():
            text = render_template(template.read_text(encoding="utf-8"), day, now)
        else:
            text = f"---\ndate: {day.isoformat()}\n---\n"
        path.parent.mkdir(parents=True, exist_ok=True)
        try:
            # Exclusive: if Obsidian has just made the note, its copy stays.
            with path.open("xb") as file:
                file.write(text.encode("utf-8"))
        except FileExistsError:
            pass

    def _update(self, day: date, change: Callable[[str], str]) -> None:
        """Change a note, starting over if someone else wrote it between reading and writing."""
        path = self.note_path(day)
        if not path.exists():
            self._create(day, datetime.now())
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
                atomic_write(path, data)
                return
        raise JournalBusy(str(path))

    def apply(self, edit: Edit, label: str = "") -> Undo:
        previous: dict[str, str | None] = {}

        def change(text: str) -> str:
            values = properties(text)
            previous.clear()
            for key in (*edit.set_values, *edit.add_values):
                previous[key] = values.get(key)
            for key, value in edit.set_values.items():
                text = set_property(text, key, render_value(value))
            for key, amount in edit.add_values.items():
                total = to_number(values.get(key)) + amount
                text = set_property(text, key, render_value(total))
            for section, line in edit.lines:
                text = append_line(text, section, line)
            return text

        self._update(edit.day, change)
        return Undo(edit.day.isoformat(), edit.lines, previous, label)

    def revert(self, undo: Undo) -> None:
        def change(text: str) -> str:
            for section, line in undo.lines:
                text = remove_line(text, section, line)
            for key, value in undo.previous.items():
                text = set_property(text, key, value or "")
            return text

        self._update(date.fromisoformat(undo.day), change)

    def restore_if_lost(self, edit: Edit) -> bool:
        """Put an edit back if Obsidian saved its own older copy over it while the user typed."""
        text = self.read(edit.day)
        if text is None:
            return False
        missing = tuple(item for item in edit.lines if item[1] not in section_lines(text, item[0]))
        values = properties(text)
        wrong = {key: value for key, value in edit.set_values.items() if values.get(key) != render_value(value)}
        if not missing and not wrong:
            return False
        whole_edit_lost = bool(edit.lines) and len(missing) == len(edit.lines)
        add_values = edit.add_values if whole_edit_lost else {}
        self.apply(Edit(edit.day, missing, wrong, add_values))
        return True
