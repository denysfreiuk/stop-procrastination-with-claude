from __future__ import annotations

import os
import subprocess
from datetime import date, datetime
from pathlib import Path

import pytest

from discipline_bot import files
from discipline_bot.config import ROOT
from discipline_bot.files import atomic_write
from discipline_bot.journal import (
    FOCUS,
    FOOD,
    GYM,
    LEARNED,
    LOG,
    NOTE,
    PHONE,
    WORDS,
    Edit,
    Journal,
    JournalBusy,
    render_template,
)
from discipline_bot.markdown import properties, section_lines

from .conftest import DAY

FOCUS_EDIT = Edit(DAY, ((FOCUS, "- 14:32 · 50 хв · ML"),), add_values={"focus_blocks": 1, "focus_minutes": 50})


def test_new_note_comes_from_the_real_template(journal: Journal) -> None:
    journal.apply(Edit(DAY, ((LOG, "- 14:32 перша"),)))
    text = journal.read(DAY)
    assert text.startswith("---\ndate: 2026-10-30\nfocus_blocks: 0\n")
    assert section_lines(text, LOG) == ["- 14:32 перша"]
    assert journal.note_path(DAY) == journal.vault / "Journal" / "Daily" / "2026-10-30.md"


def test_note_stays_valid_utf8_with_cyrillic(journal: Journal) -> None:
    journal.apply(Edit(DAY, ((LOG, "- 14:32 їжак і ґанок"),)))
    assert "їжак і ґанок".encode() in journal.note_path(DAY).read_bytes()


def test_template_has_everything_the_bot_writes() -> None:
    template = (ROOT / "obsidian" / "Templates" / "Daily.md").read_text(encoding="utf-8")
    for section in (FOCUS, LEARNED, WORDS, PHONE, GYM, FOOD, NOTE, LOG):
        assert f"## {section}\n" in template
    assert {
        "focus_blocks", "focus_minutes", "screen_time_min", "tiktok_relapse", "sleep_hours",
        "gym", "gym_minutes", "new_words", "anki_done",
    } <= properties(template).keys()
    assert "energy" not in properties(template), "energy was dropped from the system"


def test_render_template_variables() -> None:
    template = 'date: "{{date:YYYY-MM-DD}}"\nd: {{date}}\nt: {{time}}\nc: {{time:HH.mm.ss}}\nn: {{title}}\n'
    rendered = render_template(template, date(2026, 1, 2), datetime(2026, 1, 2, 9, 5, 7))
    assert rendered == "date: 2026-01-02\nd: 2026-01-02\nt: 09:05\nc: 09.05.07\nn: 2026-01-02\n"


def test_a_vault_without_the_template_still_records(journal: Journal) -> None:
    (journal.vault / "Templates" / "Daily.md").unlink()
    journal.apply(FOCUS_EDIT)
    text = journal.read(DAY)
    assert properties(text) == {"date": "2026-10-30", "focus_blocks": "1", "focus_minutes": "50"}
    assert section_lines(text, FOCUS) == ["- 14:32 · 50 хв · ML"]


def test_an_existing_note_is_not_replaced(journal: Journal) -> None:
    path = journal.note_path(DAY)
    path.parent.mkdir(parents=True)
    path.write_text("---\nmy_key: мій\n---\nМій текст\n", encoding="utf-8")
    journal.apply(Edit(DAY, ((LOG, "- 14:32 запис"),)))
    text = journal.read(DAY)
    assert "my_key: мій" in text and "Мій текст" in text
    assert section_lines(text, LOG) == ["- 14:32 запис"]


def test_numbers_add_up_and_values_are_set(journal: Journal) -> None:
    journal.apply(FOCUS_EDIT)
    journal.apply(Edit(DAY, ((FOCUS, "- 15:30 · 25 хв · Uni"),), add_values={"focus_blocks": 1, "focus_minutes": 25}))
    journal.apply(Edit(DAY, set_values={"tiktok_relapse": True, "sleep_hours": 7.5}))
    values = properties(journal.read(DAY))
    assert values["focus_blocks"] == "2"
    assert values["focus_minutes"] == "75"
    assert values["tiktok_relapse"] == "true"
    assert values["sleep_hours"] == "7.5"


def test_a_value_set_by_hand_is_counted(journal: Journal) -> None:
    journal.apply(Edit(DAY, set_values={"focus_minutes": 50}))
    journal.apply(FOCUS_EDIT)
    assert properties(journal.read(DAY))["focus_minutes"] == "100"


