from __future__ import annotations

import re

import pytest

from anki_claude import __version__
from anki_claude.constants import NOTE_TYPE_NAMES
from anki_claude.errors import AnkiError
from anki_claude.notes import NoteIn
from anki_claude.notetypes import HIGHLIGHT_MEDIA, LABELS, build_specs, made_by, render_template

from .fake_ankiconnect import FakeAnkiConnect, front_has_content

SPECS = build_specs("uk")
SPECIAL = {"FrontSide", "Tags", "Type", "Deck", "Subdeck", "Card", "CardFlag"}


def references(template: str) -> set[str]:
    names = set()
    for raw in re.findall(r"\{\{([^}]+)\}\}", template):
        name = raw.lstrip("#^/").split(":")[-1].strip()
        if name not in SPECIAL:
            names.add(name)
    return names


def test_spec_names_match_constants() -> None:
    assert tuple(spec.name for spec in SPECS.values()) == NOTE_TYPE_NAMES


@pytest.mark.parametrize("spec", SPECS.values(), ids=lambda s: s.key)
def test_templates_only_reference_existing_fields(spec) -> None:
    for template in spec.templates:
        for side in (template.front, template.back):
            unknown = references(side) - set(spec.fields)
            assert not unknown, f"{spec.name}/{template.name}: {unknown}"


@pytest.mark.parametrize("spec", SPECS.values(), ids=lambda s: s.key)
def test_no_build_placeholders_left(spec) -> None:
    for template in spec.templates:
        assert "[[" not in template.front + template.back


def test_explanations_never_on_the_front() -> None:
    for spec in SPECS.values():
        for template in spec.templates:
            for hidden in ("WhyThisWord", "Explanation", "Why", "MeaningOfTerms", "WhenToUse", "Collocations"):
                assert f"{{{{{hidden}}}}}" not in template.front, f"{spec.name}/{template.name} shows {hidden}"


def test_production_card_is_typed_and_conditional() -> None:
    production = SPECS["vocab"].templates[1]
    assert production.front.startswith("{{#Active}}") and production.front.rstrip().endswith("{{/Active}}")
    assert "{{type:Word}}" in production.front and "{{type:Word}}" in production.back
    assert "Введи словникову форму" in production.front
    assert "{{TranslationUA}}" in production.front
    assert "{{Word}}" not in production.front.replace('data-ac-word>{{Word}}', "")


def vocab_fields(**overrides: str) -> dict[str, str]:
    fields = {name: "" for name in SPECS["vocab"].fields}
    fields.update(Word="go", MeaningEN="to move", TranslationUA="йти", Example1="I <b>go</b> home.", Example2="She <b>went</b> out.")
    fields.update(overrides)
    return fields


@pytest.mark.parametrize(
    ("overrides", "expected"),
    [
        ({}, ["Recognition"]),
        ({"Active": "yes"}, ["Recognition", "Production"]),
        ({"DrillForms": "yes"}, ["Recognition"]),
        ({"DrillForms": "yes", "Forms": "go – went – gone"}, ["Recognition", "Forms"]),
        ({"Active": "yes", "DrillForms": "yes", "Forms": "go – went – gone"}, ["Recognition", "Production", "Forms"]),
    ],
)
def test_vocab_cards_follow_anki_generation_rules(overrides, expected) -> None:
    fields = vocab_fields(**overrides)
    generated = [t.name for t in SPECS["vocab"].templates if front_has_content(t.front, fields)]
    assert generated == expected


def test_template_decks() -> None:
    assert [t.deck for t in SPECS["vocab"].templates] == ["English::EN-UA", "English::UA-EN", "English::UA-EN"]
    assert SPECS["distinction"].templates[0].deck == "English::Distinctions"
    assert all(t.deck is None for key in ("concept", "cloze", "formula", "code") for t in SPECS[key].templates)


def test_scripts_are_inlined_with_persistence_and_media_name() -> None:
    recognition = SPECS["vocab"].templates[0]
    assert "window.Persistence" in recognition.front
    assert "data-ac-example" in recognition.front
    assert HIGHLIGHT_MEDIA in SPECS["code"].templates[0].front


def test_back_sides_mark_themselves_before_front_side_scripts_run() -> None:
    for spec in SPECS.values():
        for template in spec.templates:
            if "{{FrontSide}}" in template.back and "<script>" in template.front:
                assert template.back.index('id="ac-back"') < template.back.index("{{FrontSide}}"), template.name


