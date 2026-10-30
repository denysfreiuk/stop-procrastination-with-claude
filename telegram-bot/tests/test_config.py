from __future__ import annotations

from datetime import time
from pathlib import Path

import pytest

from discipline_bot.config import ConfigError, load_config, set_env_value

GOOD = "TELEGRAM_BOT_TOKEN=123:abc\nTELEGRAM_USER_ID=42\n"


def write(tmp_path: Path, text: str) -> Path:
    (tmp_path / "obsidian").mkdir(exist_ok=True)
    path = tmp_path / ".env"
    path.write_text(text, encoding="utf-8")
    return path


def test_defaults_and_relative_vault(tmp_path: Path) -> None:
    config = load_config(write(tmp_path, GOOD))
    assert config.token == "123:abc" and config.user_id == 42
    assert config.reminder_time == time(20, 0)
    assert config.timezone.key == "Europe/Kyiv"
    assert config.vault == tmp_path / "obsidian"


def test_values_from_the_file(tmp_path: Path) -> None:
    other = tmp_path / "other"
    other.mkdir()
    text = f'{GOOD}TIMEZONE=Europe/Warsaw\nREMINDER_TIME=21:30\nVAULT_PATH="{other}"\n'
    config = load_config(write(tmp_path, text))
    assert config.timezone.key == "Europe/Warsaw"
    assert config.reminder_time == time(21, 30)
    assert config.vault == other


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("", "TELEGRAM_BOT_TOKEN"),
        ("TELEGRAM_BOT_TOKEN=1:a\n", "TELEGRAM_USER_ID"),
        ("TELEGRAM_BOT_TOKEN=1:a\nTELEGRAM_USER_ID=me\n", "TELEGRAM_USER_ID"),
        (f"{GOOD}TIMEZONE=Mars/Base\n", "TIMEZONE"),
        (f"{GOOD}REMINDER_TIME=вечір\n", "REMINDER_TIME"),
        (f"{GOOD}VAULT_PATH=gone\n", "VAULT_PATH"),
    ],
)
def test_mistakes_name_the_setting(tmp_path: Path, text: str, expected: str) -> None:
    with pytest.raises(ConfigError, match=expected):
        load_config(write(tmp_path, text))


def test_missing_file(tmp_path: Path) -> None:
    with pytest.raises(ConfigError, match="setup"):
        load_config(tmp_path / ".env")


def test_set_env_value_changes_one_line_only(env_file: Path) -> None:
    set_env_value(env_file, "REMINDER_TIME", "21:30")
    assert env_file.read_text(encoding="utf-8") == "# Час нагадування\nREMINDER_TIME=21:30\n\n# Інше\nTIMEZONE=Europe/Kyiv\n"


def test_set_env_value_keeps_windows_line_endings(tmp_path: Path) -> None:
    path = tmp_path / ".env"
    path.write_bytes(b"A=1\r\nREMINDER_TIME=20:00\r\nB=2\r\n")
    set_env_value(path, "REMINDER_TIME", "21:30")
    assert path.read_bytes() == b"A=1\r\nREMINDER_TIME=21:30\r\nB=2\r\n"


def test_set_env_value_adds_a_missing_key(tmp_path: Path) -> None:
    path = tmp_path / ".env"
    path.write_text("A=1", encoding="utf-8")
    set_env_value(path, "REMINDER_TIME", "21:30")
    assert path.read_text(encoding="utf-8") == "A=1\nREMINDER_TIME=21:30\n"