def test_undo_returns_the_note_to_its_exact_state(journal: Journal) -> None:
    journal.apply(Edit(DAY, ((LOG, "- 10:00 раніше"),)))
    before = journal.read(DAY)
    undo = journal.apply(FOCUS_EDIT)
    journal.revert(undo)
    assert journal.read(DAY) == before


def test_undo_keeps_what_the_user_added_meanwhile(journal: Journal) -> None:
    undo = journal.apply(FOCUS_EDIT)
    path = journal.note_path(DAY)
    path.write_text(path.read_text(encoding="utf-8") + "мій рядок\n", encoding="utf-8")
    journal.revert(undo)
    text = journal.read(DAY)
    assert "мій рядок" in text
    assert section_lines(text, FOCUS) == []


def test_undo_empties_a_value_that_was_empty(journal: Journal) -> None:
    journal.apply(Edit(DAY, ((LOG, "- 10:00 раніше"),)))
    undo = journal.apply(Edit(DAY, set_values={"screen_time_min": 95}))
    journal.revert(undo)
    assert "screen_time_min:\n" in journal.read(DAY)


def test_windows_line_endings_are_kept(journal: Journal) -> None:
    path = journal.note_path(DAY)
    path.parent.mkdir(parents=True)
    path.write_bytes(b"---\r\nfocus_minutes: 5\r\n---\r\n## \xd0\x9b\xd0\xbe\xd0\xb3\r\n")
    journal.apply(Edit(DAY, ((LOG, "- 10:00 x"),), add_values={"focus_minutes": 5}))
    raw = path.read_bytes()
    assert b"focus_minutes: 10\r\n" in raw
    assert b"- 10:00 x" in raw
    assert raw.count(b"\n") == raw.count(b"\r\n")


def test_a_write_from_obsidian_during_our_edit_is_not_lost(journal: Journal) -> None:
    journal.apply(Edit(DAY, ((LOG, "- 10:00 раніше"),)))
    path = journal.note_path(DAY)
    calls = []

    def change(text: str) -> str:
        calls.append(text)
        if len(calls) == 1:
            # Obsidian saves while we hold the old text; the size changes, so the write must restart.
            path.write_text(text + "текст з Obsidian\n", encoding="utf-8")
        return text + "текст бота\n"

    journal._update(DAY, change)
    text = journal.read(DAY)
    assert len(calls) == 2
    assert "текст з Obsidian" in text and "текст бота" in text


def test_a_note_that_never_settles_fails_loudly(journal: Journal) -> None:
    journal.apply(Edit(DAY, ((LOG, "- 10:00 раніше"),)))
    path = journal.note_path(DAY)

    def change(text: str) -> str:
        path.write_text(path.read_text(encoding="utf-8") + "ще\n", encoding="utf-8")
        return text + "бот\n"

    with pytest.raises(JournalBusy):
        journal._update(DAY, change)
    assert "бот" not in journal.read(DAY)


def test_lost_write_is_restored_once(journal: Journal) -> None:
    journal.apply(Edit(DAY, ((LOG, "- 10:00 раніше"),)))
    path = journal.note_path(DAY)
    old_copy = path.read_bytes()
    journal.apply(FOCUS_EDIT)
    path.write_bytes(old_copy)  # Obsidian saved the copy it had in the editor.

    assert journal.restore_if_lost(FOCUS_EDIT) is True
    text = journal.read(DAY)
    assert section_lines(text, FOCUS) == ["- 14:32 · 50 хв · ML"]
    assert properties(text)["focus_minutes"] == "50"
    assert journal.restore_if_lost(FOCUS_EDIT) is False
    assert properties(journal.read(DAY))["focus_minutes"] == "50"


def test_lost_property_is_restored(journal: Journal) -> None:
    edit = Edit(DAY, set_values={"sleep_hours": 7.5})
    journal.apply(edit)
    path = journal.note_path(DAY)
    path.write_text(path.read_text(encoding="utf-8").replace("sleep_hours: 7.5", "sleep_hours:"), encoding="utf-8")
    assert journal.restore_if_lost(edit) is True
    assert properties(journal.read(DAY))["sleep_hours"] == "7.5"


def test_only_missing_lines_come_back_and_numbers_stay(journal: Journal) -> None:
    edit = Edit(DAY, ((WORDS, "- borrow"), (WORDS, "- lend")), add_values={"new_words": 2})
    journal.apply(edit)
    path = journal.note_path(DAY)
    path.write_text(path.read_text(encoding="utf-8").replace("- lend\n", ""), encoding="utf-8")
    assert journal.restore_if_lost(edit) is True
    text = journal.read(DAY)
    assert section_lines(text, WORDS) == ["- borrow", "- lend"]
    assert properties(text)["new_words"] == "2"


