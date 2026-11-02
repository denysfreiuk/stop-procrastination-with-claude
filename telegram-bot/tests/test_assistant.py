from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, time, timedelta
from pathlib import Path

import pytest

from discipline_bot.assistant import BUTTON_ROWS, MAX_UNDO, Assistant
from discipline_bot.commands import CommandError
from discipline_bot.journal import FOCUS, FOOD, GYM, LEARNED, LOG, NOTE, PHONE, WORDS, Edit, Journal
from discipline_bot.markdown import properties, section_lines

from .conftest import DAY, KYIV, NOW


def values(journal: Journal) -> dict[str, str]:
    return properties(journal.read(DAY))


def section(journal: Journal, name: str) -> list[str]:
    return section_lines(journal.read(DAY), name)


def test_plain_text_goes_to_the_log(assistant: Assistant, journal: Journal) -> None:
    reply = assistant.on_text("Прочитав розділ\nі зробив конспект", NOW)
    assert section(journal, LOG) == ["- 14:32 Прочитав розділ / і зробив конспект"]
    assert "14:32" in reply.text


def test_focus_adds_block_minutes_and_a_line(assistant: Assistant, journal: Journal) -> None:
    assistant.focus("50 ML", NOW)
    reply = assistant.focus("ML 25", NOW + timedelta(hours=1))
    assert section(journal, FOCUS) == ["- 14:32 · 50 хв · ML", "- 15:32 · 25 хв · ML"]
    assert values(journal)["focus_blocks"] == "2"
    assert values(journal)["focus_minutes"] == "75"
    assert "75 хв" in reply.text


def test_focus_without_a_topic_repeats_the_last_one(assistant: Assistant, journal: Journal) -> None:
    assistant.focus("50 ML", NOW)
    assistant.focus("25", NOW)
    assert section(journal, FOCUS)[-1].endswith("· ML")


def test_first_focus_without_a_topic_asks_for_it(assistant: Assistant, journal: Journal) -> None:
    assert assistant.focus("50", NOW).text == "Яка тема?"
    assistant.on_text("Uni", NOW)
    assert section(journal, FOCUS) == ["- 14:32 · 50 хв · Uni"]
    assert section(journal, LOG) == []


def test_focus_button_takes_two_taps(assistant: Assistant, journal: Journal) -> None:
    assistant.focus("50 ML", NOW)
    assistant.focus("25 Uni", NOW)
    first = assistant.on_text("🎯 Фокус", NOW)
    assert [label for label, _ in first.buttons[0]] == ["25", "50", "90"]
    second = assistant.on_button("focus:90", NOW)
    assert [row[0][0] for row in second.buttons] == ["Uni", "ML"]
    assistant.on_button(second.buttons[1][0][1], NOW)
    assert section(journal, FOCUS)[-1] == "- 14:32 · 90 хв · ML"
    assert values(journal)["focus_minutes"] == "165"


def test_learned_resets_anki_done_and_words_leave_it(assistant: Assistant, journal: Journal) -> None:
    assistant.learned("перше", NOW)
    journal.apply(Edit(DAY, set_values={"anki_done": True}))
    assistant.words("borrow", NOW)
    assert values(journal)["anki_done"] == "true", "words go to Anki through the study table"
    assistant.learned("друге", NOW)
    assert values(journal)["anki_done"] == "false"
    assert section(journal, LEARNED) == ["- 14:32 перше", "- 14:32 друге"]


def test_words_tell_how_many_wait_for_anki(assistant: Assistant, journal: Journal, vault: Path) -> None:
    journal.apply(Edit(DAY - timedelta(days=1), ((WORDS, "- lend"), (WORDS, "- borrow"))))
    (vault / "Слова на вивчення.md").write_text(
        "# Слова на вивчення\n\n## Вчу зараз\n\n## Уже в Anki\n- 2026-10-29 · lend\n", encoding="utf-8"
    )
    reply = assistant.words("reluctant: She was reluctant, thorough", NOW)
    assert reply.text == "📥 +1 з контекстом у черзі на Anki (усього: 2)"
    reply = assistant.words("give up, put off", NOW)
    assert reply.text == "📥 +2 у черзі на Anki (усього: 4)"
    assert "у черзі на Anki: 4" in assistant.words("reluctant: I was reluctant to ask", NOW).text


