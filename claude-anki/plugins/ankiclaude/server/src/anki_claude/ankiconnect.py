"""Async client for AnkiConnect.

API v6 (POST /) is the baseline every AnkiConnect version supports. Newer
add-on releases also serve API v1 (JSON-RPC 2.0, POST /api/v1); the client
detects it and callers use it only for what v6 cannot do.
"""

from __future__ import annotations

import itertools
from dataclasses import dataclass, field
from typing import Any

import httpx

from .errors import (
    AnkiActionError,
    AnkiAuthError,
    AnkiNotRunningError,
    AnkiOutdatedError,
    AnkiTimeoutError,
)

API_VERSION = 6
MIN_API_VERSION = 6


@dataclass(frozen=True)
class Capabilities:
    api_version: int
    v1: bool = False
    anki_version: str | None = None
    v1_methods: frozenset[str] = field(default_factory=frozenset)

    def has(self, method: str) -> bool:
        return self.v1 and method in self.v1_methods


class AnkiConnect:
    def __init__(
        self,
        url: str,
        key: str | None = None,
        *,
        timeout: float = 15.0,
        connect_timeout: float = 3.0,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self.url = url.rstrip("/")
        self.key = key
        self.timeout = timeout
        # trust_env=False: AnkiConnect is local, a system HTTP proxy must never see these requests.
        self._http = httpx.AsyncClient(
            timeout=httpx.Timeout(timeout, connect=connect_timeout),
            transport=transport,
            trust_env=False,
        )
        self._ids = itertools.count(1)
        self._caps: Capabilities | None = None

    async def aclose(self) -> None:
        await self._http.aclose()

    async def _post(self, path: str, payload: dict, label: str, timeout: float | None, headers: dict) -> httpx.Response:
        try:
            return await self._http.post(
                self.url + path,
                json=payload,
                headers=headers,
                timeout=httpx.Timeout(timeout, connect=self._http.timeout.connect) if timeout else httpx.USE_CLIENT_DEFAULT,
            )
        except (httpx.ConnectError, httpx.RemoteProtocolError, httpx.ConnectTimeout) as error:
            raise AnkiNotRunningError(self.url) from error
        except httpx.TimeoutException as error:
            raise AnkiTimeoutError(label, timeout or self.timeout) from error

    async def invoke(self, action: str, timeout: float | None = None, **params: Any) -> Any:
        """Call an API v6 action and return its result."""
        payload: dict[str, Any] = {"action": action, "version": API_VERSION}
        if params:
            payload["params"] = params
        if self.key:
            payload["key"] = self.key
        response = await self._post("", payload, action, timeout, {})
        if response.status_code in (401, 403):
            raise AnkiAuthError()
        response.raise_for_status()
        body = response.json()
        if not isinstance(body, dict) or "error" not in body:
            raise AnkiOutdatedError(
                f"AnkiConnect відповів у старому форматі (без API v{API_VERSION}).",
                "Онови add-on AnkiConnect: Anki → Інструменти → Додатки → Перевірити оновлення.",
            )
        error = body["error"]
        if error is not None:
            raise _v6_error(action, str(error))
        return body["result"]

    async def multi(self, actions: list[tuple[str, dict]], timeout: float | None = None) -> list[Any]:
        """Run several v6 actions in one request.

        Each item of the returned list is either the action's result or an AnkiActionError.
        """
        result = await self.invoke(
            "multi",
            timeout=timeout,
            actions=[{"action": name, "version": API_VERSION, "params": params} for name, params in actions],
        )
        out: list[Any] = []
        for (name, _), item in zip(actions, result, strict=True):
            if isinstance(item, dict) and set(item) == {"result", "error"}:
                out.append(_v6_error(name, str(item["error"])) if item["error"] is not None else item["result"])
            else:
                out.append(item)
        return out

    async def rpc(self, method: str, params: dict | None = None, timeout: float | None = None) -> Any:
        """Call an API v1 (JSON-RPC 2.0) method and return its result."""
        payload = {"jsonrpc": "2.0", "id": next(self._ids), "method": method, "params": params or {}}
        headers = {"Authorization": f"Bearer {self.key}"} if self.key else {}
        response = await self._post("/api/v1", payload, method, timeout, headers)
        if response.status_code in (401, 403):
            raise AnkiAuthError()
        if response.status_code == 404:
            raise AnkiActionError(method, "API v1 недоступний у цій версії AnkiConnect", "methodNotFound")
        if response.status_code == 204:
            return None
        response.raise_for_status()
        body = response.json()
        if "error" in body:
            error = body["error"]
            kind = (error.get("data") or {}).get("type")
            raise AnkiActionError(method, error.get("message", "невідома помилка"), kind)
        return body.get("result")

    async def capabilities(self, refresh: bool = False) -> Capabilities:
        if self._caps is not None and not refresh:
            return self._caps
        version = await self.invoke("version")
        if not isinstance(version, int) or version < MIN_API_VERSION:
            raise AnkiOutdatedError(
                f"AnkiConnect надто старий (API v{version}, потрібна v{MIN_API_VERSION}+).",
                "Онови add-on AnkiConnect: Anki → Інструменти → Додатки → Перевірити оновлення.",
            )
        caps = Capabilities(api_version=version)
        try:
            described = await self.rpc("api.describe")
        except AnkiActionError:
            described = None
        if isinstance(described, dict) and described.get("apiMajor") == 1:
            caps = Capabilities(
                api_version=version,
                v1=True,
                anki_version=described.get("ankiVersion"),
                v1_methods=frozenset(m["name"] for m in described.get("methods", []) if m.get("available")),
            )
        self._caps = caps
        return caps


def _v6_error(action: str, error: str) -> Exception:
    lowered = error.lower()
    if "api key" in lowered:
        return AnkiAuthError()
    if "unsupported action" in lowered:
        return AnkiOutdatedError(
            f"Твоя версія AnkiConnect не знає дії «{action}».",
            "Онови add-on AnkiConnect: Anki → Інструменти → Додатки → Перевірити оновлення.",
        )
    return AnkiActionError(action, error)
