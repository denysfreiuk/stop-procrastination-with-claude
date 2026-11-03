"""Daily notes on disk: creating them from the template and changing them safely."""

from __future__ import annotations

import logging
import re
import subprocess
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path

from .files import atomic_write
from .markdown import append_line, insert_by_time, properties, remove_line, render_value, section_lines, set_property

DAILY_FOLDER = Path("Journal") / "Daily"
TEMPLATE = Path("Templates") / "Daily.md"
STUDY_PAGE = Path("Слова на вивчення.md")
HABITS_PAGE = Path("Звички.md")

FOCUS = "Фокус"
LEARNED = "Що вивчив"
WORDS = "Нові слова"
PHONE = "Телефон / тікток"
GYM = "Зал"
FOOD = "Їжа"
NOTE = "Нотатка дня"
SUMMARY = "Підсумок"
LOG = "Лог"

WRITE_TRIES = 5
COMMIT_TRIES = 3
GIT_IDENTITY = ("-c", "user.name=discipline-bot", "-c", "user.email=bot@localhost")
logger = logging.getLogger("discipline_bot")
_QUOTED_VARIABLE = re.compile(r'"(\{\{[^{}]*\}\})"')
_VARIABLE = re.compile(r"\{\{\s*(date|time|title)\s*(?::([^{}]*))?\}\}")
_MOMENT_TOKEN = re.compile("YYYY|MM|DD|HH|mm|ss")
_MOMENT = {"YYYY": "%Y", "MM": "%m", "DD": "%d", "HH": "%H", "mm": "%M", "ss": "%S"}
_NOTE_NAME = re.compile(r"^\d{4}-\d{2}-\d{2}$")


class JournalBusy(Exception):
    """The note kept changing under us; nothing was written."""


@dataclass(frozen=True)
class Edit:
    day: date
    lines: tuple[tuple[str, str], ...] = ()  # (section, line)
    set_values: Mapping[str, object] = field(default_factory=dict)
    add_values: Mapping[str, int] = field(default_factory=dict)
    by_time: bool = False  # put `- HH:MM` lines in time order instead of at the end


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
    def __init__(self, vault: Path, commit: bool = False) -> None:
        self.vault = vault
        self.commit_changes = commit

    def _git(self, *args: str) -> subprocess.CompletedProcess[str]:
        command = ["git", "-C", str(self.vault), *args]
        return subprocess.run(command, capture_output=True, text=True, encoding="utf-8", errors="replace")

    def _commit(self, message: str) -> None:
        """On a server the vault is the git repository other devices sync with.

        Each change is committed at once, so the working tree stays clean and pushes
        from the other devices (receive.denyCurrentBranch=updateInstead) go through.
        A failed commit never fails the write: the next commit picks the change up.
        """
        if not self.commit_changes:
            return
        try:
            for _ in range(COMMIT_TRIES):
                result = self._git("add", "--all")
                if result.returncode == 0:
                    if self._git("diff", "--cached", "--quiet").returncode == 0:
                        return
                    result = self._git(*GIT_IDENTITY, "commit", "--quiet", "--message", message or "Запис бота")
                    if result.returncode == 0:
                        return
                time.sleep(0.2)  # Most often a push from another device holds the index for a moment.
        except OSError as error:
            logger.warning("Could not run git in the vault: %s", error)
            return
        logger.warning("Could not commit the vault: %s", result.stderr.strip())

    def note_path(self, day: date) -> Path:
        return self.vault / DAILY_FOLDER / f"{day.isoformat()}.md"

    def read(self, day: date) -> str | None:
        return self._read(self.note_path(day))

    @staticmethod
    def _read(path: Path) -> str | None:
        try:
            return path.read_bytes().decode("utf-8").replace("\r\n", "\n")
        except FileNotFoundError:
            return None

    def days(self) -> list[date]:
        """Days that have a note, oldest first."""
        folder = self.vault / DAILY_FOLDER
        names = (path.stem for path in folder.glob("*.md")) if folder.is_dir() else ()
        return sorted(date.fromisoformat(name) for name in names if _NOTE_NAME.match(name))

    def read_page(self, page: Path) -> str:
        """A page of the vault outside the journal, such as STUDY_PAGE; empty when there is none."""
        return self._read(self.vault / page) or ""

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

    def _update(self, day: date, change: Callable[[str], str], message: str = "") -> None:
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
                self._commit(message)
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
                text = (insert_by_time if edit.by_time else append_line)(text, section, line)
            return text

        self._update(edit.day, change, f"Бот: {label}" if label else "")
        return Undo(edit.day.isoformat(), edit.lines, previous, label)

    def revert(self, undo: Undo) -> None:
        def change(text: str) -> str:
            for section, line in undo.lines:
                text = remove_line(text, section, line)
            for key, value in undo.previous.items():
                text = set_property(text, key, value or "")
            return text

        self._update(date.fromisoformat(undo.day), change, f"Бот: скасовано {undo.label}".rstrip())

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
        self.apply(Edit(edit.day, missing, wrong, add_values, edit.by_time), "відновлено втрачений запис")
        return True
