from __future__ import annotations

from pathlib import Path

from anki_claude.config import DEFAULT_URL, load_config


def test_defaults_and_missing_root_deck_warning() -> None:
    config = load_config({})
    assert config.anki_connect_url == DEFAULT_URL
    assert config.root_deck is None
    assert config.max_cards_per_batch == 15
    assert config.promote_after_days == 3
    assert config.auto_sync is True
    assert any("root_deck" in warning for warning in config.warnings)


def test_unsubstituted_user_config_placeholders_count_as_unset() -> None:
    config = load_config({"ANKI_ROOT_DECK": "${user_config.root_deck}", "ANKI_CONNECT_KEY": "${user_config.anki_connect_key}"})
    assert config.root_deck is None
    assert config.anki_connect_key is None


def test_root_deck_is_normalized() -> None:
    assert load_config({"ANKI_ROOT_DECK": " Den :: "}).root_deck == "Den"
    assert load_config({"ANKI_ROOT_DECK": "Study::Den"}).root_deck == "Study::Den"


def test_numbers_bools_and_levels_are_validated() -> None:
    config = load_config(
        {
            "ANKI_ROOT_DECK": "Den",
            "ANKI_MAX_CARDS_PER_BATCH": "500",
            "ANKI_PROMOTE_AFTER_DAYS": "5",
            "ANKI_AUTO_SYNC": "ні",
            "ANKI_SOUND_ON_STOP": "так",
            "ANKI_ENGLISH_LEVEL": "b2",
            "ANKI_ENGLISH_GOAL": "Z9",
        }
    )
    assert config.max_cards_per_batch == 15
    assert config.promote_after_days == 5
    assert config.auto_sync is False
    assert config.sound_on_stop is True
    assert config.english_level == "B2"
    assert config.english_goal == "C1"
    assert len(config.warnings) == 2


def test_env_file_fills_gaps_but_environment_wins(tmp_path: Path) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text('# comment\nANKI_ROOT_DECK="FromFile"\nANKI_PROMOTE_AFTER_DAYS=7\n', encoding="utf-8")
    config = load_config({"ANKI_CLAUDE_ENV_FILE": str(env_file), "ANKI_PROMOTE_AFTER_DAYS": "4"})
    assert config.root_deck == "FromFile"
    assert config.promote_after_days == 4
    assert config.env_file == env_file


def test_public_dict_hides_the_key() -> None:
    public = load_config({"ANKI_ROOT_DECK": "Den", "ANKI_CONNECT_KEY": "secret"}).public_dict()
    assert "secret" not in str(public)
    assert public["anki_connect_key"] == "задано"
