from __future__ import annotations

from datetime import date

import pytest

from anki_claude.notes import NoteIn, normalize_tag, NoteValidationError

from .fake_ankiconnect import FakeAnkiConnect

MONTH = f"added::{date.today():%Y-%m}"


def vocab(word: str = "reluctant", **fields: str) -> NoteIn:
    base = {
        "Word": word,
        "IPA": "/rɪˈlʌktənt/",
        "PartOfSpeech": "adjective",
        "MeaningEN": "not wanting to do something",
        "TranslationUA": "неохочий",
        "Example1": f"He was <b>{word}</b> to admit it.",
        "Example2": f"She seemed **{word}** to leave.",
        "WhyThisWord": "Сильніше за not willing.",
        "Register": "Neutral",
        "Active": "yes",
    }
    base.update(fields)
    return NoteIn(type="vocab", fields=base, tags=["topic::english::Adjectives", "level::b2"])


async def ready(fake: FakeAnkiConnect, make_anki, **env: str):
    anki = make_anki(fake, **{"ANKI_AUTO_SYNC": "false", **env})
    await anki.decks.setup()
    await anki.note_types.ensure()
    return anki


@pytest.mark.parametrize("v1", [True, False])
async def test_vocab_cards_land_in_their_decks_and_production_waits(v1: bool, make_anki) -> None:
    fake = FakeAnkiConnect(v1=v1)
    anki = await ready(fake, make_anki)
    report = await anki.add_notes([vocab()])
    assert report["summary"] == "додано 1, дублікатів 0, помилок 0"
    added = report["added"][0]
    assert added["deck"] == "Den::English::EN-UA" and added["cards"] == 2 and added["pending"] == ["production"]
    note_id = added["note_id"]
    recognition, production = fake.card(note_id, 0), fake.card(note_id, 1)
    assert recognition["deck"] == "Den::English::EN-UA" and recognition["queue"] == 0
    assert production["deck"] == "Den::English::UA-EN" and production["queue"] == -1
    note = fake.notes[note_id]
    assert set(note["tags"]) == {"topic::english::adjectives", "level::b2", "gen::claude", MONTH, "status::pending-production"}
    assert note["fields"]["Example2"] == "She seemed <b>reluctant</b> to leave."
    assert note["fields"]["Register"] == "neutral"
    assert ("changeDeck" in fake.calls) is (not v1)


async def test_known_words_get_an_active_production_card(fake: FakeAnkiConnect, make_anki) -> None:
    anki = await ready(fake, make_anki)
    report = await anki.add_notes([vocab(), vocab("eager", Active="yes")], known=True)
    for added in report["added"]:
        assert added["pending"] == []
        assert fake.card(added["note_id"], 1)["queue"] == 0


async def test_per_note_known_overrides_the_batch_flag(fake: FakeAnkiConnect, make_anki) -> None:
    anki = await ready(fake, make_anki)
    note = vocab()
    note.known = False
    report = await anki.add_notes([note], known=True)
    assert report["added"][0]["pending"] == ["production"]


async def test_passive_words_have_no_production_card(fake: FakeAnkiConnect, make_anki) -> None:
    anki = await ready(fake, make_anki)
    report = await anki.add_notes([vocab(Active="no")])
    added = report["added"][0]
    assert added["cards"] == 1 and added["pending"] == []
    assert fake.notes[added["note_id"]]["fields"]["Active"] == ""


async def test_forms_card_always_waits(fake: FakeAnkiConnect, make_anki) -> None:
    anki = await ready(fake, make_anki)
    note = vocab("go", Forms="go – went – gone", DrillForms="yes", Example1="I <b>go</b> home.", Example2="We <b>went</b> out.")
    report = await anki.add_notes([note], known=True)
    added = report["added"][0]
    assert added["cards"] == 3 and added["pending"] == ["forms"]
    forms = fake.card(added["note_id"], 2)
    assert forms["deck"] == "Den::English::UA-EN" and forms["queue"] == -1
    assert "status::pending-forms" in fake.notes[added["note_id"]]["tags"]


