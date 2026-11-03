from __future__ import annotations

from datetime import date, timedelta

from discipline_bot import stats

from .conftest import DAY


def note(focus: int = 0, relapse: bool = False, gym: bool = False, learned: str = "") -> str:
    return (
        f"---\nfocus_minutes: {focus}\ntiktok_relapse: {str(relapse).lower()}\ngym: {str(gym).lower()}\n---\n"
        f"## Що вивчив\n{learned}\n\n## Лог\n"
    )


def reader(notes: dict[int, str]):
    """Notes by how many days ago they were written."""
    by_day = {DAY - timedelta(days=offset): text for offset, text in notes.items()}

    def read(day: date) -> str | None:
        return by_day.get(day)

    return read


def test_empty_today_keeps_the_streak() -> None:
    read = reader({1: note(50), 2: note(learned="- 10:00 щось"), 3: note(25)})
    assert stats.streak(read, DAY, stats.studied) == 3


def test_a_logged_today_counts() -> None:
    assert stats.streak(reader({0: note(10), 1: note(50)}), DAY, stats.studied) == 2


def test_a_day_without_a_note_breaks_the_streak() -> None:
    assert stats.streak(reader({0: note(10), 2: note(50)}), DAY, stats.studied) == 1


def test_a_day_without_learning_breaks_the_streak() -> None:
    read = reader({1: note(50), 2: note(), 3: note(25)})
    assert stats.streak(read, DAY, stats.studied) == 1


def test_no_notes_mean_no_streak() -> None:
    assert stats.streak(reader({}), DAY, stats.studied) == 0
    assert stats.tiktok_streak(reader({}), DAY) == 0


def test_a_relapse_today_zeroes_the_tiktok_streak() -> None:
    assert stats.tiktok_streak(reader({0: note(relapse=True), 1: note(), 2: note()}), DAY) == 0


def test_a_relapse_before_today_ends_the_tiktok_streak() -> None:
    assert stats.tiktok_streak(reader({0: note(), 1: note(), 2: note(relapse=True), 3: note()}), DAY) == 2


def test_gym_days_look_at_seven_days() -> None:
    read = reader({0: note(gym=True), 6: note(gym=True), 7: note(gym=True), 3: note()})
    assert stats.gym_days(read, DAY) == 2


def test_summary_of_an_empty_day_lists_what_is_missing() -> None:
    text = stats.summary(None, DAY)
    assert text.startswith("📊 30 жовтня\nПоки нічого не записано.")
    assert text.endswith("Ще немає: фокус, що вивчив, нові слова, сон, їжа")


def test_summary_shows_filled_values_and_the_rest_as_missing() -> None:
    note_text = (
        "---\nfocus_blocks: 2\nfocus_minutes: 100\nsleep_hours: 7.5\n"
        "gym: true\ngym_minutes: 60\nnew_words: 2\ntiktok_relapse: true\n---\n"
        "## Що вивчив\n- 10:00 x\n\n## Нові слова\n- borrow\n\n## Їжа\n- 13:00 борщ\n"
    )
    text = stats.summary(note_text, DAY)
    for expected in ("100 хв, блоків: 2", "Вивчив: 1", "Нових слів: 2", "зрив", "Сон: 7.5", "Зал: 60"):
        assert expected in text
    assert "Ще немає" not in text


def test_reminder_when_everything_is_filled() -> None:
    note_text = (
        "---\nfocus_minutes: 10\nsleep_hours: 7\n---\n"
        "## Що вивчив\n- x\n\n## Нові слова\n- y\n\n## Їжа\n- z\n"
    )
    assert stats.reminder(note_text, DAY).endswith("Усе заповнено 👍")
    with_words = stats.reminder(note_text, DAY, words_for_anki=3)
    assert with_words.endswith("📥 На Anki чекає слів: 3. У Claude Code: /anki-from-notes")


def test_goals_come_from_the_habits_page_or_default() -> None:
    page = "```dataviewjs\nconst GOALS = { focusMinutes: 90, sleepHours: 7.5 };\n```"
    assert stats.habit_goals(page) == stats.Goals(90, 7.5)
    assert stats.habit_goals("") == stats.Goals(50, 7)


def test_dashboard_ticks_the_habits_of_the_tracker_page() -> None:
    today = (
        "---\nfocus_blocks: 1\nfocus_minutes: 50\nsleep_hours: 6.5\ngym: true\ngym_minutes: 60\n"
        "new_words: 2\ntiktok_relapse: false\n---\n"
        "## Що вивчив\n- 10:00 PCA\n\n## Нові слова\n- borrow\n- lend\n\n## Підсумок\n\n## Лог\n"
    )
    read = reader({0: today, 1: note(30, learned="- 09:00 x"), 2: note(relapse=True)})
    text = stats.dashboard(read, DAY, stats.Goals(), words_for_anki=5)
    lines = text.split("\n")
    assert lines[0] == "📵✅ 🎯✅ 📚✅ 🔤✅ 🏋️✅ 😴⬜ 📝⬜"
    assert lines[1] == "30 жовтня, пʼятниця · 5 з 7"
    assert "🎯 Фокус: 50 з 50 хв · блоків: 1" in lines
    assert "📚 Вивчив: 1 · 🔤 Слів: 2 · 📥 На Anki: 5" in lines
    assert "😴 Сон: 6.5 год · 🏋️ Зал: 60 хв" in lines
    assert "📵 Тікток: без зривів" in lines
    assert lines[-1] == "🔥 Навчання поспіль: 2 · 📵 Без тіктока: 2"


def test_dashboard_counts_meals_and_shows_the_estimate() -> None:
    today = "---\nkcal: 2100\nprotein_g: 120\n---\n## Їжа\n- 08:30 вівсянка\n- 13:05 борщ\n- 10:00 банан\n"
    lines = stats.dashboard(reader({0: today}), DAY, stats.Goals(), 0).split("\n")
    assert "🍽 Їжа: 3 · остання о 13:05 · ~2100 ккал, білка ~120 г" in lines
    lines = stats.dashboard(reader({0: "## Їжа\n- 08:30 вівсянка\n"}), DAY, stats.Goals(), 0).split("\n")
    assert "🍽 Їжа: 1 · остання о 08:30" in lines


def test_dashboard_of_a_day_without_a_note() -> None:
    text = stats.dashboard(reader({}), DAY, stats.Goals(), words_for_anki=0)
    assert text.startswith("📵✅ 🎯⬜ 📚⬜ 🔤⬜ 🏋️⬜ 😴⬜ 📝⬜\n30 жовтня, пʼятниця · 1 з 7")
    assert "😴 Сон: — · 🏋️ Зал: —\n🍽 Їжа: —" in text


def test_words_for_anki_skip_the_ones_the_study_page_lists() -> None:
    read = reader({
        0: "## Нові слова\n- borrow\n- reluctant — Friends\n- reluctant — I was reluctant\n",
        1: "## Нові слова\n- Borrow\n- lend\n",
    })
    page = "# Слова на вивчення\n\n## Вчу зараз\n| lend | |\n\n## Уже в Anki\n- 2026-10-29 · borrow\n"
    days = [DAY - timedelta(days=1), DAY]
    assert stats.words_for_anki(days, read, page) == 3, "lend, borrow and reluctant of today"
    assert stats.words_for_anki(days, read, "") == 4
