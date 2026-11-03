from __future__ import annotations

import shutil
from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest
from mcp.client.client import Client

from anki_claude import journal as journal_module
from anki_claude.errors import JournalError
from anki_claude.journal import Journal, append_lines, properties, replace_section, sections, typed, week_label
from anki_claude.server import build_server

from .fake_ankiconnect import FakeAnkiConnect

REPOSITORY = Path(__file__).resolve().parents[5]
TODAY = date(2026, 10, 30)
NOTE = """---
date: {day}
focus_blocks: {blocks}
focus_minutes: {minutes}
screen_time_min: {screen}
tiktok_relapse: {relapse}
sleep_hours: {sleep}
gym: {gym}
gym_minutes: 0
new_words: {words}
energy: {energy}
anki_done: {anki}
my_key: моє
---
## Фокус
{focus}

## Що вивчив
{learned}

## Нові слова
{vocabulary}

## Підсумок

## Лог
- 09:00 запис користувача
"""


def write_note(vault: Path, day: date, **fields: object) -> Path:
    values: dict[str, object] = {
        "blocks": 0, "minutes": 0, "screen": "", "relapse": "false", "sleep": "", "gym": "false",
        "words": 0, "energy": "", "anki": "false", "focus": "", "learned": "", "vocabulary": "",
    }
    values.update(fields)
    path = vault / "Journal" / "Daily" / f"{day.isoformat()}.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(NOTE.format(day=day.isoformat(), **values), encoding="utf-8")
    return path


@pytest.fixture
def vault(tmp_path: Path) -> Path:
    root = tmp_path / "vault"
    (root / "Templates").mkdir(parents=True)
    shutil.copy(REPOSITORY / "obsidian" / "Templates" / "Weekly.md", root / "Templates" / "Weekly.md")
    return root


@pytest.fixture
def journal(vault: Path, monkeypatch: pytest.MonkeyPatch) -> Journal:
    monkeypatch.setattr(Journal, "today", lambda self: TODAY)
    return Journal(vault, "Europe/Kyiv")


def test_today_uses_the_configured_zone(vault: Path) -> None:
    assert Journal(vault, "Pacific/Auckland").today() == datetime.now(ZoneInfo("Pacific/Auckland")).date()


def test_properties_are_typed_and_sections_keep_only_filled_ones(journal: Journal, vault: Path) -> None:
    write_note(vault, TODAY, minutes=75, sleep=7.5, relapse="true", focus="- 10:00 · 75 хв · ML", energy=4)
    day = journal.read()["days"][0]
    assert day["date"] == "2026-10-30" and day["weekday"] == "пт"
    assert day["properties"]["focus_minutes"] == 75
    assert day["properties"]["sleep_hours"] == 7.5
    assert day["properties"]["tiktok_relapse"] is True
    assert day["properties"]["screen_time_min"] is None
    assert day["properties"]["my_key"] == "моє"
    assert set(day["sections"]) == {"Фокус", "Лог"}


def test_default_is_today_and_a_missing_note_is_reported(journal: Journal, vault: Path) -> None:
    write_note(vault, TODAY - timedelta(days=1))
    report = journal.read()
    assert report["days"] == [] and report["missing_days"] == ["2026-10-30"]
    assert report["today"] == "2026-10-30"


def test_a_period_and_a_single_day(journal: Journal, vault: Path) -> None:
    for offset in (0, 2, 3, 9):
        write_note(vault, TODAY - timedelta(days=offset))
    report = journal.read("2026-10-27", "2026-10-30")
    assert [day["date"] for day in report["days"]] == ["2026-10-27", "2026-10-28", "2026-10-30"]
    assert report["missing_days"] == ["2026-10-29"]
    assert [day["date"] for day in journal.read("2026-10-28", "2026-10-28")["days"]] == ["2026-10-28"]
    assert [day["date"] for day in journal.read(date_from="2026-10-28")["days"]] == ["2026-10-28", "2026-10-30"]


def test_last_notes_skip_gaps_and_ignore_other_files(journal: Journal, vault: Path) -> None:
    for offset in (0, 1, 5, 20):
        write_note(vault, TODAY - timedelta(days=offset))
    (vault / "Journal" / "Daily" / "чернетка.md").write_text("x", encoding="utf-8")
    report = journal.read(last_notes=3)
    assert [day["date"] for day in report["days"]] == ["2026-10-25", "2026-10-29", "2026-10-30"]
    assert report["missing_days"] == ["2026-10-26", "2026-10-27", "2026-10-28"]


