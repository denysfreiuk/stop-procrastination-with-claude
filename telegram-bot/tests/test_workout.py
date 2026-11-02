from __future__ import annotations

from datetime import datetime

import pytest

from discipline_bot.commands import CommandError
from discipline_bot.workout import Lift, Workout, exercise_name, parse_set

from .conftest import KYIV


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("60 10", (60, 10)),
        ("60x10", (60, 10)),
        ("60х10", (60, 10)),
        ("60 X 10", (60, 10)),
        ("62,5*8", (62.5, 8)),
        ("60 кг 10", (60, 10)),
        ("60кг x 10 повт", (60, 10)),
        ("12", (None, 12)),
        ("12 раз", (None, 12)),
    ],
)
def test_a_set_is_weight_and_reps(text: str, expected: tuple[float | None, int]) -> None:
    assert parse_set(text) == expected


@pytest.mark.parametrize("text", ["Жим лежачи", "жим 60", "Присідання зі штангою", "21s"])
def test_anything_else_names_an_exercise(text: str) -> None:
    assert parse_set(text) is None


def test_impossible_sets_explain_themselves() -> None:
    with pytest.raises(CommandError, match="Повторень"):
        parse_set("60 0")
    with pytest.raises(CommandError, match="Вага"):
        parse_set("5000 10")
    with pytest.raises(CommandError, match="назву"):
        exercise_name("   ")


def test_the_entry_groups_sets_by_exercise() -> None:
    started = datetime(2026, 10, 30, 18, 2, tzinfo=KYIV)
    workout = Workout(started, started, sets=[
        Lift("Жим лежачи", 60, 10), Lift("Підтягування", None, 8), Lift("Жим лежачи", 62.5, 8),
    ])
    assert workout.lines(65) == [
        "- 18:02 · 65 хв · Жим лежачи, Підтягування",
        "  - Жим лежачи: 60×10, 62.5×8",
        "  - Підтягування: 8",
    ]
    assert workout.summary(65).endswith("Підходів: 3 · тоннаж: 1100 кг")
    assert Workout.from_dict(workout.to_dict()) == workout
