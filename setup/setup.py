"""Set up the whole system on this computer.

uv run --python 3.14 setup/setup.py             install, or repeat with new answers
uv run --python 3.14 setup/setup.py update      git pull, dependencies, plugin, restart
uv run --python 3.14 setup/setup.py uninstall   remove autostart and the plugin

Only the standard library is used, and no virtual environment: Windows Smart App
Control blocks the launchers a venv contains. Personal data is never touched: notes,
.env and the bot's data stay in place through update and uninstall.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import urllib.error
import urllib.request
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import autostart  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
ENV_FILE = ROOT / ".env"
ENV_EXAMPLE = ROOT / ".env.example"
BOT_DIR = ROOT / "telegram-bot"
PLUGIN_SERVER = ROOT / "claude-anki" / "plugins" / "ankiclaude" / "server"
MARKETPLACE = "ankiclaude"
PLUGIN = "ankiclaude@ankiclaude"
ENV_LINE = re.compile(r"^([A-Z][A-Z0-9_]*)=([^\r\n]*)", re.MULTILINE)
TOKEN = re.compile(r"^\d{6,12}:[A-Za-z0-9_-]{30,}$")
NETWORK_TIMEOUT = 15


@dataclass(frozen=True)
class Question:
    key: str
    text: str
    valid: Callable[[str], bool]
    hint: str
    secret: bool = False


QUESTIONS = (
    Question("TELEGRAM_BOT_TOKEN", "Токен бота від @BotFather", lambda v: bool(TOKEN.match(v)),
             "Токен виглядає так: 123456789:AAE…", secret=True),
    Question("TELEGRAM_USER_ID", "Твій Telegram ID (покаже @userinfobot)", str.isdigit, "Це лише цифри."),
    Question("TIMEZONE", "Часовий пояс", lambda v: bool(re.fullmatch(r"UTC|[A-Za-z_]+(/[A-Za-z0-9_+-]+)+", v)),
             "Приклад: Europe/Kyiv"),
    Question("REMINDER_TIME", "Час вечірнього нагадування", lambda v: bool(re.fullmatch(r"([01]?\d|2[0-3]):[0-5]\d", v)),
             "Формат ГГ:ХХ, наприклад 20:00"),
    Question("ANKI_EXPLANATION_LANGUAGE", "Мова пояснень і підсумків", lambda v: bool(re.fullmatch(r"[a-z]{2}", v)),
             "Код мови, наприклад uk"),
    Question("ANKI_ROOT_DECK", "Коренева колода Anki", bool, "Назва не може бути порожньою."),
)


def say(text: str = "") -> None:
    print(text, flush=True)


def run(command: list[str], *, check: bool = True, stdin: str | None = None, env: Mapping[str, str] | None = None,
        cwd: Path = ROOT) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        command, input=stdin, capture_output=True, text=True, encoding="utf-8", errors="replace",
        check=check, cwd=cwd, env=None if env is None else {**os.environ, **env},
    )


def read_env(text: str) -> dict[str, str]:
    return {key: value.strip().strip("\"'") for key, value in ENV_LINE.findall(text)}


def set_env_values(text: str, values: Mapping[str, str]) -> str:
    """Fill in values and keep comments and every other line exactly as they are."""
    return ENV_LINE.sub(lambda match: f"{match[1]}={values[match[1]]}" if match[1] in values else match[0], text)


def add_missing_settings(current: str, example: str) -> tuple[str, list[str]]:
    """After an update: bring in new settings with their comments, leave the user's values alone."""
    known = read_env(current)
    blocks: list[str] = []
    added: list[str] = []
    comments: list[str] = []
    for line in example.splitlines():
        match = ENV_LINE.match(line)
        if line.startswith("#"):
            comments.append(line)
            continue
        if match and match[1] not in known:
            blocks.append("\n".join([*comments, line]))
            added.append(match[1])
        comments = []
    if not blocks:
        return current, []
    return "\n\n".join([current.rstrip(), *blocks]) + "\n", added


def write_env(text: str) -> None:
    ENV_FILE.write_text(text, encoding="utf-8", newline="\n")
    if os.name == "posix":
        ENV_FILE.chmod(0o600)


def telegram_bot_name(token: str) -> str | None:
    """The bot's username; None if Telegram rejects the token. Network trouble is not the token's fault."""
    try:
        with urllib.request.urlopen(f"https://api.telegram.org/bot{token}/getMe", timeout=NETWORK_TIMEOUT) as response:
            return json.load(response)["result"]["username"]
    except urllib.error.HTTPError:
        return None
    except OSError:
        return "?"


def ask(question: Question, current: str, read: Callable[[str], str] = input) -> str:
    shown = "вже задано" if question.secret and current else current
    prompt = f"{question.text}" + (f" [{shown}]" if shown else "") + ": "
    while True:
        answer = read(prompt).strip() or current
        if question.valid(answer):
            return answer
        say(f"  {question.hint}")


