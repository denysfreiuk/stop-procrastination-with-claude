from __future__ import annotations

import pytest

from anki_claude.decks import DeckError

from .fake_ankiconnect import FakeAnkiConnect


def preset_of(fake: FakeAnkiConnect, deck: str) -> dict:
    return fake.presets[fake.deck_preset[deck]]


async def test_setup_creates_structure_presets_and_totals(fake: FakeAnkiConnect, make_anki) -> None:
    report = await make_anki(fake).decks.setup()
    assert report["created"] == ["Den", "Den::English", "Den::English::EN-UA", "Den::English::UA-EN",
                                 "Den::English::Distinctions", "Den::ML", "Den::Uni"]
    assert "Den::Code" not in fake.decks  # created only with its first card
    limits = {deck: preset_of(fake, deck)["new"]["perDay"] for deck in report["created"]}
    assert limits == {"Den": 24, "Den::English": 20, "Den::English::EN-UA": 10, "Den::English::UA-EN": 7,
                      "Den::English::Distinctions": 3, "Den::ML": 2, "Den::Uni": 2}
    for deck in report["created"]:
        preset = preset_of(fake, deck)
        assert preset["name"].startswith("AC · ")
        assert preset["rev"]["perDay"] == 9999
        assert preset["new"]["bury"] is True
    assert preset_of(fake, "Den")["name"] == "AC · Den"
    assert preset_of(fake, "Den")["newGatherPriority"] == 3
    assert fake.presets[1]["new"]["perDay"] == 20, "the user's default preset is untouched"


async def test_setup_is_idempotent_and_keeps_user_limits(fake: FakeAnkiConnect, make_anki) -> None:
    anki = make_anki(fake)
    await anki.decks.setup()
    preset_of(fake, "Den::ML")["new"]["perDay"] = 1
    presets_before = len(fake.presets)
    report = await anki.decks.setup()
    assert report["created"] == []
    assert report["presets_created"] == []
    assert len(fake.presets) == presets_before
    assert preset_of(fake, "Den::ML")["new"]["perDay"] == 1
    assert preset_of(fake, "Den")["new"]["perDay"] == 23


async def test_lazy_branch_decks_share_the_branch_preset(fake: FakeAnkiConnect, make_anki) -> None:
    anki = make_anki(fake)
    await anki.decks.setup()
    name, created = await anki.decks.ensure("Code::Python")
    assert name == "Den::Code::Python"
    assert created == ["Den::Code", "Den::Code::Python"]
    await anki.decks.ensure("Den::Code::Git")
    await anki.decks.ensure("Uni::Calculus")
    assert fake.deck_preset["Den::Code::Python"] == fake.deck_preset["Den::Code"] == fake.deck_preset["Den::Code::Git"]
    assert fake.deck_preset["Den::Uni::Calculus"] == fake.deck_preset["Den::Uni"]
    assert preset_of(fake, "Den")["new"]["perDay"] == 26
    assert (await anki.decks.ensure("ML")) == ("Den::ML", [])


async def test_new_top_level_branch_gets_its_own_small_preset(fake: FakeAnkiConnect, make_anki) -> None:
    anki = make_anki(fake)
    await anki.decks.setup()
    await anki.decks.ensure("History::Ukraine")
    assert preset_of(fake, "Den::History")["name"] == "AC · History"
    assert fake.deck_preset["Den::History::Ukraine"] == fake.deck_preset["Den::History"]
    assert preset_of(fake, "Den")["new"]["perDay"] == 26


async def test_set_options_updates_branch_and_recomputes_totals(fake: FakeAnkiConnect, make_anki) -> None:
    anki = make_anki(fake)
    await anki.decks.setup()
    result = await anki.decks.set_options("Den::English::UA-EN", new_per_day=5, reviews_per_day=None)
    assert result["new_per_day"] == 5
    assert result["totals"] == {"Den": 22, "Den::English": 18}
    await anki.decks.ensure("Uni::Calculus")
    shared = await anki.decks.set_options("Uni", new_per_day=1, reviews_per_day=300)
    assert shared["also_affects"] == ["Den::Uni::Calculus"]
    assert preset_of(fake, "Den::Uni")["rev"]["perDay"] == 300


async def test_total_decks_cannot_be_set_by_hand(fake: FakeAnkiConnect, make_anki) -> None:
    anki = make_anki(fake)
    await anki.decks.setup()
    with pytest.raises(DeckError, match="сума підколод"):
        await anki.decks.set_options("Den", new_per_day=50, reviews_per_day=None)
    with pytest.raises(DeckError, match="немає"):
        await anki.decks.set_options("Nope", new_per_day=1, reviews_per_day=None)


async def test_resolve_accepts_relative_and_full_names(fake: FakeAnkiConnect, make_anki) -> None:
    decks = make_anki(fake).decks
    assert decks.resolve("ML") == "ML"
    assert decks.resolve("Den::ML") == "ML"
    assert decks.resolve(" Code :: Python ") == "Code::Python"
    assert decks.resolve("Den") == ""


async def test_overview_reports_limits_and_counts(fake: FakeAnkiConnect, make_anki) -> None:
    anki = make_anki(fake)
    assert (await anki.decks.overview())["exists"] is False
    await anki.decks.setup()
    overview = await anki.decks.overview()
    by_deck = {d["deck"]: d for d in overview["decks"]}
    assert by_deck["Den::English::EN-UA"]["new_per_day"] == 10
    assert by_deck["Den"]["cards"] == 0
