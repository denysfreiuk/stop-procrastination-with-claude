from __future__ import annotations

from datetime import time

import pytest

from discipline_bot.commands import (
    CommandError,
    one_line,
    parse_clock,
    parse_duration,
    parse_energy,
    parse_hours,
    parse_minutes_and_text,
    parse_vocabulary,
    parse_words,
    read_vocabulary_line,
    vocabulary_line,
)


@pytest.mark.parametrize(
    ("args", "expected"),
    [
        ("50 ML", (50, "ML")),
        ("ML 50", (50, "ML")),
        ("90 лінійна алгебра", (90, "лінійна алгебра")),
        ("25", (25, "")),
        ("лекція 3 50", (3, "лекція 50")),
    ],
)
def test_minutes_and_text(args: str, expected: tuple[int, str]) -> None:
    assert parse_minutes_and_text(args, "") == expected


@pytest.mark.parametrize("args", ["ML", "", "0 ML", "1441 ML"])
def test_bad_minutes(args: str) -> None:
    with pytest.raises(CommandError):
        parse_minutes_and_text(args, "")


def test_words_are_split_trimmed_and_unique() -> None:
    assert parse_words(" borrow, lend;give up\nBorrow,, ") == ["borrow", "lend", "give up"]


@pytest.mark.parametrize(
    ("args", "expected"),
    [
        ("borrow, lend", [("borrow", ""), ("lend", "")]),
        ("reluctant: She was reluctant to leave", [("reluctant", "She was reluctant to leave")]),
        ("give up — I won't give up, ever (Friends)", [("give up", "I won't give up, ever (Friends)")]),
        ("thorough - a thorough check", [("thorough", "a thorough check")]),
        ("borrow, lend: I borrowed, then lent it", [("borrow", "I borrowed, then lent it"), ("lend", "I borrowed, then lent it")]),
        ("reluctant: перше\nthorough: друге\nlend", [("reluctant", "перше"), ("thorough", "друге"), ("lend", "")]),
        ("source https://example.com/x", [("source https://example.com/x", "")]),
        ("well-known: a well-known fact", [("well-known", "a well-known fact")]),
        ("Borrow: x\nborrow: x\nborrow", [("Borrow", "x"), ("borrow", "")]),
        (": лише контекст", []),
    ],
)
def test_vocabulary_with_context(args: str, expected: list[tuple[str, str]]) -> None:
    assert parse_vocabulary(args) == expected


def test_vocabulary_lines_round_trip() -> None:
    assert vocabulary_line("borrow", "") == "- borrow"
    assert vocabulary_line("reluctant", "She was reluctant") == "- reluctant — She was reluctant"
    assert read_vocabulary_line("- reluctant — She was reluctant — really") == ("reluctant", "She was reluctant — really")
    assert read_vocabulary_line("- borrow") == ("borrow", "")
    assert read_vocabulary_line("lend") == ("lend", "")


@pytest.mark.parametrize(
    ("args", "minutes"),
    [("95", 95), ("1:35", 95), ("1г35", 95), ("1h35", 95), ("2 год", 120), ("1 год 5 хв", 65), ("0", 0)],
)
def test_duration(args: str, minutes: int) -> None:
    assert parse_duration(args, "") == minutes


@pytest.mark.parametrize("args", ["багато", "1:2:3", "1441", "25:00"])
def test_bad_duration(args: str) -> None:
    with pytest.raises(CommandError):
        parse_duration(args, "")


@pytest.mark.parametrize(("args", "hours"), [("7.5", 7.5), ("7,5", 7.5), ("7:30", 7.5), ("8", 8.0), ("0", 0.0)])
def test_hours(args: str, hours: float) -> None:
    assert parse_hours(args, "") == hours


@pytest.mark.parametrize("args", ["багато", "25", "-1", "nan", "inf"])
def test_bad_hours(args: str) -> None:
    with pytest.raises(CommandError):
        parse_hours(args, "")


@pytest.mark.parametrize("args", ["0", "6", "4.5", "", "багато"])
def test_bad_energy(args: str) -> None:
    with pytest.raises(CommandError):
        parse_energy(args, "")


def test_energy() -> None:
    assert parse_energy(" 4 ", "") == 4


@pytest.mark.parametrize(("text", "expected"), [("20:00", time(20, 0)), ("8:05", time(8, 5)), ("21.30", time(21, 30))])
def test_clock(text: str, expected: time) -> None:
    assert parse_clock(text) == expected


@pytest.mark.parametrize("text", ["24:00", "20:60", "20", "вечір"])
def test_bad_clock(text: str) -> None:
    with pytest.raises(CommandError):
        parse_clock(text)


def test_one_line_keeps_every_entry_on_a_single_line() -> None:
    assert one_line(" перше\n\n  друге \n") == "перше / друге"
