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
import check_privacy  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
ENV_FILE = ROOT / ".env"
ENV_EXAMPLE = ROOT / ".env.example"
BOT_DIR = ROOT / "telegram-bot"
VAULT_TEMPLATE = ROOT / "obsidian"
GIT_ONLY = ROOT / "setup" / "vault-git-only.sh"
SERVER_VAULT = "../vault"
VAULT_GITIGNORE = """# Per-device state of Obsidian and temporary files
.obsidian/workspace*.json
.trash/
.*.tmp
.DS_Store
"""
SSH_KEY = re.compile(r"^(ssh-ed25519|ssh-rsa|ecdsa-sha2-nistp\d+|sk-ssh-ed25519@openssh\.com) [A-Za-z0-9+/=]+( .*)?$")
GIT_IDENTITY = ["-c", "user.name=discipline-setup", "-c", "user.email=setup@localhost"]
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


def configure(answer_questions: bool, questions: tuple[Question, ...] = QUESTIONS,
              forced: Mapping[str, str] | None = None) -> dict[str, str]:
    """Create or update .env, and keep what is already there when Enter is pressed."""
    example = ENV_EXAMPLE.read_text(encoding="utf-8")
    text = ENV_FILE.read_text(encoding="utf-8") if ENV_FILE.is_file() else example
    text, _ = add_missing_settings(text, example)
    values = {**read_env(text), **(forced or {})}
    if answer_questions:
        say("Натисни Enter, щоб лишити значення в дужках.")
        for question in questions:
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


def vault_path(values: Mapping[str, str]) -> Path:
    path = Path(values.get("VAULT_PATH") or "obsidian")
    return path if path.is_absolute() else ENV_FILE.parent / path


def template_files() -> list[Path]:
    """The public part of the vault template, never the notes kept in this folder."""
    return [
        path for path in sorted(VAULT_TEMPLATE.rglob("*"))
        if path.is_file() and check_privacy.path_problem(f"obsidian/{path.relative_to(VAULT_TEMPLATE).as_posix()}") is None
    ]


def create_vault(vault: Path) -> None:
    for source in template_files():
        target = vault / source.relative_to(VAULT_TEMPLATE)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)


