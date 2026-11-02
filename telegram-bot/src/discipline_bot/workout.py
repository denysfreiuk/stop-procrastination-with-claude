"""The gym mode: a workout set by set, written to the note as one entry when it ends."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from .commands import CommandError

MAX_REPS = 1000
MAX_WEIGHT = 1000
MAX_NAME = 60
# `60 10`, `60x10`, `60 кг x 10`, `62,5*8`, or the reps alone for an exercise without weight: `12`.
_SET = re.compile(r"^(?:(\d+(?:[.,]\d+)?)\s*(?:кг|kg)?\s*(?:[xх×*]\s*|\s+))?(\d+)\s*(?:повт\w*|раз\w*|р)?$")


def parse_set(text: str) -> tuple[float | None, int] | None:
    """Weight and reps, or None when the text is not a set (then it names an exercise)."""
    match = _SET.match(text.strip().lower())
    if not match:
        return None
    weight = float(match[1].replace(",", ".")) if match[1] else None
    reps = int(match[2])
    if not 1 <= reps <= MAX_REPS:
        raise CommandError(f"Повторень має бути від 1 до {MAX_REPS}. Приклад: 60 10")
    if weight is not None and weight > MAX_WEIGHT:
        raise CommandError(f"Вага до {MAX_WEIGHT} кг. Приклад: 60 10")
    return weight, reps


def set_text(weight: float | None, reps: int) -> str:
    return f"{weight:g}×{reps}" if weight is not None else str(reps)


@dataclass(frozen=True)
class Lift:
    exercise: str
    weight: float | None
    reps: int


@dataclass
class Workout:
    started: datetime
    last: datetime  # the last thing done in the workout, for closing a forgotten one
    exercise: str | None = None
    sets: list[Lift] = field(default_factory=list)
    paused: bool = False

    def sets_of(self, exercise: str) -> list[Lift]:
        return [lift for lift in self.sets if lift.exercise == exercise]

    def exercises(self) -> list[str]:
        """Exercises with at least one set, in the order they were first done."""
        return list(dict.fromkeys(lift.exercise for lift in self.sets))

    def tonnage(self) -> float:
        return sum((lift.weight or 0) * lift.reps for lift in self.sets)

    def lines(self, minutes: int) -> list[str]:
        """The entry for `## Зал`: the usual one-line form, then each exercise with its sets."""
        exercises = self.exercises()
        head = f"- {self.started:%H:%M} · {minutes} хв · {', '.join(exercises)}"
        return [head, *(f"  - {name}: {self._sets_text(name)}" for name in exercises)]

    def summary(self, minutes: int) -> str:
        lines = [f"Тренування: {minutes} хв", *(f"• {name}: {self._sets_text(name)}" for name in self.exercises())]
        totals = f"Підходів: {len(self.sets)}"
        if self.tonnage():
            totals += f" · тоннаж: {self.tonnage():g} кг"
        return "\n".join([*lines, totals])

    def _sets_text(self, exercise: str) -> str:
        return ", ".join(set_text(lift.weight, lift.reps) for lift in self.sets_of(exercise))

    def to_dict(self) -> dict[str, Any]:
        return {
            "started": self.started.isoformat(),
            "last": self.last.isoformat(),
            "exercise": self.exercise,
            "sets": [[lift.exercise, lift.weight, lift.reps] for lift in self.sets],
            "paused": self.paused,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Workout:
        return cls(
            started=datetime.fromisoformat(data["started"]),
            last=datetime.fromisoformat(data["last"]),
            exercise=data.get("exercise"),
            sets=[Lift(*item) for item in data.get("sets", [])],
            paused=data.get("paused", False),
        )


def exercise_name(text: str) -> str:
    name = " ".join(text.split())[:MAX_NAME].strip()
    if not name:
        raise CommandError("Напиши назву вправи.")
    return name