def test_a_note_deleted_by_the_user_is_not_brought_back(journal: Journal) -> None:
    journal.apply(FOCUS_EDIT)
    journal.note_path(DAY).unlink()
    assert journal.restore_if_lost(FOCUS_EDIT) is False
    assert journal.read(DAY) is None


def git(folder: Path, *args: str) -> str:
    command = ["git", "-C", str(folder), "-c", "user.name=t", "-c", "user.email=t@t", *args]
    return subprocess.run(command, check=True, capture_output=True, text=True, encoding="utf-8").stdout


@pytest.fixture
def server_vault(vault: Path) -> Path:
    """The vault on a server: a repository that phones and laptops push to."""
    git(vault, "init", "-q", "-b", "main")
    git(vault, "config", "receive.denyCurrentBranch", "updateInstead")
    git(vault, "add", "--all")
    git(vault, "commit", "-q", "-m", "start")
    return vault


def test_each_write_is_committed_on_the_server(server_vault: Path) -> None:
    journal = Journal(server_vault, commit=True)
    undo = journal.apply(FOCUS_EDIT, "фокус 50 хв · ML")
    journal.revert(undo)
    assert git(server_vault, "log", "--format=%s", "-2").split("\n")[:2] == ["Бот: скасовано фокус 50 хв · ML", "Бот: фокус 50 хв · ML"]
    assert git(server_vault, "status", "--porcelain") == ""


def test_without_commits_the_repository_is_left_alone(server_vault: Path) -> None:
    Journal(server_vault).apply(FOCUS_EDIT, "фокус")
    assert git(server_vault, "log", "--format=%s").strip() == "start"


def test_a_phone_and_the_bot_work_on_the_same_vault(server_vault: Path, tmp_path: Path) -> None:
    journal = Journal(server_vault, commit=True)
    phone = tmp_path / "phone"
    git(tmp_path, "clone", "-q", str(server_vault), str(phone))

    journal.apply(FOCUS_EDIT, "фокус")
    git(phone, "pull", "-q", "--no-rebase")
    note = phone / "Journal" / "Daily" / "2026-10-30.md"
    note.write_text(note.read_text(encoding="utf-8").replace("## Нотатка дня\n", "## Нотатка дня\nз телефона\n"), encoding="utf-8")
    git(phone, "commit", "-q", "-am", "з телефона")
    git(phone, "push", "-q")

    assert section_lines(journal.read(DAY), NOTE) == ["з телефона"]
    journal.apply(Edit(DAY, ((LOG, "- 15:00 після телефона"),)), "лог")
    git(phone, "pull", "-q", "--no-rebase")
    text = note.read_text(encoding="utf-8")
    assert "з телефона" in text and "- 15:00 після телефона" in text and "- 14:32 · 50 хв · ML" in text


def test_a_failed_commit_never_loses_the_write(vault: Path, caplog: pytest.LogCaptureFixture) -> None:
    Journal(vault, commit=True).apply(FOCUS_EDIT, "фокус")  # Not a repository at all.
    assert section_lines(Journal(vault).read(DAY), FOCUS) == ["- 14:32 · 50 хв · ML"]
    assert "Could not commit" in caplog.text


def test_atomic_write_leaves_no_temporary_files(tmp_path: Path) -> None:
    path = tmp_path / "note.md"
    atomic_write(path, "текст".encode())
    assert path.read_text(encoding="utf-8") == "текст"
    assert [item.name for item in tmp_path.iterdir()] == ["note.md"]


def test_atomic_write_waits_for_a_file_held_by_another_program(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    path = tmp_path / "note.md"
    real_replace = os.replace
    attempts = []

    def flaky(source: Path, target: Path) -> None:
        attempts.append(target)
        if len(attempts) < 3:
            raise PermissionError("in use")
        real_replace(source, target)

    monkeypatch.setattr(files.os, "replace", flaky)
    monkeypatch.setattr(files.time, "sleep", lambda _: None)
    atomic_write(path, b"ok")
    assert path.read_bytes() == b"ok" and len(attempts) == 3


def test_atomic_write_keeps_the_old_file_when_it_cannot_replace(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    path = tmp_path / "note.md"
    path.write_bytes(b"old")

    def stuck(source: Path, target: Path) -> None:
        raise PermissionError("in use")

    monkeypatch.setattr(files.os, "replace", stuck)
    monkeypatch.setattr(files.time, "sleep", lambda _: None)
    with pytest.raises(PermissionError):
        atomic_write(path, b"new")
    assert path.read_bytes() == b"old"
    assert [item.name for item in tmp_path.iterdir()] == ["note.md"]
