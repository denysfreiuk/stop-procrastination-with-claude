"""Entry point of the plugin's hooks: `python hook.py session-start|stop`.

The cheap checks (is anything enabled, is it time yet) run on the standard library
before dependencies are loaded, so most Stop hooks finish in a fraction of a second.
"""

from __future__ import annotations

import json
import os
import sys
import time

from launch import bootstrap, data_dir

REMIND_EVERY_SECONDS = 3 * 3600
PROMOTE_EVERY_SECONDS = 3 * 3600
FALSE = {"false", "0", "no", "ні", "off"}


def option(name: str, default: bool) -> bool:
    value = os.environ.get(f"CLAUDE_PLUGIN_OPTION_{name}", "").strip().lower()
    return default if not value else value not in FALSE


def last(key: str) -> float:
    try:
        return json.loads((data_dir() / "hook-state.json").read_text(encoding="utf-8")).get(key, 0)
    except (OSError, ValueError):
        return 0


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    event = sys.argv[1] if len(sys.argv) > 1 else ""
    try:
        payload = json.loads(sys.stdin.read() or "{}")
    except ValueError:
        payload = {}
    now = time.time()
    if event == "stop":
        if payload.get("stop_hook_active"):
            return 0
        sound = option("SOUND_ON_STOP", False)
        remind = option("REVIEW_REMINDER", True) and now - last("remind") >= REMIND_EVERY_SECONDS
        if not sound and not remind:
            return 0
    elif event == "session-start":
        if now - last("promote") < PROMOTE_EVERY_SECONDS:
            return 0
    else:
        return 0
    bootstrap()
    from anki_claude.hooks import run

    return run(event, data_dir())


if __name__ == "__main__":
    sys.exit(main())
