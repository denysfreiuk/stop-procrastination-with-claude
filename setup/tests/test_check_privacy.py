from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import check_privacy as cp  # noqa: E402

BOT_TOKEN = "123456789:" + "A" * 35
GITHUB_TOKEN = "ghp_" + "a" * 36


class PathRules(unittest.TestCase):
    def test_vault_template_is_allowed(self) -> None:
        for path in (
            "obsidian/Dashboard.md",
            "obsidian/Звички.md",
            "obsidian/CLAUDE.md",
            "obsidian/Templates/Daily.md",
            "obsidian/.obsidian/daily-notes.json",
            "obsidian/Journal/Daily/.gitkeep",
            "obsidian/Learning/.gitkeep",
        ):
            self.assertIsNone(cp.path_problem(path), path)

    def test_personal_notes_are_blocked(self) -> None:
        for path in (
            "obsidian/Journal/Daily/2026-10-30.md",
            "obsidian/Journal/Weekly/2026-W44.md",
            "obsidian/Inbox/idea.md",
            "obsidian/Learning/ML/notes.md",
            "obsidian/Нова папка/нотатка.md",
            "obsidian/.obsidian/workspace.json",
            "obsidian/attachment.png",
        ):
            self.assertIsNotNone(cp.path_problem(path), path)

    def test_secrets_and_bot_data_are_blocked(self) -> None:
        for path in (".env", ".env.local", "telegram-bot/.env", "telegram-bot/data/state.json", "bot.log"):
            self.assertIsNotNone(cp.path_problem(path), path)

    def test_ordinary_files_are_allowed(self) -> None:
        for path in (".env.example", "README.md", "telegram-bot/src/bot.py", "claude-anki/README.md"):
            self.assertIsNone(cp.path_problem(path), path)


class ContentRules(unittest.TestCase):
    def test_token_formats_are_found(self) -> None:
        self.assertEqual(cp.content_problems(f"token = {BOT_TOKEN}", {}), ["токен Telegram-бота"])
        self.assertEqual(cp.content_problems(GITHUB_TOKEN, {}), ["токен GitHub"])

    def test_hashes_and_plain_text_pass(self) -> None:
        self.assertEqual(cp.content_problems("sha256:" + "ab" * 32 + "\nчас 12:30\n", {}), [])

    def test_local_values_are_found_and_stay_unprinted(self) -> None:
        private = {"значення TELEGRAM_USER_ID з .env": "4242424242"}
        problems = cp.check(["a.md"], lambda _: b"id: 4242424242", private)
        self.assertEqual(problems, ["a.md: значення TELEGRAM_USER_ID з .env"])

    def test_binary_files_are_skipped(self) -> None:
        self.assertEqual(cp.check(["a.png"], lambda _: b"\0" + BOT_TOKEN.encode(), {}), [])

    def test_blocked_path_is_reported_without_reading_it(self) -> None:
        def unreadable(path: str) -> bytes:
            raise AssertionError(path)

        self.assertEqual(cp.check([".env"], unreadable, {}), [".env: файл із секретами"])


class EnvFile(unittest.TestCase):
    def test_comments_quotes_and_missing_file(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / ".env"
            self.assertEqual(cp.read_env_file(path), {})
            path.write_text('# TELEGRAM_USER_ID=1\nTELEGRAM_USER_ID="77"\nEMPTY=\n', encoding="utf-8")
            self.assertEqual(cp.read_env_file(path), {"TELEGRAM_USER_ID": "77", "EMPTY": ""})


if __name__ == "__main__":
    unittest.main()
