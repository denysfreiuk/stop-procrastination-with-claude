from __future__ import annotations

import plistlib
import shutil
import subprocess
import sys
import tempfile
import unittest
import xml.etree.ElementTree as ElementTree
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import autostart  # noqa: E402
import setup  # noqa: E402

GOOD_TOKEN = "123456789:" + "A" * 35
EXAMPLE = """# Секція

# --- Telegram ---

# Токен бота.
TELEGRAM_BOT_TOKEN=
# Твій ID.
TELEGRAM_USER_ID=

# Часовий пояс.
TIMEZONE=Europe/Kyiv
"""


def completed(stdout: str = "", returncode: int = 0) -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess([], returncode, stdout, "")


class EnvFile(unittest.TestCase):
    def test_read_handles_comments_quotes_and_windows_endings(self) -> None:
        text = '# TIMEZONE=UTC\r\nTIMEZONE="Europe/Kyiv"\r\nEMPTY=\r\n'
        self.assertEqual(setup.read_env(text), {"TIMEZONE": "Europe/Kyiv", "EMPTY": ""})

    def test_set_values_changes_only_given_keys(self) -> None:
        updated = setup.set_env_values(EXAMPLE, {"TELEGRAM_USER_ID": "42"})
        self.assertEqual(updated, EXAMPLE.replace("TELEGRAM_USER_ID=\n", "TELEGRAM_USER_ID=42\n"))

    def test_set_values_keeps_windows_endings(self) -> None:
        self.assertEqual(setup.set_env_values("A=1\r\nB=2\r\n", {"A": "9"}), "A=9\r\nB=2\r\n")

    def test_set_values_with_backslashes_stays_literal(self) -> None:
        self.assertEqual(setup.set_env_values("VAULT_PATH=x\n", {"VAULT_PATH": r"C:\new\1"}), "VAULT_PATH=C:\\new\\1\n")

    def test_new_settings_arrive_with_their_comments(self) -> None:
        current = "TELEGRAM_BOT_TOKEN=secret\nTELEGRAM_USER_ID=42\n"
        text, added = setup.add_missing_settings(current, EXAMPLE)
        self.assertEqual(added, ["TIMEZONE"])
        self.assertEqual(text, f"{current}\n# Часовий пояс.\nTIMEZONE=Europe/Kyiv\n")

    def test_nothing_new_changes_nothing(self) -> None:
        self.assertEqual(setup.add_missing_settings(EXAMPLE, EXAMPLE), (EXAMPLE, []))


class Questions(unittest.TestCase):
    def question(self, key: str) -> setup.Question:
        return next(item for item in setup.QUESTIONS if item.key == key)

    def test_every_question_has_a_line_in_the_example(self) -> None:
        keys = setup.read_env(setup.ENV_EXAMPLE.read_text(encoding="utf-8"))
        for question in setup.QUESTIONS:
            self.assertIn(question.key, keys)

    def test_enter_keeps_the_current_value(self) -> None:
        self.assertEqual(setup.ask(self.question("TIMEZONE"), "Europe/Kyiv", lambda _: ""), "Europe/Kyiv")

    def test_a_bad_answer_is_asked_again(self) -> None:
        answers = iter(["25:00", "21:30"])
        with mock.patch.object(setup, "say"):
            self.assertEqual(setup.ask(self.question("REMINDER_TIME"), "", lambda _: next(answers)), "21:30")

    def test_the_token_is_never_shown_in_the_prompt(self) -> None:
        prompts = []

        def read(prompt: str) -> str:
            prompts.append(prompt)
            return ""

        setup.ask(self.question("TELEGRAM_BOT_TOKEN"), GOOD_TOKEN, read)
        self.assertNotIn(GOOD_TOKEN, prompts[0])
        self.assertIn("вже задано", prompts[0])

    def test_validators(self) -> None:
        cases = {
            "TELEGRAM_BOT_TOKEN": ([GOOD_TOKEN], ["", "abc", "123:short"]),
            "TELEGRAM_USER_ID": (["987"], ["", "id", "-1"]),
            "TIMEZONE": (["Europe/Kyiv", "UTC", "America/Argentina/Salta"], ["", "Kyiv"]),
            "REMINDER_TIME": (["20:00", "8:05"], ["", "24:00", "20"]),
            "ANKI_EXPLANATION_LANGUAGE": (["uk"], ["", "ukr"]),
            "ANKI_ROOT_DECK": (["Den"], [""]),
        }
        for key, (good, bad) in cases.items():
            for value in good:
                self.assertTrue(self.question(key).valid(value), value)
            for value in bad:
                self.assertFalse(self.question(key).valid(value), value)


