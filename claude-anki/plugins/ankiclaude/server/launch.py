"""Start the MCP server without a virtual environment.

Dependencies from requirements.lock.txt are installed once with `uv pip install
--target` into the plugin's data directory and put on sys.path. No .exe files are
created, so Windows Smart App Control, which blocks the unsigned launchers a
venv contains, cannot stop the server. Only the standard library is used here.

stdout belongs to the MCP protocol: everything this script prints goes to stderr.
"""

from __future__ import annotations

import hashlib
import os
import shutil
import site
import subprocess
import sys
import sysconfig
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
REQUIREMENTS = HERE / "requirements.lock.txt"


def log(message: str) -> None:
    print(f"[anki-claude] {message}", file=sys.stderr, flush=True)


def data_dir() -> Path:
    for name in ("ANKI_CLAUDE_DATA_DIR", "CLAUDE_PLUGIN_DATA"):
        value = os.environ.get(name, "").strip()
        if value and not value.startswith("${"):
            return Path(value)
    if sys.platform == "win32":
        base = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local"))
    elif sys.platform == "darwin":
        base = Path.home() / "Library" / "Caches"
    else:
        base = Path(os.environ.get("XDG_CACHE_HOME", Path.home() / ".cache"))
    return base / "anki-claude"


def deps_dir() -> Path:
    tag = f"py{sys.version_info.major}{sys.version_info.minor}-{sysconfig.get_platform()}"
    digest = hashlib.sha256(REQUIREMENTS.read_bytes() + tag.encode()).hexdigest()[:12]
    return data_dir() / f"pydeps-{tag}-{digest}"


def find_uv() -> str:
    # `uv run` exports its own path as UV.
    uv = os.environ.get("UV") or shutil.which("uv")
    if not uv:
        raise SystemExit("[anki-claude] Не знайдено uv. Встанови його: https://docs.astral.sh/uv/")
    return uv


def install(target: Path) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix=target.name + ".", dir=target.parent))
    log(f"Перший запуск: встановлюю залежності в {target} (це один раз, ~10–30 с)…")
    command = [
        find_uv(), "pip", "install", "--quiet", "--require-hashes",
        "--python", sys.executable, "--target", str(staging), "-r", str(REQUIREMENTS),
    ]
    result = subprocess.run(command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, encoding="utf-8")
    if result.returncode != 0:
        shutil.rmtree(staging, ignore_errors=True)
        sys.stderr.write(result.stdout)
        raise SystemExit("[anki-claude] Не вдалося встановити залежності (перевір інтернет).")
    (staging / ".complete").write_text("ok", encoding="utf-8")
    try:
        staging.rename(target)
    except OSError:
        # Another session finished the same install first.
        shutil.rmtree(staging, ignore_errors=True)
    for old in target.parent.glob("pydeps-*"):
        if old != target and old.is_dir():
            shutil.rmtree(old, ignore_errors=True)


def bootstrap() -> None:
    target = deps_dir()
    if not (target / ".complete").is_file():
        install(target)
    before = list(sys.path)
    site.addsitedir(str(target))
    # Our pinned packages must win over anything in the interpreter's own site-packages.
    added = [entry for entry in sys.path if entry not in before]
    sys.path[:] = [str(HERE / "src"), *added, *before]


def main() -> None:
    # Windows consoles default to cp1251/cp866; Claude Code reads the server's stderr as UTF-8.
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    bootstrap()
    from anki_claude.server import main as serve

    serve()


if __name__ == "__main__":
    main()