def test_the_dashboard_follows_the_entries(assistant: Assistant, journal: Journal) -> None:
    first = assistant.dashboard_due(NOW)
    assert first.edit is None and first.replaces is None, "no message yet: send one"
    assistant.dashboard_shown(5, first.text)
    assert assistant.dashboard_due(NOW + timedelta(seconds=5)) is None, "nothing new"

    assistant.on_command(assistant.focus, "50 ML", NOW)
    update = assistant.dashboard_due(NOW + timedelta(seconds=10))
    assert update.edit == 5 and "🎯✅" in update.text
    assistant.dashboard_shown(5, update.text)

    journal.apply(Edit(DAY, set_values={"gym": True}))  # from Obsidian on the phone
    assert assistant.dashboard_due(NOW + timedelta(seconds=20)) is None, "other devices are checked once a minute"
    later = assistant.dashboard_due(NOW + timedelta(minutes=1, seconds=10))
    assert later.edit == 5 and "🏋️✅" in later.text


def test_dash_renews_the_dashboard(assistant: Assistant) -> None:
    assistant.dashboard_shown(5, "старий")
    update = assistant.dashboard_due(NOW, renew=True)
    assert (update.edit, update.replaces) == (None, 5)


def test_the_dashboard_survives_a_restart(make_assistant: Callable[[], Assistant]) -> None:
    make_assistant().dashboard_shown(5, "текст")
    assert make_assistant().state.dashboard_message == 5


def test_the_reminder_mentions_words_waiting_for_anki(assistant: Assistant) -> None:
    assistant.words("borrow, lend", NOW)
    reply = assistant.reminder_due(NOW.replace(hour=20, minute=5))
    assert "📥 На Anki чекає слів: 2" in reply.text


def test_words_are_counted_and_not_repeated(assistant: Assistant, journal: Journal) -> None:
    assistant.words("borrow, lend", NOW)
    assistant.words("Borrow, give up", NOW)
    assert section(journal, WORDS) == ["- borrow", "- lend", "- give up"]
    assert values(journal)["new_words"] == "3"
    assert "вже записані" in assistant.words("lend", NOW).text


def test_words_keep_the_context_they_were_met_in(assistant: Assistant, journal: Journal) -> None:
    reply = assistant.words("reluctant: She was reluctant to leave (Friends)\nthorough", NOW)
    assert section(journal, WORDS) == ["- reluctant — She was reluctant to leave (Friends)", "- thorough"]
    assert values(journal)["new_words"] == "2"
    assert "з контекстом" in reply.text


def test_a_second_context_is_one_more_example_not_one_more_word(assistant: Assistant, journal: Journal) -> None:
    assistant.words("reluctant", NOW)
    reply = assistant.words("reluctant: I was reluctant to ask", NOW)
    assert section(journal, WORDS) == ["- reluctant", "- reluctant — I was reluctant to ask"]
    assert values(journal)["new_words"] == "1"
    assert "ще один контекст" in reply.text
    assert "вже записані" in assistant.words("Reluctant: I was reluctant to ask", NOW).text


def test_words_written_by_hand_count_as_known(assistant: Assistant, journal: Journal) -> None:
    journal.apply(Edit(DAY, ((WORDS, "- borrow — від руки"),)))
    assistant.words("borrow: інше речення", NOW)
    assert values(journal)["new_words"] == "0"


def test_undo_removes_words_with_context(assistant: Assistant, journal: Journal) -> None:
    assistant.words("reluctant: She was reluctant\nlend", NOW)
    assistant.undo("", NOW)
    assert section(journal, WORDS) == []
    assert values(journal)["new_words"] == "0"


def test_words_without_words_explain_the_format(assistant: Assistant) -> None:
    with pytest.raises(CommandError, match="reluctant"):
        assistant.words(": лише контекст", NOW)
    assert "двокрапки" in assistant.on_text("🔤 Слова", NOW).text


def test_screen_and_sleep_overwrite(assistant: Assistant, journal: Journal) -> None:
    assistant.screen("95", NOW)
    assistant.screen("1:40", NOW)
    assistant.sleep("7,5", NOW)
    assistant.sleep("8", NOW)
    assert values(journal)["screen_time_min"] == "100"
    assert values(journal)["sleep_hours"] == "8"