class Plugin(unittest.TestCase):
    def fake_claude(self, marketplaces: list[dict], plugins: list[dict]):
        calls: list[list[str]] = []

        def fake(command: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
            calls.append(command[1:])
            if command[1:] == ["plugin", "marketplace", "list", "--json"]:
                return completed(setup.json.dumps(marketplaces))
            if command[1:] == ["plugin", "list", "--json"]:
                return completed(setup.json.dumps(plugins))
            return completed()

        return fake, calls

    def install(self, marketplaces: list[dict], plugins: list[dict]) -> list[list[str]]:
        fake, calls = self.fake_claude(marketplaces, plugins)
        with mock.patch.object(setup, "run", fake):
            setup.install_plugin("claude", {"ANKI_ROOT_DECK": "Study"})
        return [call for call in calls if "--json" not in call]

    def test_first_install(self) -> None:
        calls = self.install([], [])
        self.assertEqual(calls[0], ["plugin", "marketplace", "add", str(setup.ROOT)])
        self.assertEqual(calls[1][:3], ["plugin", "install", setup.PLUGIN])
        self.assertIn("root_deck=Study", calls[1])
        self.assertIn(f"env_file={setup.ENV_FILE}", calls[1])

    def test_repeat_install_updates_and_keeps_the_marketplace(self) -> None:
        calls = self.install(
            [{"name": setup.MARKETPLACE, "path": str(setup.ROOT)}], [{"id": setup.PLUGIN}]
        )
        self.assertEqual(calls[0], ["plugin", "marketplace", "update", setup.MARKETPLACE])
        self.assertEqual(calls[1], ["plugin", "update", setup.PLUGIN])
        self.assertEqual(calls[2], ["plugin", "configure", setup.PLUGIN, "--values-stdin"])

    def test_a_moved_folder_replaces_the_marketplace(self) -> None:
        calls = self.install([{"name": setup.MARKETPLACE, "path": "/old/place"}], [])
        self.assertEqual(calls[0], ["plugin", "marketplace", "remove", setup.MARKETPLACE])
        self.assertEqual(calls[1], ["plugin", "marketplace", "add", str(setup.ROOT)])


class Commands(unittest.TestCase):
    def test_update_stops_on_local_changes(self) -> None:
        def fake(command: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
            self.assertNotIn("pull", command)
            return completed(" M obsidian/Dashboard.md\n")

        with mock.patch.object(setup, "run", fake), mock.patch.object(setup, "say") as said:
            self.assertEqual(setup.update(SimpleNamespace(after_pull=False)), 1)
        self.assertIn("obsidian/Dashboard.md", str(said.call_args_list))

    def test_uninstall_asks_first(self) -> None:
        with mock.patch("builtins.input", return_value="ні"), mock.patch.object(setup, "say"), mock.patch.object(
            autostart, "uninstall"
        ) as removed:
            self.assertEqual(setup.uninstall(SimpleNamespace(yes=False)), 0)
        removed.assert_not_called()

    def test_anki_being_closed_is_not_a_failure(self) -> None:
        with mock.patch.object(setup, "anki_version", return_value=None), mock.patch.object(setup, "say") as said:
            setup.check_anki({})
        self.assertIn("2055492159", str(said.call_args_list))


class Autostart(unittest.TestCase):
    BOT = Path("/home/я/discipline & co/telegram-bot")

    def test_windows_task_stays_alive_and_escapes_paths(self) -> None:
        xml = autostart.windows_task_xml(Path(r"C:\Py & Co\pythonw.exe"), self.BOT, r"PC\Ім'я")
        root = ElementTree.fromstring(xml.encode("utf-16"))
        namespace = {"t": "http://schemas.microsoft.com/windows/2004/02/mit/task"}

        def value(path: str) -> str:
            return root.find(path, namespace).text

        self.assertEqual(value("t:Settings/t:ExecutionTimeLimit"), "PT0S")
        self.assertEqual(value("t:Settings/t:DisallowStartIfOnBatteries"), "false")
        self.assertEqual(value("t:Settings/t:StopIfGoingOnBatteries"), "false")
        self.assertEqual(value("t:Settings/t:MultipleInstancesPolicy"), "IgnoreNew")
        self.assertEqual(value("t:Actions/t:Exec/t:Command"), r"C:\Py & Co\pythonw.exe")
        self.assertEqual(value("t:Actions/t:Exec/t:Arguments"), "launch.py")
        self.assertEqual(value("t:Triggers/t:LogonTrigger/t:UserId"), r"PC\Ім'я")

    def test_launchd_plist(self) -> None:
        data = plistlib.loads(autostart.launchd_plist(["/bin/uv", "run"], self.BOT))
        self.assertEqual(data["Label"], autostart.LAUNCHD_LABEL)
        self.assertEqual(data["ProgramArguments"], ["/bin/uv", "run"])
        self.assertTrue(data["RunAtLoad"] and data["KeepAlive"])

    @unittest.skipUnless(sys.platform == "darwin", "plutil exists on macOS only")
    def test_launchd_plist_passes_plutil(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "bot.plist"
            path.write_bytes(autostart.launchd_plist(["/bin/uv", "run"], self.BOT))
            subprocess.run(["plutil", "-lint", str(path)], check=True, capture_output=True)

    def test_systemd_unit_quotes_paths(self) -> None:
        unit = autostart.systemd_unit(autostart.bot_command("/bin/uv", self.BOT), self.BOT)
        self.assertIn(f"--directory '{self.BOT}'", unit)
        self.assertIn("Restart=always", unit)
        self.assertIn("WantedBy=default.target", unit)

    @unittest.skipUnless(shutil.which("systemd-analyze"), "needs systemd")
    def test_systemd_unit_passes_verification(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / autostart.SYSTEMD_UNIT
            path.write_text(autostart.systemd_unit(["/bin/true"], Path("/tmp")), encoding="utf-8")
            result = subprocess.run(["systemd-analyze", "verify", "--user", str(path)], capture_output=True, text=True)
            self.assertNotIn("Failed", result.stderr)

    def test_mac_folders_launchd_cannot_read(self) -> None:
        home = Path("/Users/я")
        self.assertEqual(autostart.mac_private_folder(home / "Desktop" / "discipline", home), "Desktop")
        self.assertEqual(
            autostart.mac_private_folder(home / "Library" / "Mobile Documents" / "x", home), "Library/Mobile Documents"
        )
        self.assertIsNone(autostart.mac_private_folder(home / "discipline", home))


if __name__ == "__main__":
    unittest.main()