@pytest.mark.parametrize(
    ("fields", "message"),
    [
        ({"Example2": ""}, "щонайменше 2"),
        ({"Example1": "No marked word here."}, "<b>"),
        ({"Active": "maybe"}, "yes або no"),
        ({"Register": "posh"}, "Register"),
        ({"DrillForms": "yes"}, "Forms порожнє"),
        ({"WhyThisWord": "x" * 301}, "скороти"),
        ({"Wordd": "typo"}, "невідомі поля"),
        ({"TranslationUA": ""}, "обов'язкові"),
    ],
)
async def test_vocab_validation(fields, message, fake: FakeAnkiConnect, make_anki) -> None:
    anki = await ready(fake, make_anki)
    report = await anki.add_notes([vocab(**fields), vocab("eager")])
    assert report["summary"] == "додано 1, дублікатів 0, помилок 1"
    assert message in report["errors"][0]["error"]
    assert report["errors"][0]["index"] == 0


async def test_duplicates_are_reported_with_the_existing_note(fake: FakeAnkiConnect, make_anki) -> None:
    anki = await ready(fake, make_anki)
    first = (await anki.add_notes([vocab()]))["added"][0]["note_id"]
    report = await anki.add_notes([vocab(), vocab("eager")])
    assert report["summary"] == "додано 1, дублікатів 1, помилок 0"
    assert report["duplicates"][0]["existing_note_ids"] == [first]


async def test_other_types_need_a_deck_and_create_it_lazily(fake: FakeAnkiConnect, make_anki) -> None:
    anki = await ready(fake, make_anki)
    concept = NoteIn(type="concept", fields={"Front": "Що таке precision?", "Back": "TP / (TP + FP)"}, tags=["topic::ml::metrics"])
    report = await anki.add_notes([concept])
    assert "колоду" in report["errors"][0]["error"]

    code = NoteIn(
        type="code",
        deck="Code::Python",
        fields={"Prompt": "Що виведе код?", "Code": "xs = [1, 2]\nprint(xs[-1] < 3)", "Answer": "True", "Language": " Python "},
    )
    report = await anki.add_notes([code])
    assert report["decks_created"] == ["Den::Code", "Den::Code::Python"]
    note = fake.notes[report["added"][0]["note_id"]]
    assert note["deck"] == "Den::Code::Python"
    assert note["fields"]["Code"] == "xs = [1, 2]<br>print(xs[-1] &lt; 3)"
    assert note["fields"]["Language"] == "python"


async def test_fixed_deck_types_ignore_a_wrong_deck_with_a_warning(fake: FakeAnkiConnect, make_anki) -> None:
    anki = await ready(fake, make_anki)
    note = NoteIn(type="distinction", deck="ML", fields={"Sentence": "___ a mistake (make / do)", "Answer": "make", "Pair": "make/do"})
    report = await anki.add_notes([note])
    assert report["added"][0]["deck"] == "Den::English::Distinctions"
    assert "проігноровано" in report["warnings"][0]


@pytest.mark.parametrize(
    ("note", "message"),
    [
        (NoteIn(type="cloze", deck="ML", fields={"Text": "Немає пропусків"}), "{{c1::"),
        (NoteIn(type="distinction", fields={"Sentence": "a mistake", "Answer": "make", "Pair": "make/do"}), "___"),
    ],
)
async def test_type_specific_rules(note, message, fake: FakeAnkiConnect, make_anki) -> None:
    anki = await ready(fake, make_anki)
    report = await anki.add_notes([note])
    assert message in report["errors"][0]["error"]


def test_tag_normalization() -> None:
    assert normalize_tag("Topic::ML::Linear Algebra") == "topic::ml::linear-algebra"
    assert normalize_tag("source::cs231n_lecture_3") == "source::cs231n-lecture-3"
    assert normalize_tag("source::the-office-s01e02") == "source::the-office-s01e02"
    for bad in ("тема::мл", "topic:::x", "a b c!"):
        with pytest.raises(NoteValidationError):
            normalize_tag(bad)


async def test_auto_sync_after_adding(fake: FakeAnkiConnect, make_anki) -> None:
    anki = make_anki(fake)
    await anki.decks.setup()
    await anki.note_types.ensure()
    report = await anki.add_notes([vocab()])
    assert report["sync"]["status"] == "synced"


async def test_failed_auto_sync_does_not_lose_the_added_notes(make_anki) -> None:
    fake = FakeAnkiConnect(logged_in=False)
    anki = make_anki(fake)
    await anki.decks.setup()
    await anki.note_types.ensure()
    report = await anki.add_notes([vocab()])
    assert len(report["added"]) == 1
    assert report["sync"]["status"] == "failed" and report["sync"]["reason"] == "not_logged_in"
