"""Errors with messages meant to be shown to the user as-is (Ukrainian)."""

from __future__ import annotations

# `claude plugin configure` exists only since Claude Code 2.1.285; /plugin works in older versions too.
CONFIGURE_HINT = (
    "Змінити налаштування: у терміналі запусти claude → /plugin → Anki&Claude → Configure "
    "(у Claude Code 2.1.285+ також: claude plugin configure ankiclaude@ankiclaude)."
)


class AnkiError(Exception):
    """Base error. `message` says what happened, `hint` says what to do."""

    code = "anki_error"

    def __init__(self, message: str, hint: str | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.hint = hint

    def __str__(self) -> str:
        return f"{self.message} {self.hint}" if self.hint else self.message


class NotConfiguredError(AnkiError):
    code = "not_configured"


class AnkiNotRunningError(AnkiError):
    code = "anki_not_running"

    def __init__(self, url: str) -> None:
        super().__init__(
            f"Anki не відповідає за адресою {url}.",
            "Відкрий Anki на комп'ютері. Якщо Anki вже відкрита — перевір, що встановлено "
            "add-on AnkiConnect (код 2055492159) і Anki перезапущена після встановлення.",
        )


class AnkiTimeoutError(AnkiError):
    code = "anki_timeout"

    def __init__(self, action: str, seconds: float) -> None:
        super().__init__(
            f"Anki не відповіла на «{action}» за {seconds:g} с.",
            "Можливо, в Anki відкрите модальне вікно (налаштування, синхронізація, повідомлення) — "
            "закрий його. На macOS Anki у фоні може «заснути» (App Nap) — розгорни її вікно.",
        )


class AnkiAuthError(AnkiError):
    code = "anki_auth"

    def __init__(self) -> None:
        super().__init__(
            "AnkiConnect відхилив запит: потрібен правильний API-ключ.",
            f"Вкажи ключ із налаштувань AnkiConnect (apiKey) у конфігу плагіна. {CONFIGURE_HINT}",
        )


class AnkiOutdatedError(AnkiError):
    code = "anki_outdated"


class AnkiActionError(AnkiError):
    """AnkiConnect executed the request but the action failed."""

    code = "anki_action"

    def __init__(self, action: str, error: str, kind: str | None = None) -> None:
        super().__init__(f"AnkiConnect: «{action}» не виконано: {error}")
        self.action = action
        self.error = error
        self.kind = kind


class SyncError(AnkiError):
    """Sync did not complete. `reason` is machine-readable."""

    code = "sync_failed"

    def __init__(self, reason: str, message: str, hint: str | None = None) -> None:
        super().__init__(message, hint)
        self.reason = reason