def test_tiktok_asks_why_and_records_the_answer(assistant: Assistant, journal: Journal) -> None:
    reply = assistant.tiktok("", NOW)
    assert "Чому" in reply.text
    assert values(journal)["tiktok_relapse"] == "true"
    assistant.on_text("нудно після пар", NOW)
    assert section(journal, PHONE) == ["- 14:32 зрив: нудно після пар"]
    assert section(journal, LOG) == []


def test_tiktok_with_a_reason_right_away(assistant: Assistant, journal: Journal) -> None:
    assistant.tiktok("втома", NOW)
    assert section(journal, PHONE) == ["- 14:32 зрив: втома"]
    assert assistant.pending is None


def test_gym_adds_minutes_and_a_line(assistant: Assistant, journal: Journal) -> None:
    assistant.gym("60 ноги", NOW)
    assistant.gym("30", NOW)
    assert values(journal)["gym"] == "true"
    assert values(journal)["gym_minutes"] == "90"
    assert section(journal, GYM) == ["- 14:32 · 60 хв · ноги", "- 14:32 · 30 хв"]


def test_a_workout_set_by_set(assistant: Assistant, journal: Journal) -> None:
    reply = assistant.on_text("🏋️ Зал", NOW)
    assert reply.buttons[0][0] == ("▶️ Почати тренування", "workout:start")
    assert "почалось о 14:32" in assistant.on_button("workout:start", NOW).text
    assert "Жим лежачи" in assistant.on_text("Жим лежачи", NOW).text
    reply = assistant.on_text("60 10", NOW + timedelta(minutes=3))
    assert reply.text.startswith("✅ Жим лежачи, підхід 1: 60×10")
    assert [label for row in reply.buttons for label, _ in row] == ["➕ Підхід", "🔄 Вправа", "⏸ Пауза", "🏁 Завершити"]
    assistant.on_text("62.5 8", NOW + timedelta(minutes=6))
    assert "Підхід 3" in assistant.on_button("workout:set", NOW).text
    assistant.on_button("workout:exercise", NOW)
    assistant.on_text("Підтягування", NOW)
    assistant.on_text("8", NOW + timedelta(minutes=10))
    assert journal.read(DAY) is None, "the sets reach the note when the workout ends"

    reply = assistant.on_button("workout:finish", NOW + timedelta(minutes=40))
    assert section(journal, GYM) == [
        "- 14:32 · 40 хв · Жим лежачи, Підтягування",
        "  - Жим лежачи: 60×10, 62.5×8",
        "  - Підтягування: 8",
    ]
    assert values(journal)["gym"] == "true" and values(journal)["gym_minutes"] == "40"
    assert "тоннаж: 1100 кг" in reply.text
    assert assistant.state.workout is None
    assert section(journal, LOG) == []


def test_a_paused_workout_lets_text_go_to_the_log(assistant: Assistant, journal: Journal) -> None:
    assistant.on_button("workout:start", NOW)
    assistant.on_text("Присідання", NOW)
    assistant.on_command(assistant.words, "borrow", NOW)
    assert assistant.state.workout.exercise == "Присідання", "commands work without a pause"
    assistant.on_button("workout:pause", NOW)
    assistant.on_text("болить плече", NOW)
    assert section(journal, LOG) == ["- 14:32 болить плече"]
    assert "Присідання, підходів: 0" in assistant.gym("", NOW).text
    assistant.on_text("80 8", NOW)
    assert [lift.reps for lift in assistant.state.workout.sets] == [8]


def test_undo_in_a_workout_takes_back_the_last_step(assistant: Assistant, journal: Journal) -> None:
    assistant.on_button("workout:start", NOW)
    assistant.on_text("Жим", NOW)
    assistant.on_text("60 10", NOW)
    assistant.on_command(assistant.words, "borrow", NOW)
    assistant.on_text("60 8", NOW)
    assert assistant.undo("", NOW).text == "↩️ Скасовано: підхід: Жим 60×8"
    assert assistant.undo("", NOW).text == "↩️ Скасовано: слова: borrow"
    assert section(journal, WORDS) == []
    assistant.on_button("workout:finish", NOW)
    assert "Жим: 60×10" in section(journal, GYM)[1]
    assert assistant.undo("", NOW).text == "↩️ Скасовано: тренування 1 хв"
    assert section(journal, GYM) == []