def test_totals_follow_the_same_rules_as_the_dashboard(journal: Journal, vault: Path) -> None:
    write_note(vault, TODAY, blocks=2, minutes=100, words=3, sleep=8, screen=90, energy=4, gym="true")
    write_note(vault, TODAY - timedelta(days=1), learned="- 10:00 PCA", sleep=6, relapse="true", words=2)
    write_note(vault, TODAY - timedelta(days=2))
    assert journal.read(last_notes=7)["totals"] == {
        "days_with_notes": 3,
        "focus_minutes": 100,
        "focus_blocks": 2,
        "learning_days": 2,
        "tiktok_free_days": 2,
        "gym_days": 1,
        "new_words": 5,
        "avg_sleep_hours": 7.0,
        "avg_screen_time_min": 90.0,
    }


def test_totals_of_nothing_have_no_averages(journal: Journal) -> None:
    totals = journal.read(last_notes=7)["totals"]
    assert totals["days_with_notes"] == 0 and totals["avg_sleep_hours"] is None


def test_pending_anki_shows_only_unprocessed_material(journal: Journal, vault: Path) -> None:
    write_note(vault, TODAY, learned="- 11:00 SVD", vocabulary="- borrow", focus="- 10:00 · 5 хв · ML")
    write_note(vault, TODAY - timedelta(days=1), learned="- 10:00 PCA", anki="true")
    write_note(vault, TODAY - timedelta(days=2), vocabulary="- lend")
    write_note(vault, TODAY - timedelta(days=30), learned="- 10:00 давнє")
    report = journal.read(only_pending_anki=True)
    assert [day["date"] for day in report["days"]] == ["2026-09-30", "2026-10-30"]
    assert report["days"][1]["sections"] == {"Що вивчив": ["- 11:00 SVD"]}, "words go through the word queue"
    assert report["missing_days"] == []
    limited = journal.read("2026-10-01", "2026-10-30", only_pending_anki=True)
    assert [day["date"] for day in limited["days"]] == ["2026-10-30"]


def test_word_queue_gathers_words_of_all_days_with_their_contexts(journal: Journal, vault: Path) -> None:
    write_note(vault, TODAY, vocabulary="- reluctant — She was reluctant to leave\n- borrow\n- reluctant — Friends")
    write_note(vault, TODAY - timedelta(days=40), vocabulary="- lend", anki="true")
    queue = journal.word_queue()
    assert queue["words"] == [
        {"date": "2026-09-20", "word": "lend", "contexts": []},
        {"date": "2026-10-30", "word": "reluctant", "contexts": ["She was reluctant to leave", "Friends"]},
        {"date": "2026-10-30", "word": "borrow", "contexts": []},
    ]
    assert queue["study_table"] == ""
    assert not (vault / "Слова на вивчення.md").exists()


def test_studied_words_leave_the_queue_and_the_notes_stay_untouched(journal: Journal, vault: Path) -> None:
    path = write_note(vault, TODAY, vocabulary="- reluctant — Friends\n- borrow\n- lend")
    note = path.read_text(encoding="utf-8")
    table = "| Слово | Переклад |\n|---|---|\n| reluctant | неохочий |\n| borrow | позичати |"
    journal.save_study_table(table)
    assert journal.word_queue()["study_table"] == table
    result = journal.mark_words_in_anki([("2026-10-30", "Reluctant"), ("2026-10-30", "borrow")])
    assert result["marked"] == 2 and result["left_in_queue"] == 1
    queue = journal.word_queue()
    assert [item["word"] for item in queue["words"]] == ["lend"]
    assert queue["study_table"] == ""
    assert path.read_text(encoding="utf-8") == note
    page = sections((vault / "Слова на вивчення.md").read_text(encoding="utf-8"))
    assert page["Уже в Anki"] == ["- 2026-10-30 · Reluctant", "- 2026-10-30 · borrow"]
    assert journal.mark_words_in_anki([("2026-10-30", "borrow")])["marked"] == 0


def test_the_same_word_on_a_new_day_waits_for_anki_again(journal: Journal, vault: Path) -> None:
    write_note(vault, TODAY - timedelta(days=1), vocabulary="- borrow")
    journal.mark_words_in_anki([("2026-10-29", "borrow")])
    write_note(vault, TODAY, vocabulary="- borrow — I borrowed a pen")
    assert journal.word_queue()["words"] == [{"date": "2026-10-30", "word": "borrow", "contexts": ["I borrowed a pen"]}]


