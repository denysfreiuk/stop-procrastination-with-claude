from __future__ import annotations

from .fake_ankiconnect import FakeAnkiConnect
from .test_notes import ready, vocab


async def add_word(anki, fake, word="reluctant", **fields):
    report = await anki.add_notes([vocab(word, **fields)])
    return report["added"][0]["note_id"]


async def test_production_waits_until_recognition_is_learned(fake: FakeAnkiConnect, make_anki) -> None:
    anki = await ready(fake, make_anki, ANKI_AUTO_SYNC="true")
    note_id = await add_word(anki, fake)
    fake.card(note_id, 0)["ivl"] = 2
    report = await anki.promote()
    assert report["promoted"] == [] and report["waiting_total"] == 1
    assert fake.card(note_id, 1)["queue"] == -1

    fake.card(note_id, 0)["ivl"] = 3
    syncs_before = fake.syncs
    report = await anki.promote()
    assert report["promoted"] == [{"word": "reluctant", "card": "UA→EN", "after": "EN→UA 3 дн."}]
    assert fake.card(note_id, 1)["queue"] == 0, "released as a new card"
    assert "status::pending-production" not in fake.notes[note_id]["tags"]
    assert fake.syncs == syncs_before + 2, "sync before checking and after releasing"
    assert report["message"].startswith("Розморожено 1: reluctant (UA→EN)")


async def test_forms_follow_production_not_recognition(fake: FakeAnkiConnect, make_anki) -> None:
    anki = await ready(fake, make_anki)
    note_id = await add_word(anki, fake, "go", Forms="go – went – gone", DrillForms="yes",
                             Example1="I <b>go</b> home.", Example2="We <b>went</b> out.")
    fake.card(note_id, 0)["ivl"] = 30
    report = await anki.promote()
    assert [p["card"] for p in report["promoted"]] == ["UA→EN"], "forms wait for the just-released production"
    assert fake.card(note_id, 2)["queue"] == -1
    fake.card(note_id, 1)["ivl"] = 4
    report = await anki.promote()
    assert [p["card"] for p in report["promoted"]] == ["Форми"]
    assert fake.card(note_id, 2)["queue"] == 0
    assert "status::pending-forms" not in fake.notes[note_id]["tags"]


async def test_forms_of_a_passive_word_follow_recognition(fake: FakeAnkiConnect, make_anki) -> None:
    anki = await ready(fake, make_anki)
    note_id = await add_word(anki, fake, "go", Active="no", Forms="go – went – gone", DrillForms="yes",
                             Example1="I <b>go</b> home.", Example2="We <b>went</b> out.")
    fake.card(note_id, 0)["ivl"] = 5
    report = await anki.promote()
    assert report["promoted"] == [{"word": "go", "card": "Форми", "after": "EN→UA 5 дн."}]


async def test_threshold_comes_from_config(fake: FakeAnkiConnect, make_anki) -> None:
    anki = await ready(fake, make_anki, ANKI_PROMOTE_AFTER_DAYS="7")
    note_id = await add_word(anki, fake)
    fake.card(note_id, 0)["ivl"] = 5
    assert (await anki.promote())["promoted"] == []
    fake.card(note_id, 0)["ivl"] = 7
    assert len((await anki.promote())["promoted"]) == 1


async def test_failed_sync_releases_nothing(make_anki) -> None:
    fake = FakeAnkiConnect(logged_in=True)
    anki = await ready(fake, make_anki, ANKI_AUTO_SYNC="true")
    note_id = await add_word(anki, fake)
    fake.card(note_id, 0)["ivl"] = 10
    fake.logged_in = False
    report = await anki.promote()
    assert report["status"] == "sync_failed" and report["reason"] == "not_logged_in"
    assert "Нічого не розморожено" in report["message"]
    assert fake.card(note_id, 1)["queue"] == -1


async def test_reviewing_defers_unless_forced(fake: FakeAnkiConnect, make_anki) -> None:
    anki = await ready(fake, make_anki, ANKI_AUTO_SYNC="true")
    note_id = await add_word(anki, fake)
    fake.card(note_id, 0)["ivl"] = 10
    fake.reviewing = True
    assert (await anki.promote())["status"] == "deferred"
    assert fake.card(note_id, 1)["queue"] == -1
    assert len((await anki.promote(force=True))["promoted"]) == 1


async def test_without_auto_sync_it_works_locally(fake: FakeAnkiConnect, make_anki) -> None:
    anki = await ready(fake, make_anki)  # ready() turns auto_sync off
    note_id = await add_word(anki, fake)
    fake.card(note_id, 0)["ivl"] = 10
    fake.reviewing = True
    report = await anki.promote()
    assert len(report["promoted"]) == 1 and report["sync"] == [] and fake.syncs == 0


async def test_cards_suspended_by_someone_else_are_left_alone(fake: FakeAnkiConnect, make_anki) -> None:
    anki = await ready(fake, make_anki)
    report = await anki.add_notes([vocab()], known=True)
    note_id = report["added"][0]["note_id"]
    fake.card(note_id, 1)["queue"] = -1  # e.g. Anki suspended a leech
    fake.card(note_id, 0)["ivl"] = 30
    assert (await anki.promote())["promoted"] == []
    assert fake.card(note_id, 1)["queue"] == -1


async def test_dry_run_changes_nothing(fake: FakeAnkiConnect, make_anki) -> None:
    anki = await ready(fake, make_anki)
    note_id = await add_word(anki, fake)
    fake.card(note_id, 0)["ivl"] = 10
    report = await anki.promote(dry_run=True)
    assert len(report["promoted"]) == 1 and "пробний запуск" in report["message"]
    assert fake.card(note_id, 1)["queue"] == -1
    assert "status::pending-production" in fake.notes[note_id]["tags"]