def test_a_set_needs_an_exercise_and_an_empty_workout_writes_nothing(assistant: Assistant, journal: Journal) -> None:
    assistant.on_button("workout:start", NOW)
    with pytest.raises(CommandError, match="назву вправи"):
        assistant.on_text("60 10", NOW)
    assert "нічого не записав" in assistant.on_button("workout:finish", NOW).text
    assert journal.read(DAY) is None


def test_a_forgotten_workout_closes_itself(make_assistant: Callable[[], Assistant], journal: Journal) -> None:
    first = make_assistant()
    first.on_button("workout:start", NOW)
    first.on_text("Жим", NOW)
    first.on_text("60 10", NOW + timedelta(minutes=20))
    restarted = make_assistant()
    assert "підходів: 1" in restarted.dashboard_due(NOW + timedelta(minutes=21)).text
    assert restarted.workout_due(NOW + timedelta(hours=2)) is None
    closed = restarted.workout_due(NOW + timedelta(hours=2, minutes=21))
    assert closed.text.startswith("Закрив тренування сам")
    assert section(journal, GYM)[0] == "- 14:32 · 20 хв · Жим"


def test_food_note_and_energy(assistant: Assistant, journal: Journal) -> None:
    assistant.eat("борщ", NOW)
    assistant.note("Хороший день", NOW)
    assistant.on_button("energy:4", NOW)
    assert section(journal, FOOD) == ["- 14:32 борщ"]
    assert section(journal, NOTE) == ["Хороший день"]
    assert values(journal)["energy"] == "4"


@pytest.mark.parametrize("row", range(len(BUTTON_ROWS)))
def test_every_button_is_handled(assistant: Assistant, row: int) -> None:
    for label in BUTTON_ROWS[row]:
        assert label in assistant.buttons


@pytest.mark.parametrize(
    ("button", "answer", "section_name", "expected"),
    [
        ("📚 Вивчив", "PCA", LEARNED, "- 14:32 PCA"),
        ("🔤 Слова", "borrow, lend", WORDS, "- lend"),
        ("🍽 Їжа", "борщ", FOOD, "- 14:32 борщ"),
        ("📝 Нотатка", "день", NOTE, "день"),
        ("🏋️ Зал", "60 ноги", GYM, "- 14:32 · 60 хв · ноги"),
    ],
)
def test_button_then_answer(assistant: Assistant, journal: Journal, button: str, answer: str, section_name: str, expected: str) -> None:
    assistant.on_text(button, NOW)
    assistant.on_text(answer, NOW)
    assert section(journal, section_name)[-1] == expected
    assert section(journal, LOG) == []


def test_a_wrong_answer_keeps_the_question_open(assistant: Assistant, journal: Journal) -> None:
    assistant.on_text("📱 Екран", NOW)
    with pytest.raises(CommandError):
        assistant.on_text("багато", NOW)
    assistant.on_text("95", NOW)
    assert values(journal)["screen_time_min"] == "95"


def test_an_old_question_expires_and_text_goes_to_the_log(assistant: Assistant, journal: Journal) -> None:
    assistant.on_text("📚 Вивчив", NOW)
    assistant.on_text("це вже просто думка", NOW + timedelta(minutes=16))
    assert section(journal, LEARNED) == []
    assert len(section(journal, LOG)) == 1


def test_a_command_cancels_the_open_question(assistant: Assistant, journal: Journal) -> None:
    assistant.on_text("📚 Вивчив", NOW)
    assistant.on_command(assistant.sleep, "7", NOW)
    assistant.on_text("у лог", NOW)
    assert len(section(journal, LOG)) == 1


def test_a_stale_inline_button_is_harmless(assistant: Assistant) -> None:
    assert "не працює" in assistant.on_button("щось:старе", NOW).text


def test_undo_goes_back_step_by_step(assistant: Assistant, journal: Journal) -> None:
    assistant.focus("50 ML", NOW)
    assistant.sleep("7", NOW)
    assert "сон" in assistant.undo("", NOW).text
    assert values(journal)["sleep_hours"] == ""
    assert "ML" in assistant.undo("", NOW).text
    assert values(journal)["focus_minutes"] == "0"
    assert section(journal, FOCUS) == []
    assert "Нема що" in assistant.undo("", NOW).text


