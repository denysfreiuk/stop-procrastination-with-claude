"""Settings from the repository's single .env file."""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from datetime import time
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from .commands import CommandError, parse_clock
from .files import atomic_write

ROOT = Path(__file__).resolve().parents[3]
DEFAULT_REMINDER = "20:00"
DEFAULT_VAULT = "obsidian"


class ConfigError(Exception):
    """The message tells the user what to fix in .env."""


@dataclass(frozen=True)
class Config:
    token: str
    user_id: int
    timezone: ZoneInfo
    reminder_time: time
    vault: Path
    env_file: Path


def env_file_path() -> Path:
    return Path(os.environ.get("DISCIPLINE_ENV_FILE") or ROOT / ".env")


def parse_env_file(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    for raw in path.read_text(encoding="utf-8-sig").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        values[key.strip()] = value
    return values


def load_config(path: Path | None = None) -> Config:
    path = path or env_file_path()
    if not path.is_file():
        raise ConfigError(f"Немає файлу {path}. Запусти setup або скопіюй .env.example у .env.")
    values = parse_env_file(path)

    token = values.get("TELEGRAM_BOT_TOKEN", "")
    if not token:
        raise ConfigError(f"Заповни TELEGRAM_BOT_TOKEN у {path} (токен дає @BotFather).")
    user_id = values.get("TELEGRAM_USER_ID", "")
    if not user_id.isdigit():
        raise ConfigError(f"Заповни TELEGRAM_USER_ID у {path} (свій ID покаже @userinfobot).")

    zone = values.get("TIMEZONE") or "Europe/Kyiv"
    try:
        timezone = ZoneInfo(zone)
    except (ZoneInfoNotFoundError, ValueError):
        raise ConfigError(f"Невідомий часовий пояс TIMEZONE={zone}.") from None

    try:
        reminder_time = parse_clock(values.get("REMINDER_TIME") or DEFAULT_REMINDER)
    except CommandError:
        raise ConfigError("REMINDER_TIME має бути у форматі ГГ:ХХ, наприклад 20:00.") from None

    vault = Path(values.get("VAULT_PATH") or DEFAULT_VAULT)
    if not vault.is_absolute():
        vault = path.parent / vault
    if not vault.is_dir():
        raise ConfigError(f"Не знайдено vault: {vault}. Перевір VAULT_PATH у {path}.")

    return Config(token, int(user_id), timezone, reminder_time, vault, path)


def set_env_value(path: Path, key: str, value: str) -> None:
    """Change one line and leave the comments and every other setting alone."""
    text = path.read_bytes().decode("utf-8")
    line = f"{key}={value}"
    pattern = re.compile(rf"^{re.escape(key)}=.*?(?=\r?$)", re.MULTILINE)
    if pattern.search(text):
        text = pattern.sub(lambda _: line, text, count=1)
    else:
        text = f"{text.rstrip()}\n{line}\n"
    atomic_write(path, text.encode("utf-8"))
