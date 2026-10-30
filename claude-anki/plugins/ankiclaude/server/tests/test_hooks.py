from __future__ import annotations

from pathlib import Path

import pytest

from anki_claude import hooks
from anki_claude.anki import Anki
from anki_claude.ankiconnect import AnkiConnect
from anki_claude.config import load_config

from .conftest import URL
from .fake_ankiconnect import FakeAnkiConnect
from .test_notes import vocab


@pytest.fixture
def wired(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    """Point the hooks at a fake AnkiConnect and a temporary state file."""

    def wire(fake: FakeAnkiConnect, **env: str):
        config = load_config({"ANKI_ROOT_DECK": "Den", **env})
        monkeypatch.setattr(hooks, "_anki", lambda cfg: Anki(cfg, AnkiConnect(URL, transport=fake.transport())))
        return config, hooks.State(tmp_path / "hook-state.json")

    return wire


def test_plugin_options_become_our_env_names() -> None:
    env = {"CLAUDE_PLUGIN_OPTION_ROOT_DECK": "Den", "CLAUDE_PLUGIN_OPTION_TTS": "false", "ANKI_AUTO_SYNC": "true",
           "CLAUDE_PLUGIN_OPTION_AUTO_SYNC": "false"}
    hooks.apply_plugin_options(env)
    assert env["ANKI_ROOT_DECK"] == "Den" and env["ANKI_TTS"] == "false"
    assert env["ANKI_AUTO_SYNC"] == "true", "an explicit env value wins"


def test_state_survives_restarts(tmp_path: Path) -> None:
    state = hooks.State(tmp_path / "s.json")
    assert state.due("remind", 60)
    state.mark("remind")
    assert not hooks.State(tmp_path / "s.json").due("remind", 60)


async def test_session_start_is_silent_without_waiting_cards(fake: FakeAnkiConnect, wired, make_anki) -> None:
    config, state = wired(fake)
    await make_anki(fake).decks.setup()
    assert await hooks.session_start(config, state) is None
    assert fake.syncs == 0, "no waiting cards, no sync"
    assert not state.due("promote", 60)


async def test_session_start_reports_released_cards(fake: FakeAnkiConnect, wired, make_anki) -> None:
    anki = make_anki(fake, ANKI_AUTO_SYNC="false")
    await anki.decks.setup()
    await anki.note_types.ensure()
    note_id = (await anki.add_notes([vocab()]))["added"][0]["note_id"]
    fake.card(note_id, 0)["ivl"] = 5
    config, state = wired(fake)
    output = await hooks.session_start(config, state)
    assert output["systemMessage"].startswith("📚 Anki&Claude: Розморожено 1: reluctant (UA→EN)")
    assert fake.syncs == 2
    assert await hooks.session_start(config, state) is None, "not again within the interval"


async def test_session_start_explains_a_failed_sync(fake: FakeAnkiConnect, wired, make_anki) -> None:
    anki = make_anki(fake, ANKI_AUTO_SYNC="false")
    await anki.decks.setup()
    await anki.note_types.ensure()
    await anki.add_notes([vocab()])
    fake.logged_in = False
    config, state = wired(fake)
    output = await hooks.session_start(config, state)
    assert "Нічого не розморожено" in output["systemMessage"]


async def test_hooks_stay_quiet_when_anki_is_closed(wired) -> None:
    config, state = wired(FakeAnkiConnect(running=False))
    assert await hooks.session_start(config, state) is None
    assert state.due("promote", 60), "try again next session"
    assert await hooks.stop(config, state) is None


async def test_stop_reminds_about_due_cards_at_most_every_few_hours(fake: FakeAnkiConnect, wired, make_anki) -> None:
    anki = make_anki(fake, ANKI_AUTO_SYNC="false")
    await anki.decks.setup()
    await anki.note_types.ensure()
    await anki.add_notes([vocab(), vocab("eager", Active="no")])
    config, state = wired(fake)
    output = await hooks.stop(config, state)
    assert output == {"systemMessage": "📚 У Den чекає 2 карток: нових 2, у навчанні 0, на повторення 0."}
    assert await hooks.stop(config, state) is None


async def test_stop_respects_the_reminder_option(fake: FakeAnkiConnect, wired) -> None:
    config, state = wired(fake, ANKI_REVIEW_REMINDER="false")
    assert await hooks.stop(config, state) is None
    assert fake.calls == []
