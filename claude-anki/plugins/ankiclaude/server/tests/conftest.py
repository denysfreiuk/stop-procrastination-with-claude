from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import pytest

from anki_claude import anki as anki_module
from anki_claude import config as config_module
from anki_claude.anki import Anki
from anki_claude.ankiconnect import AnkiConnect
from anki_claude.config import load_config

from .fake_ankiconnect import FakeAnkiConnect

URL = "http://127.0.0.1:8765"


@pytest.fixture(autouse=True)
def isolated(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    # Never read the developer's real ~/.config/anki-claude/.env, never wait between polls.
    monkeypatch.setattr(config_module, "user_config_dir", lambda: tmp_path / "config")
    monkeypatch.setattr(anki_module, "SYNC_POLL_INTERVAL", 0)


@pytest.fixture
def fake() -> FakeAnkiConnect:
    return FakeAnkiConnect()


@pytest.fixture
def make_anki() -> Callable[..., Anki]:
    def make(fake: FakeAnkiConnect, **env: str) -> Anki:
        config = load_config({"ANKI_ROOT_DECK": "Den", **env})
        return Anki(config, AnkiConnect(URL, config.anki_connect_key, transport=fake.transport()))

    return make
