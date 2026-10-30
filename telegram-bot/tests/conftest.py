from __future__ import annotations

import shutil
from collections.abc import Callable
from datetime import date, datetime, time
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from discipline_bot.assistant import Assistant, State
from discipline_bot.config import ROOT
from discipline_bot.journal import Journal

KYIV = ZoneInfo("Europe/Kyiv")
DAY = date(2026, 10, 30)
NOW = datetime(2026, 10, 30, 14, 32, tzinfo=KYIV)
ENV_TEXT = "# Час нагадування\nREMINDER_TIME=20:00\n\n# Інше\nTIMEZONE=Europe/Kyiv\n"


@pytest.fixture
def vault(tmp_path: Path) -> Path:
    """A temporary vault with the real template from the repository."""
    root = tmp_path / "vault"
    (root / "Templates").mkdir(parents=True)
    shutil.copy(ROOT / "obsidian" / "Templates" / "Daily.md", root / "Templates" / "Daily.md")
    return root


@pytest.fixture
def journal(vault: Path) -> Journal:
    return Journal(vault)


@pytest.fixture
def env_file(tmp_path: Path) -> Path:
    path = tmp_path / ".env"
    path.write_text(ENV_TEXT, encoding="utf-8")
    return path


@pytest.fixture
def make_assistant(journal: Journal, env_file: Path, tmp_path: Path) -> Callable[[], Assistant]:
    def make() -> Assistant:
        return Assistant(journal, State(tmp_path / "data" / "state.json"), time(20, 0), env_file)

    return make


@pytest.fixture
def assistant(make_assistant: Callable[[], Assistant]) -> Assistant:
    return make_assistant()