def configure(answer_questions: bool) -> dict[str, str]:
    """Create or update .env, and keep what is already there when Enter is pressed."""
    example = ENV_EXAMPLE.read_text(encoding="utf-8")
    text = ENV_FILE.read_text(encoding="utf-8") if ENV_FILE.is_file() else example
    values = read_env(text)
    if answer_questions:
        say("Натисни Enter, щоб лишити значення в дужках.")
        for question in QUESTIONS:
            while True:
                values[question.key] = ask(question, values.get(question.key, ""))
                if question.key != "TELEGRAM_BOT_TOKEN":
                    break
                name = telegram_bot_name(values[question.key])
                if name:
                    if name != "?":
                        say(f"  ✓ Бот @{name}")
                    break
                say("  Telegram не прийняв цей токен, перевір його в @BotFather.")
                values[question.key] = ""
    write_env(set_env_values(text, values))
    say(f"  ✓ Налаштування збережено в {ENV_FILE}")
    return values


def enable_commit_check() -> None:
    if (ROOT / ".git").exists():
        run(["git", "config", "core.hooksPath", ".githooks"], check=False)


def find_uv() -> str:
    uv = os.environ.get("UV") or shutil.which("uv")
    if not uv:
        raise SystemExit("Не знайдено uv. Встанови його: https://docs.astral.sh/uv/getting-started/installation/")
    return uv


def claude_config_dir() -> Path:
    return Path(os.environ.get("CLAUDE_CONFIG_DIR") or Path.home() / ".claude")


def install_dependencies(uv: str) -> bool:
    """Install what the bot and the plugin's server need, and check the bot's settings."""
    python = [uv, "run", "--quiet", "--no-project", "--python", "3.14"]
    result = run([*python, "--directory", str(BOT_DIR), "python", "launch.py", "--check"], check=False)
    if result.returncode != 0:
        say(f"  ✗ Бот: {(result.stdout or result.stderr).strip()}")
        return False
    say("  ✓ Бот готовий")
    plugin_data = claude_config_dir() / "plugins" / "data" / "ankiclaude-ankiclaude"
    result = run(
        [*python, "--directory", str(PLUGIN_SERVER), "python", "-c", "import launch; launch.bootstrap()"],
        check=False, env={"CLAUDE_PLUGIN_DATA": str(plugin_data)},
    )
    if result.returncode != 0:
        say(f"  ✗ Сервер плагіна: {result.stderr.strip()}")
        return False
    say("  ✓ Сервер плагіна готовий")
    return True


def same_path(first: str, second: Path) -> bool:
    return os.path.normcase(os.path.normpath(first)) == os.path.normcase(os.path.normpath(str(second)))


def claude_json(claude: str, *args: str) -> list[dict]:
    return json.loads(run([claude, "plugin", *args, "--json"]).stdout)


def install_plugin(claude: str, values: Mapping[str, str]) -> None:
    options = {"root_deck": values["ANKI_ROOT_DECK"], "env_file": str(ENV_FILE)}
    marketplace = next((item for item in claude_json(claude, "marketplace", "list") if item["name"] == MARKETPLACE), None)
    if marketplace and not same_path(marketplace.get("path", ""), ROOT):
        # A folder that was moved, or the plugin from GitHub: this also removes the old plugin.
        run([claude, "plugin", "marketplace", "remove", MARKETPLACE])
        marketplace = None
    if marketplace is None:
        run([claude, "plugin", "marketplace", "add", str(ROOT)])
    if any(item["id"] == PLUGIN for item in claude_json(claude, "list")):
        run([claude, "plugin", "marketplace", "update", MARKETPLACE])
        run([claude, "plugin", "update", PLUGIN])
        run([claude, "plugin", "configure", PLUGIN, "--values-stdin"], stdin=json.dumps(options))
    else:
        settings = [item for key, value in options.items() for item in ("--config", f"{key}={value}")]
        run([claude, "plugin", "install", PLUGIN, *settings])


def anki_version(url: str) -> int | None:
    request = urllib.request.Request(url, data=b'{"action": "version", "version": 6}', method="POST")
    try:
        with urllib.request.urlopen(request, timeout=3) as response:
            return json.load(response).get("result")
    except (OSError, ValueError):
        return None


def check_anki(values: Mapping[str, str]) -> None:
    version = anki_version(values.get("ANKI_CONNECT_URL") or "http://127.0.0.1:8765")
    if version:
        say(f"  ✓ Anki відповідає, AnkiConnect API v{version}")
        return
    say("  ! Anki не відповідає. Це не заважає решті, але для карток:")
    say("    1. Встанови Anki: https://apps.ankiweb.net")
    say("    2. Інструменти → Додатки → Отримати додатки, код 2055492159 (AnkiConnect)")
    say("    3. Перезапусти Anki і тримай її відкритою, коли працюєш з картками")