def test_undo_survives_a_restart(make_assistant: Callable[[], Assistant], journal: Journal) -> None:
    make_assistant().words("borrow, lend", NOW)
    make_assistant().undo("", NOW)
    assert section(journal, WORDS) == []
    assert values(journal)["new_words"] == "0"


def test_undo_history_is_limited(assistant: Assistant) -> None:
    for number in range(MAX_UNDO + 5):
        assistant.log(f"запис {number}", NOW)
    assert len(assistant.state.undo) == MAX_UNDO


def test_undo_is_not_taken_for_a_lost_write(assistant: Assistant, journal: Journal) -> None:
    assistant.focus("50 ML", NOW)
    assistant.undo("", NOW)
    assert assistant.confirm_writes(NOW + timedelta(seconds=6)) == []
    assert section(journal, FOCUS) == []


def test_lost_write_is_restored_after_the_delay(assistant: Assistant, journal: Journal) -> None:
    assistant.log("перший", NOW)
    path = journal.note_path(DAY)
    old_copy = path.read_bytes()
    assistant.focus("50 ML", NOW)
    path.write_bytes(old_copy)

    assert assistant.confirm_writes(NOW + timedelta(seconds=1)) == []
    assert section(journal, FOCUS) == []
    assert len(assistant.confirm_writes(NOW + timedelta(seconds=6))) == 1
    assert section(journal, FOCUS) == ["- 14:32 · 50 хв · ML"]
    assert values(journal)["focus_minutes"] == "50"
    assert assistant.confirm_writes(NOW + timedelta(seconds=12)) == []


def test_a_newer_value_is_not_taken_for_a_lost_one(assistant: Assistant, journal: Journal) -> None:
    assistant.screen("95", NOW)
    assistant.screen("120", NOW + timedelta(seconds=2))
    assert assistant.confirm_writes(NOW + timedelta(seconds=30)) == []
    assert values(journal)["screen_time_min"] == "120"


def test_today_and_streak_reports(assistant: Assistant) -> None:
    assert "Поки нічого" in assistant.today("", NOW).text
    assistant.focus("50 ML", NOW)
    assert "50 хв" in assistant.today("", NOW).text
    assert "Навчання поспіль: 1" in assistant.streak("", NOW).text


def test_remind_changes_the_time_and_the_env_file(assistant: Assistant, env_file: Path) -> None:
    assert "20:00" in assistant.remind("", NOW).text
    assert "21:30" in assistant.remind("21:30", NOW).text
    assert assistant.reminder_time == time(21, 30)
    assert "REMINDER_TIME=21:30" in env_file.read_text(encoding="utf-8")


def test_reminder_comes_once_a_day_and_after_sleep_mode(assistant: Assistant) -> None:
    evening = datetime(2026, 10, 30, 20, 0, tzinfo=KYIV)
    assert assistant.reminder_due(evening - timedelta(minutes=1)) is None
    reply = assistant.reminder_due(evening + timedelta(hours=2))  # The laptop woke up at 22:00.
    assert reply is not None and "Ще немає" in reply.text
    assistant.mark_reminder_sent(evening)
    assert assistant.reminder_due(evening + timedelta(hours=3)) is None
    assert assistant.reminder_due(evening + timedelta(days=1)) is not None


def test_a_later_reminder_time_can_fire_again_today(assistant: Assistant) -> None:
    evening = datetime(2026, 10, 30, 20, 5, tzinfo=KYIV)
    assistant.mark_reminder_sent(evening)
    assistant.remind("21:30", evening)
    assert assistant.reminder_due(evening) is None
    assert assistant.reminder_due(evening + timedelta(hours=2)) is not None


def test_a_broken_state_file_does_not_stop_the_bot(make_assistant: Callable[[], Assistant], tmp_path: Path) -> None:
    path = tmp_path / "data" / "state.json"
    path.parent.mkdir()
    path.write_text("{ не json", encoding="utf-8")
    assert make_assistant().state.topics == []


def test_a_day_changes_at_midnight(assistant: Assistant, journal: Journal) -> None:
    late = datetime(2026, 10, 30, 23, 59, tzinfo=KYIV)
    assistant.log("пізно", late)
    assistant.log("вже завтра", late + timedelta(minutes=2))
    assert journal.note_path(DAY).exists()
    assert journal.note_path(DAY + timedelta(days=1)).exists()
