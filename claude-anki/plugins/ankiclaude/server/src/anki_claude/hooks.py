"""Hook logic: release delayed cards at session start, remind about reviews after a reply.

Hooks print at most one JSON object with a systemMessage (shown to the user) and stay
silent when Anki is closed, so ordinary coding sessions are not disturbed.
"""

from __future__ import annotations

import asyncio
import json
import os
import subprocess
import sys
import time
from collections.abc import MutableMapping
from pathlib import Path
from typing import Any

from .anki import Anki
from .ankiconnect import AnkiConnect
from .config import Config, load_config
from .errors import AnkiError, AnkiNotRunningError, AnkiTimeoutError
from .notes import PENDING_FORMS, PENDING_PRODUCTION

PROMOTE_EVERY_SECONDS = 3 * 3600
REMIND_EVERY_SECONDS = 3 * 3600

# userConfig keys as Claude Code exports them to hooks (CLAUDE_PLUGIN_OPTION_<KEY>) → our env names.
OPTION_ENV = {
    "ROOT_DECK": "ANKI_ROOT_DECK",
    "ANKI_CONNECT_URL": "ANKI_CONNECT_URL",
    "ANKI_CONNECT_KEY": "ANKI_CONNECT_KEY",
    "EXPLANATION_LANGUAGE": "ANKI_EXPLANATION_LANGUAGE",
    "ENGLISH_LEVEL": "ANKI_ENGLISH_LEVEL",
    "ENGLISH_GOAL": "ANKI_ENGLISH_GOAL",
    "EXAMPLE_LEVEL": "ANKI_EXAMPLE_LEVEL",
    "MAX_CARDS_PER_BATCH": "ANKI_MAX_CARDS_PER_BATCH",
    "PROMOTE_AFTER_DAYS": "ANKI_PROMOTE_AFTER_DAYS",
    "AUTO_SYNC": "ANKI_AUTO_SYNC",
    "TTS": "ANKI_TTS",
    "TTS_LANG": "ANKI_TTS_LANG",
    "REVIEW_REMINDER": "ANKI_REVIEW_REMINDER",
    "SOUND_ON_STOP": "ANKI_SOUND_ON_STOP",
}


def apply_plugin_options(environ: MutableMapping[str, str]) -> None:
    for option, target in OPTION_ENV.items():
        value = environ.get(f"CLAUDE_PLUGIN_OPTION_{option}")
        if value is not None and not environ.get(target):
            environ[target] = value


class State:
    """Small JSON file in the plugin's data directory remembering when hooks last acted."""

    def __init__(self, path: Path) -> None:
        self.path = path
        try:
            self.data: dict[str, float] = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            self.data = {}

    def due(self, key: str, every: float) -> bool:
        return time.time() - self.data.get(key, 0) >= every

    def mark(self, key: str) -> None:
        self.data[key] = time.time()
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.path.write_text(json.dumps(self.data), encoding="utf-8")
        except OSError:
            pass


def _anki(config: Config) -> Anki:
    # Hooks must never hang a session: fail fast when Anki is busy or closed.
    return Anki(config, AnkiConnect(config.anki_connect_url, config.anki_connect_key, timeout=8, connect_timeout=1.5))


async def session_start(config: Config, state: State) -> dict[str, Any] | None:
    if not state.due("promote", PROMOTE_EVERY_SECONDS):
        return None
    anki = _anki(config)
    try:
        pending = await anki.client.invoke(
            "findCards", query=f'deck:"{config.root_deck}" (tag:{PENDING_PRODUCTION} OR tag:{PENDING_FORMS}) is:suspended'
        )
        if not pending:
            state.mark("promote")
            return None
        report = await anki.promote()
    except (AnkiNotRunningError, AnkiTimeoutError):
        return None  # Anki is closed: try again next session
    finally:
        await anki.client.aclose()
    status = report.get("status")
    if status == "deferred":
        return {"systemMessage": "Anki&Claude: ти зараз повторюєш картки — розморожування відкладено. Потім: /anki-promote"}
    state.mark("promote")
    if status == "sync_failed":
        return {"systemMessage": f"Anki&Claude: {report['message']}"}
    if report.get("promoted"):
        return {"systemMessage": f"📚 Anki&Claude: {report['message']}"}
    return None


async def stop(config: Config, state: State) -> dict[str, Any] | None:
    if not config.review_reminder or not state.due("remind", REMIND_EVERY_SECONDS):
        return None
    anki = _anki(config)
    try:
        stats = await anki.client.invoke("getDeckStats", decks=[config.root_deck])
    except AnkiError:
        return None
    finally:
        await anki.client.aclose()
    row = next(iter(stats.values()), None) if isinstance(stats, dict) else None
    if not row:
        return None
    new, learning, review = row.get("new_count", 0), row.get("learn_count", 0), row.get("review_count", 0)
    state.mark("remind")
    if new + learning + review == 0:
        return None
    return {
        "systemMessage": f"📚 У {config.root_deck} чекає {new + learning + review} карток: "
        f"нових {new}, у навчанні {learning}, на повторення {review}."
    }


def play_sound() -> None:
    try:
        if sys.platform == "win32":
            import winsound

            winsound.MessageBeep(winsound.MB_ICONASTERISK)
        elif sys.platform == "darwin":
            subprocess.Popen(["afplay", "/System/Library/Sounds/Glass.aiff"])
        else:
            sound = "/usr/share/sounds/freedesktop/stereo/complete.oga"
            if os.path.exists(sound):
                subprocess.Popen(["paplay", sound], stderr=subprocess.DEVNULL)
            else:
                sys.stderr.write("\a")
    except Exception:  # noqa: BLE001 - a missing sound must never break a hook
        pass


def run(event: str, data_dir: Path) -> int:
    apply_plugin_options(os.environ)
    config = load_config()
    if not config.root_deck:
        return 0
    state = State(data_dir / "hook-state.json")
    if event == "stop" and config.sound_on_stop:
        play_sound()
    handler = session_start if event == "session-start" else stop
    output = asyncio.run(handler(config, state))
    if output:
        print(json.dumps(output, ensure_ascii=False))
    return 0
