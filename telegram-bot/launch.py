"""Start the bot without a virtual environment.

Dependencies from requirements.lock.txt are installed once with `uv pip install
--target` into data/ and put on sys.path. No .exe files are created, so Windows
Smart App Control, which blocks the unsigned launchers a venv contains, cannot
stop the bot. Only the standard library is used here.
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
DATA = HERE / "data"
REQUIREMENTS = HERE / "requirements.lock.txt"


def log(message: str) -> None:
    print(f"[discipline-bot] {message}", file=sys.stderr, flush=True)


def deps_dir() -> Path:
    tag = f"py{sys.version_info.major}{sys.version_info.minor}-{sysconfig.get_platform()}"
    digest = hashlib.sha256(REQUIREMENTS.read_bytes() + tag.encode()).hexdigest()[:12]
    return DATA / f"pydeps-{tag}-{digest}"


def find_uv() -> str:
    # `uv run` exports its own path as UV.
    uv = os.environ.get("UV") or shutil.which("uv")
    if not uv:
        raise SystemExit("[discipline-bot] Не знайдено uv. Встанови його: https://docs.astral.sh/uv/")
    return uv


def install(target: Path) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix=target.name + ".", dir=target.parent))
    log(f"Встановлюю залежності в {target} (це один раз)…")
    command = [
        find_uv(), "pip", "install", "--quiet", "--require-hashes",
        "--python", sys.executable, "--target", str(staging), "-r", str(REQUIREMENTS),
    ]
    result = subprocess.run(command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, encoding="utf-8")
    if result.returncode != 0:
        shutil.rmtree(staging, ignore_errors=True)
        log(result.stdout)
        raise SystemExit("[discipline-bot] Не вдалося встановити залежності (перевір інтернет).")
    (staging / ".complete").write_text("ok", encoding="utf-8")
    try:
        staging.rename(target)
    except OSError:
        # Another start finished the same install first.
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
    # Windows consoles default to cp1251/cp866; there is no stderr at all under pythonw.
    if sys.stderr is not None:
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    bootstrap()
    from discipline_bot.bot import main as run

    run()


if __name__ == "__main__":
    main()
