"""Two-step confirmation for deletions and mass changes.

The first call only previews and returns a one-time token; the action runs when the
same call comes back with that token. Tokens are bound to the exact action and
arguments and expire, so a token from one preview cannot authorise anything else.
"""

from __future__ import annotations

import json
import secrets
import time
from typing import Any

TTL_SECONDS = 600
MASS_CHANGE_LIMIT = 20


class Confirmations:
    def __init__(self) -> None:
        self._pending: dict[str, tuple[str, float]] = {}

    @staticmethod
    def _fingerprint(action: str, payload: Any) -> str:
        return action + "\0" + json.dumps(payload, sort_keys=True, ensure_ascii=False)

    def issue(self, action: str, payload: Any) -> str:
        now = time.monotonic()
        self._pending = {t: v for t, v in self._pending.items() if v[1] > now}
        token = secrets.token_hex(4)
        self._pending[token] = (self._fingerprint(action, payload), now + TTL_SECONDS)
        return token

    def consume(self, token: str | None, action: str, payload: Any) -> bool:
        if not token or token not in self._pending:
            return False
        fingerprint, expires = self._pending[token]
        if expires < time.monotonic() or fingerprint != self._fingerprint(action, payload):
            return False
        del self._pending[token]
        return True


def needs_confirmation(token: str, preview: Any, what: str) -> dict[str, Any]:
    return {
        "needs_confirmation": True,
        "confirm_token": token,
        "preview": preview,
        "message": f"{what} Покажи це користувачу і виклич інструмент ще раз з confirm_token "
        "лише після його явного «так». Токен діє 10 хвилин і лише для цих самих аргументів.",
    }
