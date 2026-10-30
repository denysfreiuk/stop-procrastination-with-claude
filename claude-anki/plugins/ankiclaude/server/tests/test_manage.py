"""Finding, editing, tagging, deleting, problem cards and statistics."""

from __future__ import annotations

import pytest

from anki_claude.notes import DuplicateCandidate, NoteIn, NoteValidationError

from .fake_ankiconnect import FakeAnkiConnect
from .test_notes import ready, vocab


async def seeded(fake: FakeAnkiConnect, make_anki, **env):
    anki = await ready(fake, make_anki, **env)
    report = await anki.add_notes(
        [
            vocab(),
            vocab("eager", Active="no"),
            NoteIn(type="concept", deck="ML", fields={"Front": "Що таке recall?", "Back": "TP / (TP + FN)"},
                   tags=["topic::ml::metrics"]),
        ]
    )
    ids = {item["key"]: item["note_id"] for item in report["added"]}
    return anki, ids


async def test_find_notes_returns_fields_tags_and_cards(fake: FakeAnkiConnect, make_anki) -> None:
    anki, ids = await seeded(fake, make_anki)
    found = await anki.notes.find('deck:"Den" tag:topic::english')
    assert found["total"] == 2
    reluctant = next(n for n in found["notes"] if n["key"] == "reluctant")
    assert reluctant["type"] == "vocab"
    assert [c["template"] for c in reluctant["cards"]] == ["Recognition", "Production"]
    assert reluctant["cards"][1]["suspended"] is True
    assert reluctant["fields"]["Word"] == "reluctant"
    ml = await anki.notes.find('deck:"Den::ML"', with_fields=False)
    assert ml["total"] == 1 and "fields" not in ml["notes"][0]


async def test_check_duplicates_finds_exact_and_similar(fake: FakeAnkiConnect, make_anki) -> None:
    anki, ids = await seeded(fake, make_anki)
    result = await anki.notes.check_duplicates(
        [DuplicateCandidate(type="vocab", key="reluctant"), DuplicateCandidate(type="vocab", key="reluctantly"),
         DuplicateCandidate(type="vocab", key="cheerful")]
    )
    exact, similar, fresh = result["results"]
    assert [m["note_id"] for m in exact["exact"]] == [ids["reluctant"]]
    assert [m["key"] for m in similar["similar"]] == ["reluctant"]
    assert fresh["exact"] == [] and fresh["similar"] == []
    assert result["with_matches"] == 2


async def test_activating_a_word_creates_a_waiting_production_card(fake: FakeAnkiConnect, make_anki) -> None:
    anki, ids = await seeded(fake, make_anki)
    report = await anki.notes.update_fields(ids["eager"], {"Active": "yes"})
    assert report["changed"] == ["Active"]
    production = fake.card(ids["eager"], 1)
    assert production["deck"] == "Den::English::UA-EN" and production["queue"] == -1
    assert "status::pending-production" in fake.notes[ids["eager"]]["tags"]


async def test_known_activation_and_deactivation(fake: FakeAnkiConnect, make_anki) -> None:
    anki, ids = await seeded(fake, make_anki)
    await anki.notes.update_fields(ids["eager"], {"Active": "yes"}, known=True)
    assert fake.card(ids["eager"], 1)["queue"] == 0
    report = await anki.notes.update_fields(ids["reluctant"], {"Active": "no"})
    assert fake.card(ids["reluctant"], 1)["queue"] == -1
    assert "status::pending-production" not in fake.notes[ids["reluctant"]]["tags"]
    assert report["cards"] == ["Active вимкнено: картку UA→EN призупинено"]


async def test_update_validates_like_add(fake: FakeAnkiConnect, make_anki) -> None:
    anki, ids = await seeded(fake, make_anki)
    with pytest.raises(NoteValidationError, match="<b>"):
        await anki.notes.update_fields(ids["reluctant"], {"Example1": "no mark"})
    with pytest.raises(NoteValidationError, match="Forms порожнє"):
        await anki.notes.update_fields(ids["reluctant"], {"DrillForms": "yes"})
    with pytest.raises(NoteValidationError, match="невідомі поля"):
        await anki.notes.update_fields(ids["reluctant"], {"Wrod": "x"})
    report = await anki.notes.update_fields(ids["reluctant"], {"Example3": "A **reluctant** hero."})
    assert fake.notes[ids["reluctant"]]["fields"]["Example3"] == "A <b>reluctant</b> hero."
    assert (await anki.notes.update_fields(ids["reluctant"], {"Example3": "A **reluctant** hero."}))["changed"] == []
    assert report["changed"] == ["Example3"]