def checklist(bot_ready: bool) -> None:
    say()
    say("Лишились ручні кроки:")
    say(f"  [ ] Obsidian: Open folder as vault → {ROOT / 'obsidian'}")
    say("  [ ] Obsidian: увімкни сторонні додатки, постав Dataview і Calendar")
    say("  [ ] Dataview: увімкни Enable JavaScript Queries, інакше Dashboard не порахує")
    say("  [ ] Calendar: початок тижня з понеділка")
    say("  [ ] Anki: Налаштування → Синхронізація → синхронізувати при відкритті й закритті")
    if bot_ready:
        say("  [ ] Telegram: надішли своєму боту /start")
    say("  [ ] Claude Code: відкрий новий чат у вкладці Code і спробуй /journal")


def install(args: argparse.Namespace) -> int:
    say("1/5 Налаштування")
    values = configure(answer_questions=not args.yes)
    enable_commit_check()

    say("2/5 Залежності")
    uv = find_uv()
    ready = install_dependencies(uv)

    say("3/5 Плагін Claude Code")
    claude = shutil.which("claude")
    if args.no_plugin:
        say("  – Пропущено")
    elif not claude:
        say("  ! Не знайдено claude. Встанови Claude Code: https://code.claude.com і запусти setup ще раз.")
    else:
        install_plugin(claude, values)
        say("  ✓ Плагін встановлено. Команди з'являться в новому чаті.")

    say("4/5 Автозапуск бота")
    if args.no_autostart:
        say("  – Пропущено")
    elif not ready:
        say("  ! Пропущено: спершу виправ помилку вище і запусти setup ще раз.")
    else:
        if sys.platform == "darwin" and (folder := autostart.mac_private_folder(ROOT)):
            say(f"  ! Репозиторій лежить у {folder}: macOS не пустить туди бота у фоні. Перенеси його, наприклад, у ~/discipline.")
        autostart.install(uv, BOT_DIR)
        say("  ✓ Бот запущено, далі стартуватиме сам після входу в систему")

    say("5/5 Anki")
    check_anki(values)
    checklist(ready and not args.no_autostart)
    return 0 if ready else 1


def update(args: argparse.Namespace) -> int:
    if not args.after_pull:
        changed = run(["git", "status", "--porcelain", "--untracked-files=no"]).stdout.strip()
        if changed:
            say("Оновлення зупинено: ці файли з репозиторію змінені локально.")
            say(changed)
            say("Скасуй зміни (git restore <файл>) або збережи їх (git stash) і запусти update ще раз.")
            return 1
        pulled = run(["git", "pull", "--ff-only"], check=False)
        if pulled.returncode != 0:
            say(f"git pull не вдався:\n{pulled.stderr.strip()}")
            return 1
        say(f"✓ Код оновлено: {pulled.stdout.strip().splitlines()[-1]}")
        # Carry on with the code that has just arrived.
        return subprocess.run([sys.executable, __file__, "update", "--after-pull"], check=False).returncode

    text, added = add_missing_settings(ENV_FILE.read_text(encoding="utf-8"), ENV_EXAMPLE.read_text(encoding="utf-8"))
    if added:
        write_env(text)
        say(f"✓ Нові налаштування в .env: {', '.join(added)}")
    values = read_env(text)
    enable_commit_check()
    ready = install_dependencies(find_uv())
    claude = shutil.which("claude")
    if claude:
        install_plugin(claude, values)
        say("✓ Плагін оновлено. Нові команди з'являться в новому чаті.")
    if ready and autostart.restart():
        say("✓ Бота перезапущено")
    return 0 if ready else 1


def uninstall(args: argparse.Namespace) -> int:
    if not args.yes and input("Прибрати автозапуск бота і плагін? [т/Н]: ").strip().lower() not in {"т", "так", "y", "yes"}:
        say("Нічого не змінено.")
        return 0
    say("✓ Автозапуск прибрано, бота зупинено" if autostart.uninstall() else "– Автозапуску не було")
    claude = shutil.which("claude")
    if claude and any(item["name"] == MARKETPLACE for item in claude_json(claude, "marketplace", "list")):
        run([claude, "plugin", "marketplace", "remove", MARKETPLACE])
        say("✓ Плагін прибрано")
    say(f"Твої нотатки, .env і дані бота лишились у {ROOT}.")
    return 0


def main(argv: list[str] | None = None) -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    parser = argparse.ArgumentParser(description="Встановлення системи Stop Procrastination.")
    parser.add_argument("command", nargs="?", choices=("install", "update", "uninstall"), default="install")
    parser.add_argument("--yes", action="store_true", help="нічого не питати: брати значення з .env")
    parser.add_argument("--no-plugin", action="store_true", help="не чіпати плагін Claude Code")
    parser.add_argument("--no-autostart", action="store_true", help="не налаштовувати автозапуск бота")
    parser.add_argument("--after-pull", action="store_true", help=argparse.SUPPRESS)
    args = parser.parse_args(argv)
    try:
        return {"install": install, "update": update, "uninstall": uninstall}[args.command](args)
    except subprocess.CalledProcessError as error:
        say(f"Команда не вдалась: {' '.join(map(str, error.cmd[:4]))}\n{(error.stderr or error.stdout or '').strip()}")
        return 1
    except KeyboardInterrupt:
        say("\nЗупинено.")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