def test_a_new_table_replaces_the_old_one_and_the_list_stays(journal: Journal, vault: Path) -> None:
    write_note(vault, TODAY, vocabulary="- borrow\n- lend")
    journal.mark_words_in_anki([("2026-10-30", "borrow")], clear_study_table=False)
    journal.save_study_table("| lend | позичати |")
    journal.save_study_table("| lend | давати в борг |")
    page = sections((vault / "Слова на вивчення.md").read_text(encoding="utf-8"))
    assert page == {"Вчу зараз": ["| lend | давати в борг |"], "Уже в Anki": ["- 2026-10-30 · borrow"]}
    with pytest.raises(JournalError, match="Порожня"):
        journal.save_study_table(" ")
    with pytest.raises(JournalError, match="YYYY-MM-DD"):
        journal.mark_words_in_anki([("вчора", "lend")])


def test_bad_date_is_explained(journal: Journal) -> None:
    with pytest.raises(JournalError, match="YYYY-MM-DD"):
        journal.read("вчора")


def test_missing_vault_and_zone_are_explained(tmp_path: Path, vault: Path) -> None:
    with pytest.raises(JournalError, match="VAULT_PATH"):
        Journal(tmp_path / "gone", "Europe/Kyiv")
    with pytest.raises(JournalError, match="TIMEZONE"):
        Journal(vault, "Mars/Base")


def test_summary_is_appended_and_touches_nothing_else(journal: Journal, vault: Path) -> None:
    path = write_note(vault, TODAY, focus="- 10:00 · 5 хв · ML")
    before = path.read_text(encoding="utf-8")
    journal.add_summary("2026-10-30", "Добрий день.\n\n**На завтра:** зранку ML.")
    journal.add_summary("2026-10-30", "Ще думка.")
    after = path.read_text(encoding="utf-8")
    assert after == before.replace(
        "## Підсумок\n", "## Підсумок\nДобрий день.\n**На завтра:** зранку ML.\nЩе думка.\n"
    )


def test_summary_needs_a_note_and_text(journal: Journal, vault: Path) -> None:
    write_note(vault, TODAY)
    with pytest.raises(JournalError, match="Немає нотатки"):
        journal.add_summary("2026-10-01", "текст")
    with pytest.raises(JournalError, match="Порожній"):
        journal.add_summary("2026-10-30", "  \n ")


def test_mark_anki_done_changes_one_line(journal: Journal, vault: Path) -> None:
    path = write_note(vault, TODAY)
    before = path.read_text(encoding="utf-8")
    result = journal.mark_anki_done(["2026-10-30", "2026-10-01"])
    assert result == {"marked": ["2026-10-30"], "missing": ["2026-10-01"]}
    assert path.read_text(encoding="utf-8") == before.replace("anki_done: false", "anki_done: true")


def test_windows_line_endings_survive(journal: Journal, vault: Path) -> None:
    path = write_note(vault, TODAY)
    path.write_bytes(path.read_bytes().replace(b"\n", b"\r\n"))
    journal.mark_anki_done(["2026-10-30"])
    raw = path.read_bytes()
    assert b"anki_done: true\r\n" in raw and raw.count(b"\n") == raw.count(b"\r\n")


def test_a_save_from_obsidian_during_our_write_is_kept(journal: Journal, vault: Path) -> None:
    path = write_note(vault, TODAY)
    calls = []

    def change(text: str) -> str:
        calls.append(1)
        if len(calls) == 1:
            path.write_text(text + "з Obsidian\n", encoding="utf-8")
        return text + "від плагіна\n"

    journal._update(path, change)
    text = path.read_text(encoding="utf-8")
    assert "з Obsidian" in text and "від плагіна" in text


def test_atomic_write_waits_for_a_held_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    path = tmp_path / "note.md"
    real_replace = journal_module.os.replace
    attempts = []

    def flaky(source: Path, target: Path) -> None:
        attempts.append(target)
        if len(attempts) == 1:
            raise PermissionError("in use")
        real_replace(source, target)

    monkeypatch.setattr(journal_module.os, "replace", flaky)
    monkeypatch.setattr(journal_module.time, "sleep", lambda _: None)
    journal_module._atomic_write(path, "ok".encode())
    assert path.read_text(encoding="utf-8") == "ok"
    assert [item.name for item in tmp_path.iterdir()] == ["note.md"]