async def test_small_tag_changes_run_directly(fake: FakeAnkiConnect, make_anki) -> None:
    anki, ids = await seeded(fake, make_anki)
    result = await anki.notes.change_tags("add", [ids["eager"]], ["Status::To Check"], anki.confirmations, None)
    assert result["done"] is True
    assert "status::to-check" in fake.notes[ids["eager"]]["tags"]
    await anki.notes.change_tags("remove", [ids["eager"]], ["status::to-check"], anki.confirmations, None)
    assert "status::to-check" not in fake.notes[ids["eager"]]["tags"]


async def test_mass_tag_changes_need_a_token(fake: FakeAnkiConnect, make_anki) -> None:
    anki = await ready(fake, make_anki)
    report = await anki.add_notes([vocab(f"word{chr(97 + i)}{chr(97 + i)}") for i in range(21)])
    note_ids = [item["note_id"] for item in report["added"]]
    first = await anki.notes.change_tags("add", note_ids, ["topic::bulk"], anki.confirmations, None)
    assert first["needs_confirmation"] is True
    assert all("topic::bulk" not in fake.notes[n]["tags"] for n in note_ids)
    wrong = await anki.notes.change_tags("add", note_ids, ["topic::other"], anki.confirmations, first["confirm_token"])
    assert wrong["needs_confirmation"] is True, "a token only covers the previewed arguments"
    done = await anki.notes.change_tags("add", note_ids, ["topic::bulk"], anki.confirmations, first["confirm_token"])
    assert done["done"] is True
    assert all("topic::bulk" in fake.notes[n]["tags"] for n in note_ids)


async def test_delete_always_needs_a_fresh_token(fake: FakeAnkiConnect, make_anki) -> None:
    anki, ids = await seeded(fake, make_anki)
    preview = await anki.notes.delete([ids["eager"]], anki.confirmations, None)
    assert preview["needs_confirmation"] is True
    assert preview["preview"]["list"][0]["key"] == "eager"
    assert ids["eager"] in fake.notes
    assert (await anki.notes.delete([ids["reluctant"]], anki.confirmations, preview["confirm_token"]))["needs_confirmation"]
    assert (await anki.notes.delete([ids["eager"]], anki.confirmations, preview["confirm_token"])) == {"deleted": 1}
    assert ids["eager"] not in fake.notes
    again = await anki.notes.delete([ids["reluctant"]], anki.confirmations, preview["confirm_token"])
    assert again["needs_confirmation"] is True, "tokens are single-use"


async def test_leeches_are_ranked_by_lapses(fake: FakeAnkiConnect, make_anki) -> None:
    anki, ids = await seeded(fake, make_anki)
    fake.card(ids["eager"], 0)["lapses"] = 9
    fake.card(ids["reluctant"], 0)["lapses"] = 5
    fake.notes[ids["Що таке recall?"]]["tags"].append("leech")
    result = await anki.insights.leeches(min_lapses=4)
    assert [n["key"] for n in result["notes"]] == ["eager", "reluctant", "Що таке recall?"]
    assert result["notes"][0]["problem_cards"][0]["lapses"] == 9


async def test_stats_summarise_the_collection(fake: FakeAnkiConnect, make_anki) -> None:
    anki, ids = await seeded(fake, make_anki)
    stats = await anki.insights.stats()
    assert stats["counts"]["notes"] == 3
    assert stats["counts"]["cards"] == 4
    assert stats["counts"]["waiting_production"] == 1
    assert stats["reviewed_today"] == 5
    assert len(stats["reviews_last_7_days"]) == 7
    assert {"topic": "topic::english::adjectives", "notes": 2} in stats["top_topics"]


def test_last_days_fills_calendar_gaps() -> None:
    from datetime import date

    from anki_claude.insights import last_days

    by_day = [["2026-10-29", 5], ["2026-10-27", 12], ["2026-03-12", 4]]
    days = last_days(by_day, 3, today=date(2026, 10, 29))
    assert days == [{"date": "2026-10-27", "cards": 12}, {"date": "2026-10-28", "cards": 0}, {"date": "2026-10-29", "cards": 5}]
