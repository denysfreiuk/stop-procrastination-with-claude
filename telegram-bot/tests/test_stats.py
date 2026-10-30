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
    assert "Ще немає: фокус, що вивчив, нові слова, екран, сон, їжа, енергія" in text


def test_summary_shows_filled_values_and_the_rest_as_missing() -> None:
    note_text = (
        "---\nfocus_blocks: 2\nfocus_minutes: 100\nscreen_time_min: 95\nsleep_hours: 7.5\n"
        "gym: true\ngym_minutes: 60\nnew_words: 2\nenergy: 4\ntiktok_relapse: true\n---\n"
        "## Що вивчив\n- 10:00 x\n\n## Нові слова\n- borrow\n\n## Їжа\n- 13:00 борщ\n"
    )
    text = stats.summary(note_text, DAY)
    for expected in ("100 хв, блоків: 2", "Вивчив: 1", "Нових слів: 2", "Екран: 95", "зрив", "Сон: 7.5", "Зал: 60", "Енергія: 4"):
        assert expected in text
    assert "Ще немає" not in text


def test_reminder_when_everything_is_filled() -> None:
    note_text = (
        "---\nfocus_minutes: 10\nscreen_time_min: 0\nsleep_hours: 7\nenergy: 3\n---\n"
        "## Що вивчив\n- x\n\n## Нові слова\n- y\n\n## Їжа\n- z\n"
    )
    assert stats.reminder(note_text, DAY).endswith("Усе заповнено 👍")