def test_speech_can_be_turned_off() -> None:
    with_tts = [t.front + t.back for t in SPECS["vocab"].templates]
    assert sum("{{tts en_US:Word}}" in side for side in with_tts) == 2
    assert "{{tts en_US:Forms}}" in with_tts[2]
    quiet = build_specs("uk", tts=False)
    for spec in quiet.values():
        for t in spec.templates:
            assert "{{tts" not in t.front + t.back and "ac-tts" not in t.front + t.back


def test_speech_language_is_configurable() -> None:
    british = build_specs("uk", tts_lang="en_GB")["vocab"].templates
    assert "{{tts en_GB:Word}}" in british[0].front and "{{tts en_GB:Forms}}" in british[2].back


@pytest.mark.parametrize(("raw", "expected"), [("en-gb", "en_GB"), ("EN_us", "en_US"), ("british", "en_US")])
def test_speech_language_config_is_normalized(raw: str, expected: str) -> None:
    from anki_claude.config import load_config

    assert load_config({"ANKI_TTS_LANG": raw}).tts_lang == expected


async def test_turning_speech_off_updates_templates_without_full_sync(fake: FakeAnkiConnect, make_anki) -> None:
    await make_anki(fake).note_types.ensure()
    report = await make_anki(fake, ANKI_TTS="false").note_types.ensure()
    assert report["updated"] == ["AC Vocab"]
    assert report["full_sync_required"] is False
    assert all("{{tts" not in t["front"] + t["back"] for t in fake.note_types["AC Vocab"]["templates"])


def test_css_supports_night_mode_and_phones() -> None:
    css = SPECS["vocab"].css
    assert ".nightMode" in css and ".night_mode" in css
    assert "@media (max-width: 480px)" in css


def test_labels_are_localised_with_english_fallback() -> None:
    assert "Сполучення" in render_template("[[label:collocations]]", "uk")
    assert "Collocations" in render_template("[[label:collocations]]", "de")
    assert set(LABELS["uk"]) == set(LABELS["en"])
    with pytest.raises(ValueError):
        render_template("[[label:nope]]", "uk")


async def test_ensure_creates_all_types_with_template_decks(fake: FakeAnkiConnect, make_anki) -> None:
    anki = make_anki(fake)
    await anki.decks.setup()
    report = await anki.note_types.ensure()
    assert report["created"] == list(NOTE_TYPE_NAMES)
    assert report["media_stored"] == [HIGHLIGHT_MEDIA]
    vocab = fake.note_types["AC Vocab"]
    assert [fake._deck_name(t["did"]) for t in vocab["templates"]] == ["Den::English::EN-UA", "Den::English::UA-EN", "Den::English::UA-EN"]
    assert fake.note_types["AC Cloze"]["kind"] == "cloze"

    again = await anki.note_types.ensure()
    assert again["created"] == [] and again["updated"] == []
    assert again["unchanged"] == list(NOTE_TYPE_NAMES)
    assert again["media_stored"] == []


async def test_ensure_without_api_v1_uses_create_model(make_anki) -> None:
    fake = FakeAnkiConnect(v1=False)
    anki = make_anki(fake)
    report = await anki.note_types.ensure()
    assert "createModel" in fake.calls
    assert report["deck_overrides"].startswith("маршрутизація")
    assert all(t["did"] is None for t in fake.note_types["AC Vocab"]["templates"])


async def test_ensure_updates_outdated_types_and_flags_full_sync(fake: FakeAnkiConnect, make_anki) -> None:
    anki = make_anki(fake)
    await anki.note_types.ensure()
    vocab = fake.note_types["AC Vocab"]
    vocab["css"] = "/* old */"
    vocab["templates"][0]["front"] = "{{Word}}"
    vocab["templates"][1]["did"] = None
    vocab["fields"].remove("DrillForms")

    preview = await anki.note_types.ensure(dry_run=True)
    assert preview["updated"] == ["AC Vocab"]
    assert vocab["css"] == "/* old */", "dry run changes nothing"

    report = await anki.note_types.ensure()
    assert report["full_sync_required"] is True
    assert set(report["changes"]["AC Vocab"]) == {
        "нове поле DrillForms", "оновлено шаблон Recognition", "оновлено CSS", "колода шаблону Production → Den::English::UA-EN",
    }
    assert vocab["fields"] == list(SPECS["vocab"].fields)
    assert vocab["css"] == SPECS["vocab"].css
    assert fake._deck_name(vocab["templates"][1]["did"]) == "Den::English::UA-EN"


def made_by_plugin(fake: FakeAnkiConnect, version: str | None) -> None:
    """Make the AC types look as if plugin `version` wrote them (None: before versions were recorded)."""
    for note_type in fake.note_types.values():
        if "/* ankiclaude " in note_type["css"]:
            marker = f"/* ankiclaude {version} */\n" if version else ""
            note_type["css"] = re.sub(r"/\* ankiclaude [\d.]+ \*/\n", marker, note_type["css"])
    fake.note_types["AC Vocab"]["templates"][1]["front"] += "<!-- old -->"