def test_weekly_review_from_the_real_template(journal: Journal, vault: Path) -> None:
    write_note(vault, TODAY, blocks=2, minutes=100, words=3, sleep=8)
    write_note(vault, TODAY - timedelta(days=1), learned="- 10:00 PCA", relapse="true", sleep=7)
    review = journal.save_weekly_review(
        {
            "Що вийшло": "Два блоки ML.",
            "Головна причина зривів": "Втома ввечері.",
            "Зміни на наступний тиждень": "1. Телефон поза кімнатою.\n2. Лягати до 23:00.",
        }
    )
    assert review["week"] == "2026-W44"
    path = vault / "Journal" / "Weekly" / "2026-W44.md"
    text = path.read_text(encoding="utf-8")
    values = properties(text)
    assert values["week"] == "2026-W44"
    assert values["focus_minutes"] == "100"
    assert values["learning_days"] == "2"
    assert values["tiktok_free_days"] == "1"
    assert values["avg_sleep_hours"] == "7.5"
    assert values["avg_screen_time_min"] == ""
    assert "avg_energy" not in values
    assert "{{" not in text
    filled = sections(text)
    assert filled["Що вийшло"] == ["Два блоки ML."]
    assert filled["Зміни на наступний тиждень"] == ["1. Телефон поза кімнатою.", "2. Лягати до 23:00."]
    assert list(filled) == ["Що вийшло", "Головна причина зривів", "Зміни на наступний тиждень"]


def test_existing_review_is_never_overwritten(journal: Journal, vault: Path) -> None:
    write_note(vault, TODAY)
    journal.save_weekly_review({"Що вийшло": "перше"})
    path = vault / "Journal" / "Weekly" / "2026-W44.md"
    path.write_text(path.read_text(encoding="utf-8") + "мої нотатки\n", encoding="utf-8")
    assert journal.read(last_notes=7)["weekly_review_exists"] is True
    with pytest.raises(JournalError, match="уже є"):
        journal.save_weekly_review({"Що вийшло": "друге"})
    assert "мої нотатки" in path.read_text(encoding="utf-8")


def test_review_needs_notes(journal: Journal) -> None:
    with pytest.raises(JournalError, match="Немає щоденних"):
        journal.save_weekly_review({})


@pytest.mark.parametrize(
    ("day", "label"),
    [(date(2026, 10, 30), "2026-W44"), (date(2027, 1, 1), "2026-W53"), (date(2026, 1, 1), "2026-W01")],
)
def test_week_labels_are_iso(day: date, label: str) -> None:
    assert week_label(day) == label


@pytest.mark.parametrize(
    ("raw", "value"),
    [("", None), ("true", True), ("false", False), ("7.5", 7.5), ("50", 50), ("текст", "текст")],
)
def test_typed(raw: str, value: object) -> None:
    assert typed(raw) == value


def test_helpers_keep_the_blank_line_before_the_next_heading() -> None:
    assert append_lines("## A\n\n## B\n", "A", ["x"]) == "## A\nx\n\n## B\n"
    assert replace_section("## A\nстаре\n\n## B\n", "A", "нове") == "## A\nнове\n\n## B\n"
    assert replace_section("## A\n1. \n", "A", "нове") == "## A\nнове\n"
    assert append_lines("---\na: 1\n---\n", "Нове", ["x"]) == "---\na: 1\n---\n\n## Нове\nx\n"


async def test_tools_explain_a_missing_vault(fake: FakeAnkiConnect, make_anki) -> None:
    anki = make_anki(fake)
    async with Client(build_server(lambda: anki)) as client:
        result = await client.call_tool("read_journal")
    assert result.is_error is True
    assert "VAULT_PATH" in result.content[0].text


async def test_tools_read_and_write_the_vault(fake: FakeAnkiConnect, make_anki, vault: Path) -> None:
    today = datetime.now(ZoneInfo("Europe/Kyiv")).date()
    path = write_note(vault, today, learned="- 10:00 PCA", vocabulary="- borrow")
    anki = make_anki(fake, VAULT_PATH=str(vault))
    async with Client(build_server(lambda: anki)) as client:
        report = await client.call_tool("read_journal", {"only_pending_anki": True})
        await client.call_tool("add_day_summary", {"date": today.isoformat(), "summary": "Добрий день."})
        await client.call_tool("mark_anki_done", {"dates": [today.isoformat()]})
        review = await client.call_tool("save_weekly_review", {"sections": {"Що вийшло": "Усе."}})
        queue = await client.call_tool("read_word_queue")
        await client.call_tool("save_study_table", {"table": "| borrow | позичати |"})
        marked = await client.call_tool("mark_words_in_anki", {"words": [{"date": today.isoformat(), "word": "borrow"}]})
    assert report.structured_content["days"][0]["sections"] == {"Що вивчив": ["- 10:00 PCA"]}
    assert review.is_error is False
    text = path.read_text(encoding="utf-8")
    assert "Добрий день." in text and "anki_done: true" in text
    assert [item["word"] for item in queue.structured_content["words"]] == ["borrow"]
    assert marked.structured_content["marked"] == 1 and marked.structured_content["left_in_queue"] == 0