def git_in(folder: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    return run(["git", "-C", str(folder), *args], check=check)


def share_vault(vault: Path) -> None:
    """Make the server's vault a repository the other devices push to.

    updateInstead lets a push update the files the bot works with, as long as they
    have no uncommitted changes, and the bot commits each of its writes at once.
    """
    if not (vault / ".git").exists():
        git_in(vault, "init", "--quiet", "--initial-branch=main")
    git_in(vault, "config", "receive.denyCurrentBranch", "updateInstead")
    ignore = vault / ".gitignore"
    if not ignore.exists():
        ignore.write_text(VAULT_GITIGNORE, encoding="utf-8", newline="\n")
    has_commits = git_in(vault, "rev-parse", "--verify", "--quiet", "HEAD", check=False).returncode == 0
    has_notes = any(path.name not in {".git", ".gitignore"} for path in vault.iterdir())
    # An empty repository stays empty: the first push from a laptop brings its own history.
    if not has_commits and has_notes:
        git_in(vault, "add", "--all")
        git_in(vault, *GIT_IDENTITY, "commit", "--quiet", "--message", "Початковий vault")


def prepare_vault(values: Mapping[str, str], server: bool) -> Path:
    """A new vault outside the repository starts from the template; an existing one is never filled in."""
    vault = vault_path(values)
    inside_repository = vault.resolve() == VAULT_TEMPLATE.resolve()
    if not inside_repository and not vault.exists():
        create_vault(vault)
        say(f"  ✓ Створено vault із шаблону: {vault.resolve()}")
    vault.mkdir(parents=True, exist_ok=True)
    if server:
        share_vault(vault)
        say("  ✓ Vault — git-репозиторій, з яким синхронізуються ноут і телефони")
    return vault


def linger_enabled(user: str) -> bool:
    result = run(["loginctl", "show-user", user, "--property=Linger"], check=False)
    return "Linger=yes" in result.stdout


def install_dependencies(uv: str, plugin: bool = True) -> bool:
    """Install what the bot and the plugin's server need, and check the bot's settings."""
    python = [uv, "run", "--quiet", "--no-project", "--python", "3.14"]
    result = run([*python, "--directory", str(BOT_DIR), "python", "launch.py", "--check"], check=False)
    if result.returncode != 0:
        say(f"  ✗ Бот: {(result.stdout or result.stderr).strip()}")
        return False
    say("  ✓ Бот готовий")
    if not plugin:
        return True
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
    if args.server:
        return install_server(args)
    say("1/5 Налаштування")
    values = configure(answer_questions=not args.yes)
    enable_commit_check()

    say("2/5 Залежності")
    prepare_vault(values, server=False)
    uv = find_uv()
    ready = install_dependencies(uv)
    run_bot = values.get("RUN_BOT", "true").lower() != "false"

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
    elif not run_bot:
        say("  – Бот працює на сервері (RUN_BOT=false), тут його не запускаю")
    elif not ready:
        say("  ! Пропущено: спершу виправ помилку вище і запусти setup ще раз.")
    else:
        if sys.platform == "darwin" and (folder := autostart.mac_private_folder(ROOT)):
            say(f"  ! Репозиторій лежить у {folder}: macOS не пустить туди бота у фоні. Перенеси його, наприклад, у ~/discipline.")
        autostart.install(uv, BOT_DIR)
        say("  ✓ Бот запущено, далі стартуватиме сам після входу в систему")

    say("5/5 Anki")
    check_anki(values)
    checklist(ready and run_bot and not args.no_autostart)
    return 0 if ready else 1


def install_server(args: argparse.Namespace) -> int:
    """The bot on an always-on Linux server; laptops and phones sync the vault with it over SSH."""
    say("1/4 Налаштування")
    current = read_env(ENV_FILE.read_text(encoding="utf-8")) if ENV_FILE.is_file() else {}
    forced = {"VAULT_GIT_COMMIT": "true", "RUN_BOT": "true"}
    if current.get("VAULT_PATH", "obsidian") == "obsidian":
        forced["VAULT_PATH"] = SERVER_VAULT
    values = configure(answer_questions=not args.yes, questions=QUESTIONS[:4], forced=forced)

    say("2/4 Vault")
    vault = prepare_vault(values, server=True)

    say("3/4 Залежності")
    uv = find_uv()
    ready = install_dependencies(uv, plugin=False)

    say("4/4 Автозапуск бота")
    if args.no_autostart:
        say("  – Пропущено")
    elif not ready:
        say("  ! Пропущено: спершу виправ помилку вище і запусти setup ще раз.")
    else:
        autostart.install(uv, BOT_DIR)
        say("  ✓ Бот запущено як сервіс systemd із лімітами пам'яті й процесора")
        user = os.environ.get("USER", "")
        if user and not linger_enabled(user):
            say("  ! Щоб бот працював і тоді, коли ти не залогінений, виконай один раз:")
            say(f"      sudo loginctl enable-linger {user}")

    say()
    say("Адреса vault для ноута й телефонів:")
    say(f"  ssh://{os.environ.get('USER', 'user')}@<адреса сервера>{vault.resolve()}")
    say("Ключ телефона додає: uv run --python 3.14 setup/setup.py add-device \"ssh-ed25519 AAAA… phone\"")
    return 0 if ready else 1


def add_device(args: argparse.Namespace) -> int:
    """Let a phone's SSH key sync the vault and nothing else: no shell, no other repositories."""
    key = " ".join(args.key).strip()
    if not SSH_KEY.match(key):
        say("Це не схоже на публічний SSH-ключ. Він починається з ssh-ed25519, ssh-rsa або ecdsa-sha2-….")
        return 1
    vault = vault_path(read_env(ENV_FILE.read_text(encoding="utf-8"))).resolve()
    keys = Path.home() / ".ssh" / "authorized_keys"
    existing = keys.read_text(encoding="utf-8") if keys.exists() else ""
    if key.split()[1] in existing:
        say("Цей ключ уже додано.")
        return 0
    keys.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    line = f"command=\"'{GIT_ONLY}' '{vault}'\",restrict {key}\n"
    with keys.open("a", encoding="utf-8", newline="\n") as file:
        file.write(("\n" if existing and not existing.endswith("\n") else "") + line)
    keys.chmod(0o600)
    say(f"✓ Пристрій додано. З цим ключем доступний лише git-репозиторій {vault}")
    return 0


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
    server = values.get("VAULT_GIT_COMMIT", "").lower() == "true"
    ready = install_dependencies(find_uv(), plugin=not server)
    claude = shutil.which("claude")
    if claude and not server:
        install_plugin(claude, values)
        say("✓ Плагін оновлено. Нові команди з'являться в новому чаті.")
    if ready and values.get("RUN_BOT", "true").lower() != "false" and autostart.restart():
        say("✓ Бота перезапущено")
    return 0 if ready else 1


def uninstall(args: argparse.Namespace) -> int:
    what = "автозапуск бота" if args.bot_only else "автозапуск бота і плагін"
    if not args.yes and input(f"Прибрати {what}? [т/Н]: ").strip().lower() not in {"т", "так", "y", "yes"}:
        say("Нічого не змінено.")
        return 0
    say("✓ Автозапуск прибрано, бота зупинено" if autostart.uninstall() else "– Автозапуску не було")
    if args.bot_only:
        if ENV_FILE.is_file():
            text, _ = add_missing_settings(ENV_FILE.read_text(encoding="utf-8"), ENV_EXAMPLE.read_text(encoding="utf-8"))
            write_env(set_env_values(text, {"RUN_BOT": "false"}))
            say("✓ RUN_BOT=false: setup більше не запускатиме бота на цьому комп'ютері")
        return 0
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
    parser.add_argument("command", nargs="?", choices=("install", "update", "uninstall", "add-device"), default="install")
    parser.add_argument("key", nargs="*", help="для add-device: публічний SSH-ключ пристрою")
    parser.add_argument("--yes", action="store_true", help="нічого не питати: брати значення з .env")
    parser.add_argument("--server", action="store_true", help="встановити бота на сервер, з яким синхронізуються пристрої")
    parser.add_argument("--no-plugin", action="store_true", help="не чіпати плагін Claude Code")
    parser.add_argument("--no-autostart", action="store_true", help="не налаштовувати автозапуск бота")
    parser.add_argument("--bot-only", action="store_true", help="для uninstall: прибрати лише бота, плагін лишити")
    parser.add_argument("--after-pull", action="store_true", help=argparse.SUPPRESS)
    args = parser.parse_args(argv)
    commands = {"install": install, "update": update, "uninstall": uninstall, "add-device": add_device}
    try:
        return commands[args.command](args)
    except subprocess.CalledProcessError as error:
        say(f"Команда не вдалась: {' '.join(map(str, error.cmd[:4]))}\n{(error.stderr or error.stdout or '').strip()}")
        return 1
    except KeyboardInterrupt:
        say("\nЗупинено.")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
