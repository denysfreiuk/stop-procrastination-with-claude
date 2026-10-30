"""Plugin configuration.

Values come from environment variables (Claude Code fills them from the plugin's
userConfig), then from an optional .env file, then from defaults.
"""

from __future__ import annotations

import os
import re
import sys
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path

from .errors import CONFIGURE_HINT

DEFAULT_URL = "http://127.0.0.1:8765"
LEVELS = ("A1", "A2", "B1", "B2", "C1", "C2")
_TRUE = {"1", "true", "yes", "y", "on", "так"}
_FALSE = {"0", "false", "no", "n", "off", "ні"}


@dataclass(frozen=True)
class Config:
    anki_connect_url: str = DEFAULT_URL
    anki_connect_key: str | None = None
    root_deck: str | None = None
    explanation_language: str = "uk"
    english_level: str = "B1"
    english_goal: str = "C1"
    example_level: str = "B1-B2"
    max_cards_per_batch: int = 15
    promote_after_days: int = 3
    auto_sync: bool = True
    tts: bool = True
    tts_lang: str = "en_US"
    review_reminder: bool = True
    sound_on_stop: bool = False
    env_file: Path | None = None
    warnings: tuple[str, ...] = field(default=())

    def public_dict(self) -> dict:
        """Config without secrets, for showing to the user."""
        return {
            "root_deck": self.root_deck,
            "anki_connect_url": self.anki_connect_url,
            "anki_connect_key": "задано" if self.anki_connect_key else "не задано",
            "explanation_language": self.explanation_language,
            "english_level": self.english_level,
            "english_goal": self.english_goal,
            "example_level": self.example_level,
            "max_cards_per_batch": self.max_cards_per_batch,
            "promote_after_days": self.promote_after_days,
            "auto_sync": self.auto_sync,
            "tts": self.tts,
            "tts_lang": self.tts_lang,
            "review_reminder": self.review_reminder,
            "sound_on_stop": self.sound_on_stop,
            "env_file": str(self.env_file) if self.env_file else None,
            "warnings": list(self.warnings),
        }


def _is_set(value: str | None) -> bool:
    # An option the user never filled can reach us as an unsubstituted "${user_config.x}".
    return bool(value and value.strip() and not value.strip().startswith("${"))


def parse_env_file(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    for raw in path.read_text(encoding="utf-8-sig").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip().removeprefix("export ").strip()
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        values[key] = value
    return values


def user_config_dir() -> Path:
    if sys.platform == "win32":
        return Path(os.environ.get("APPDATA", Path.home() / "AppData" / "Roaming")) / "anki-claude"
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / "anki-claude"
    return Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config")) / "anki-claude"


def find_env_file(environ: Mapping[str, str]) -> Path | None:
    explicit = environ.get("ANKI_CLAUDE_ENV_FILE")
    if _is_set(explicit):
        return Path(explicit)
    candidate = user_config_dir() / ".env"
    return candidate if candidate.is_file() else None


def normalize_root_deck(value: str) -> str:
    parts = [part.strip() for part in value.split("::")]
    return "::".join(part for part in parts if part)


def load_config(environ: Mapping[str, str] | None = None) -> Config:
    environ = os.environ if environ is None else environ
    warnings: list[str] = []

    env_file = find_env_file(environ)
    file_values: dict[str, str] = {}
    if env_file is not None:
        try:
            file_values = parse_env_file(env_file)
        except OSError as error:
            warnings.append(f"Не вдалося прочитати {env_file}: {error}")

    def get(key: str) -> str | None:
        value = environ.get(key)
        if _is_set(value):
            return value.strip()
        value = file_values.get(key)
        return value.strip() if _is_set(value) else None

    def get_int(key: str, default: int, low: int, high: int) -> int:
        raw = get(key)
        if raw is None:
            return default
        try:
            value = int(float(raw))
        except ValueError:
            warnings.append(f"{key}={raw!r} — не число, використовую {default}.")
            return default
        if not low <= value <= high:
            warnings.append(f"{key}={value} поза межами {low}–{high}, використовую {default}.")
            return default
        return value

    def get_bool(key: str, default: bool) -> bool:
        raw = get(key)
        if raw is None:
            return default
        if raw.lower() in _TRUE:
            return True
        if raw.lower() in _FALSE:
            return False
        warnings.append(f"{key}={raw!r} — не так/ні, використовую {default}.")
        return default

    def get_level(key: str, default: str) -> str:
        raw = get(key)
        if raw is None:
            return default
        if raw.upper() not in LEVELS:
            warnings.append(f"{key}={raw!r} — невідомий рівень, використовую {default}.")
            return default
        return raw.upper()

    tts_lang = (get("ANKI_TTS_LANG") or "en_US").replace("-", "_")
    if not re.fullmatch(r"[a-z]{2}_[A-Za-z]{2}", tts_lang):
        warnings.append(f"ANKI_TTS_LANG={tts_lang!r} — очікую формат en_US, використовую en_US.")
        tts_lang = "en_US"
    tts_lang = tts_lang[:3].lower() + tts_lang[3:].upper()

    root_deck = get("ANKI_ROOT_DECK")
    if root_deck is not None:
        root_deck = normalize_root_deck(root_deck) or None
    if root_deck is None:
        warnings.append(f"Не задано кореневу колоду (root_deck). {CONFIGURE_HINT}")

    url = (get("ANKI_CONNECT_URL") or DEFAULT_URL).rstrip("/")
    if not url.startswith(("http://", "https://")):
        warnings.append(f"ANKI_CONNECT_URL={url!r} без http://, використовую {DEFAULT_URL}.")
        url = DEFAULT_URL

    return Config(
        anki_connect_url=url,
        anki_connect_key=get("ANKI_CONNECT_KEY"),
        root_deck=root_deck,
        explanation_language=get("ANKI_EXPLANATION_LANGUAGE") or "uk",
        english_level=get_level("ANKI_ENGLISH_LEVEL", "B1"),
        english_goal=get_level("ANKI_ENGLISH_GOAL", "C1"),
        example_level=get("ANKI_EXAMPLE_LEVEL") or "B1-B2",
        max_cards_per_batch=get_int("ANKI_MAX_CARDS_PER_BATCH", 15, 1, 50),
        promote_after_days=get_int("ANKI_PROMOTE_AFTER_DAYS", 3, 1, 60),
        auto_sync=get_bool("ANKI_AUTO_SYNC", True),
        tts=get_bool("ANKI_TTS", True),
        tts_lang=tts_lang,
        review_reminder=get_bool("ANKI_REVIEW_REMINDER", True),
        sound_on_stop=get_bool("ANKI_SOUND_ON_STOP", False),
        env_file=env_file,
        warnings=tuple(warnings),
    )
