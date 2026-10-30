"""Stop personal notes and secrets from reaching the public repository.

python setup/check_privacy.py --staged   what is about to be committed (pre-commit hook)
python setup/check_privacy.py --all      everything git tracks (CI and final checks)

Paths are checked against the same allowlist as .gitignore, so `git add -f` does not help.
Contents are checked for token formats and for this machine's own values from .env.
Only the standard library is used, so the hook needs nothing installed.
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from collections.abc import Callable, Iterable, Mapping
from pathlib import Path, PurePosixPath

ROOT = Path(__file__).resolve().parents[1]
VAULT = "obsidian/"
VAULT_FILES = {
    "Dashboard.md",
    "CLAUDE.md",
    ".obsidian/daily-notes.json",
    ".obsidian/templates.json",
    ".obsidian/types.json",
}
PRIVATE_ENV_KEYS = ("TELEGRAM_BOT_TOKEN", "TELEGRAM_USER_ID", "ANKI_CONNECT_KEY")
SECRET_PATTERNS = {
    "токен Telegram-бота": re.compile(r"\b\d{6,12}:[A-Za-z0-9_-]{30,}\b"),
    "токен GitHub": re.compile(r"\bgh[pousr]_[A-Za-z0-9]{30,}\b"),
    "ключ Anthropic": re.compile(r"\bsk-ant-[A-Za-z0-9_-]{20,}"),
    "приватний ключ": re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
}


def path_problem(path: str) -> str | None:
    name = PurePosixPath(path).name
    if name == ".env" or (name.startswith(".env.") and name != ".env.example"):
        return "файл із секретами"
    if name.endswith(".log"):
        return "лог"
    if path.startswith("telegram-bot/data/"):
        return "дані бота"
    if path.startswith(VAULT):
        relative = path.removeprefix(VAULT)
        allowed = relative in VAULT_FILES or relative.startswith("Templates/") or name == ".gitkeep"
        if not allowed:
            return "особиста нотатка або налаштування vault"
    return None


def content_problems(text: str, private_values: Mapping[str, str]) -> list[str]:
    found = [label for label, pattern in SECRET_PATTERNS.items() if pattern.search(text)]
    found += [label for label, value in private_values.items() if value in text]
    return found


def read_env_file(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    if not path.is_file():
        return values
    for raw in path.read_text(encoding="utf-8-sig").splitlines():
        key, separator, value = raw.strip().partition("=")
        if separator and not key.startswith("#"):
            values[key.strip()] = value.strip().strip("\"'")
    return values


def private_values() -> dict[str, str]:
    """Values of this machine that may not appear in any file, each labeled without showing it."""
    env = read_env_file(ROOT / ".env")
    values = {f"значення {key} з .env": env[key] for key in PRIVATE_ENV_KEYS if env.get(key)}
    email = git("config", "--global", "user.email", check=False).decode("utf-8").strip()
    if email and not email.endswith("@users.noreply.github.com"):
        values["особистий email з глобального git"] = email
    return values


def git(*args: str, check: bool = True) -> bytes:
    return subprocess.run(["git", *args], cwd=ROOT, capture_output=True, check=check).stdout


def paths_from(output: bytes) -> list[str]:
    return [item.decode("utf-8") for item in output.split(b"\0") if item]


def staged_paths() -> list[str]:
    return paths_from(git("diff", "--cached", "--name-only", "--diff-filter=ACMR", "-z"))


def tracked_paths() -> list[str]:
    return paths_from(git("ls-files", "-z"))


def read_staged(path: str) -> bytes:
    return git("show", f":{path}")


def read_worktree(path: str) -> bytes:
    try:
        return (ROOT / path).read_bytes()
    except OSError:
        return b""


def check(paths: Iterable[str], read: Callable[[str], bytes], private: Mapping[str, str]) -> list[str]:
    problems: list[str] = []
    for path in paths:
        problem = path_problem(path)
        if problem:
            problems.append(f"{path}: {problem}")
            continue
        content = read(path)
        if b"\0" in content:
            continue
        for label in content_problems(content.decode("utf-8", errors="ignore"), private):
            problems.append(f"{path}: {label}")
    return problems


def main(argv: list[str] | None = None) -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    parser = argparse.ArgumentParser(description="Перевірка на особисті дані перед комітом.")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--staged", action="store_true", help="перевірити staged-файли")
    group.add_argument("--all", action="store_true", help="перевірити всі файли в git")
    args = parser.parse_args(argv)

    paths = staged_paths() if args.staged else tracked_paths()
    problems = check(paths, read_staged if args.staged else read_worktree, private_values())
    if problems:
        print("Коміт заблоковано, у публічний репозиторій це потрапляти не має:", file=sys.stderr)
        for problem in problems:
            print(f"  {problem}", file=sys.stderr)
        return 1
    print(f"Особистих даних і секретів не знайдено (перевірено файлів: {len(paths)}).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