async def ready_types(fake: FakeAnkiConnect, make_anki, **env: str):
    anki = make_anki(fake, **{"ANKI_AUTO_SYNC": "false", **env})
    await anki.decks.setup()
    await anki.note_types.ensure()
    return anki


def test_css_records_the_plugin_version() -> None:
    assert made_by(SPECS["vocab"].css) == __version__
    assert made_by("/* no marker */") is None


@pytest.mark.parametrize("version", ["0.4.1", None])
async def test_add_notes_updates_types_an_older_plugin_made_once(version, fake: FakeAnkiConnect, make_anki) -> None:
    anki = await ready_types(fake, make_anki)
    made_by_plugin(fake, version)
    assert "оновляться самі" in " ".join((await anki.connection_report())["next_steps"])
    assert (await anki.note_types.overview())["ac_note_types"]["AC Vocab"] == "застарів"

    concept = NoteIn(type="concept", fields={"Front": "Що таке recall?", "Back": "TP / (TP + FN)"}, tags=["topic::ml::metrics"])
    report = await anki.add_notes([concept])
    update = report["note_types_update"]
    assert update["status"] == "updated" and "AC Vocab" in update["note_types"]
    assert fake.note_types["AC Vocab"]["templates"][1]["front"] == SPECS["vocab"].templates[1].front
    assert made_by(fake.note_types["AC Vocab"]["css"]) == __version__

    made_by_plugin(fake, version)
    again = await anki.add_notes([NoteIn(type="concept", fields={"Front": "Що таке F1?", "Back": "2PR / (P + R)"})])
    assert "note_types_update" not in again, "checked once per server run"


async def test_types_from_a_newer_plugin_are_never_rolled_back(fake: FakeAnkiConnect, make_anki) -> None:
    anki = await ready_types(fake, make_anki)
    made_by_plugin(fake, "99.0.0")
    changed = fake.note_types["AC Vocab"]["templates"][1]["front"]

    assert await anki.keep_note_types_current() is None
    with pytest.raises(AnkiError, match="новіша версія плагіна"):
        await anki.note_types.ensure()
    assert fake.note_types["AC Vocab"]["templates"][1]["front"] == changed
    assert (await anki.note_types.overview())["ac_note_types"]["AC Vocab"] == "новіший за плагін (99.0.0)"
    assert "старіший за типи нотаток" in " ".join((await anki.connection_report())["next_steps"])


async def test_other_settings_of_the_same_version_wait_for_ensure(fake: FakeAnkiConnect, make_anki) -> None:
    await ready_types(fake, make_anki)
    anki = make_anki(fake, ANKI_TTS="false", ANKI_AUTO_SYNC="false")
    assert await anki.keep_note_types_current() is None
    assert any("{{tts" in t["front"] for t in fake.note_types["AC Vocab"]["templates"])
    assert (await anki.note_types.overview())["ac_note_types"]["AC Vocab"] == "не збігається з налаштуваннями"


async def test_an_update_that_needs_a_full_sync_asks_first(fake: FakeAnkiConnect, make_anki) -> None:
    anki = await ready_types(fake, make_anki)
    made_by_plugin(fake, "0.4.1")
    fake.note_types["AC Vocab"]["fields"].remove("DrillForms")

    update = await anki.keep_note_types_current()
    assert update["status"] == "needs_confirmation"
    assert "DrillForms" not in fake.note_types["AC Vocab"]["fields"], "nothing changed without the user"
    assert "повну" in " ".join((await anki.connection_report())["next_steps"])


async def test_no_update_while_the_user_reviews(fake: FakeAnkiConnect, make_anki) -> None:
    anki = await ready_types(fake, make_anki)
    made_by_plugin(fake, "0.4.1")
    fake.reviewing = True
    assert await anki.keep_note_types_current() is None
    assert made_by(fake.note_types["AC Vocab"]["css"]) == "0.4.1"
    fake.reviewing = False
    assert (await anki.keep_note_types_current())["status"] == "updated"


async def test_overview_reports_status(fake: FakeAnkiConnect, make_anki) -> None:
    anki = make_anki(fake)
    assert set((await anki.note_types.overview())["ac_note_types"].values()) == {"немає"}
    await anki.note_types.ensure()
    overview = await anki.note_types.overview()
    assert set(overview["ac_note_types"].values()) == {"актуальний"}
    assert overview["other_note_types"] == ["Базовий"]
