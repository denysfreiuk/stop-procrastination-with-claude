"""Deck structure under the root deck and one preset per deck family."""

from __future__ import annotations

import copy
from dataclasses import dataclass
from typing import Any

from .ankiconnect import AnkiConnect
from .errors import AnkiActionError, AnkiError

PRESET_PREFIX = "AC · "
REVIEWS_PER_DAY = 9999
NEW_BRANCH_NEW_PER_DAY = 2
# Indices of Anki's "new card gather order" and "new card sort order" options.
GATHER_RANDOM_NOTES = 3
SORT_RANDOM_NOTE_THEN_TEMPLATE = 3


@dataclass(frozen=True)
class DeckSpec:
    path: str  # relative to the root deck; "" is the root itself
    preset: str  # preset name without PRESET_PREFIX; "" means the root deck's name
    new_per_day: int | None  # None: the sum of the direct subdecks
    standard: bool = True  # False: created only when its first card arrives


SPECS: dict[str, DeckSpec] = {
    spec.path: spec
    for spec in (
        DeckSpec("", "", None),
        DeckSpec("English", "English", None),
        DeckSpec("English::EN-UA", "EN-UA", 10),
        DeckSpec("English::UA-EN", "UA-EN", 7),
        DeckSpec("English::Distinctions", "Distinctions", 3),
        DeckSpec("ML", "ML", 2),
        DeckSpec("Uni", "Uni", 2),
        DeckSpec("Code", "Code", 2, standard=False),
    )
}
# Subdecks of these branches share the branch's preset, so the branch limit covers all of them.
SHARED_BRANCHES = ("Code", "Uni", "ML")


class DeckError(AnkiError):
    code = "deck_error"


def _parent(path: str) -> str:
    return path.rpartition("::")[0]


def _depth(path: str) -> int:
    return 0 if not path else path.count("::") + 1


class Decks:
    def __init__(self, client: AnkiConnect, root: str) -> None:
        self.client = client
        self.root = root

    # Names

    def full(self, path: str) -> str:
        return self.root if not path else f"{self.root}::{path}"

    def relative(self, name: str) -> str | None:
        if name == self.root:
            return ""
        prefix = self.root + "::"
        return name[len(prefix):] if name.startswith(prefix) else None

    def resolve(self, deck: str) -> str:
        """Accept "ML", "Code::Python" or "Den::ML"; return the relative path under the root."""
        name = "::".join(part.strip() for part in deck.strip().split("::") if part.strip())
        if not name:
            raise DeckError("Не вказано колоду.")
        relative = self.relative(name)
        return relative if relative is not None else name

    def spec_for(self, path: str) -> DeckSpec:
        if path in SPECS:
            return SPECS[path]
        top = path.split("::")[0]
        if top in SHARED_BRANCHES:
            return SPECS[top]
        if _depth(path) == 1:
            return DeckSpec(path, path, NEW_BRANCH_NEW_PER_DAY, standard=False)
        return self.spec_for(_parent(path))

    def preset_name(self, path: str) -> str:
        spec = self.spec_for(path)
        return PRESET_PREFIX + (spec.preset or self.root)

    # Reading

    async def managed(self) -> list[str]:
        """Relative paths of all existing decks under the root, parents first."""
        names = await self.client.invoke("deckNames")
        paths = [p for p in (self.relative(n) for n in names) if p is not None]
        return sorted(paths, key=lambda p: (_depth(p), p))

    async def _configs(self, paths: list[str]) -> dict[str, dict]:
        if not paths:
            return {}
        results = await self.client.multi([("getDeckConfig", {"deck": self.full(p)}) for p in paths])
        configs = {}
        for path, value in zip(paths, results, strict=True):
            if isinstance(value, Exception):
                raise value
            configs[path] = value
        return configs

    # Writing

    async def setup(self) -> dict[str, Any]:
        """Create the standard decks and give every managed deck its preset. Idempotent."""
        existing = set(await self.managed())
        created = []
        for spec in SPECS.values():
            if spec.standard and spec.path not in existing:
                await self.client.invoke("createDeck", deck=self.full(spec.path))
                created.append(self.full(spec.path))
        presets = await self.apply_presets()
        return {"created": created, **presets}

    async def ensure(self, deck: str) -> tuple[str, list[str]]:
        """Make sure a deck exists (with its parents and preset). Returns the full name and newly created decks."""
        path = self.resolve(deck)
        existing = set(await self.managed())
        if path in existing:
            return self.full(path), []
        missing = []
        current = path
        while True:
            if current not in existing:
                missing.append(self.full(current))
            if not current:
                break
            current = _parent(current)
        # Anki creates the missing parents together with the deck.
        await self.client.invoke("createDeck", deck=self.full(path))
        await self.apply_presets()
        return self.full(path), sorted(missing, key=lambda n: n.count("::"))

    async def apply_presets(self) -> dict[str, Any]:
        paths = await self.managed()
        configs = await self._configs(paths)
        by_name: dict[str, dict] = {}
        for config in configs.values():
            by_name.setdefault(config["name"], config)

        created_presets, assigned = [], []
        for path in paths:
            wanted = self.preset_name(path)
            if configs[path]["name"] == wanted:
                continue
            if wanted in by_name:
                await self.client.invoke("setDeckConfigId", decks=[self.full(path)], configId=by_name[wanted]["id"])
            else:
                config_id = await self.client.invoke("cloneDeckConfigId", name=wanted, cloneFrom=1)
                if config_id is False:
                    raise AnkiActionError("cloneDeckConfigId", f"не вдалося створити пресет «{wanted}»")
                await self.client.invoke("setDeckConfigId", decks=[self.full(path)], configId=config_id)
                config = await self.client.invoke("getDeckConfig", deck=self.full(path))
                spec = self.spec_for(path)
                self._apply_defaults(config, spec)
                await self._save(config)
                by_name[wanted] = config
                created_presets.append(wanted)
            configs[path] = by_name[wanted]
            assigned.append(f"{self.full(path)} → {wanted}")

        totals = await self._recompute_totals(paths, configs)
        return {"presets_created": created_presets, "presets_assigned": assigned, "totals": totals}

    def _apply_defaults(self, config: dict, spec: DeckSpec) -> None:
        config["new"]["perDay"] = spec.new_per_day if spec.new_per_day is not None else 0
        config["rev"]["perDay"] = REVIEWS_PER_DAY
        config["new"]["bury"] = True
        config["rev"]["bury"] = True
        config["buryInterdayLearning"] = True
        if spec.new_per_day is None:
            config["newGatherPriority"] = GATHER_RANDOM_NOTES
            config["newSortOrder"] = SORT_RANDOM_NOTE_THEN_TEMPLATE

    async def _save(self, config: dict) -> None:
        ok = await self.client.invoke("saveDeckConfig", config=config)
        if ok is False:
            raise AnkiActionError("saveDeckConfig", f"пресет «{config.get('name')}» не збережено")

    async def _recompute_totals(self, paths: list[str], configs: dict[str, dict]) -> dict[str, int]:
        """Set every "sum" deck (root, English) to the sum of its direct subdecks' new-card limits."""
        effective: dict[str, int] = {}
        totals: dict[str, int] = {}
        for path in sorted(paths, key=_depth, reverse=True):
            if self.spec_for(path).new_per_day is None:
                children = [p for p in paths if p and _parent(p) == path]
                total = sum(effective.get(child, 0) for child in children)
                config = configs[path]
                if config["new"]["perDay"] != total:
                    updated = copy.deepcopy(config)
                    updated["new"]["perDay"] = total
                    await self._save(updated)
                    config["new"]["perDay"] = total
                effective[path] = total
                totals[self.full(path)] = total
            else:
                effective[path] = configs[path]["new"]["perDay"]
        return totals

    async def set_options(self, deck: str, new_per_day: int | None, reviews_per_day: int | None) -> dict[str, Any]:
        path = self.resolve(deck)
        paths = await self.managed()
        if path not in paths:
            raise DeckError(f"Колоди «{self.full(path)}» немає.")
        configs = await self._configs(paths)
        config = configs[path]
        if new_per_day is not None and self.spec_for(path).new_per_day is None and config["name"] == self.preset_name(path):
            raise DeckError(
                f"Ліміт нових для «{self.full(path)}» рахується автоматично як сума підколод.",
                "Зміни ліміт потрібної підколоди.",
            )
        shared = sorted(self.full(p) for p, c in configs.items() if c["id"] == config["id"] and p != path)
        updated = copy.deepcopy(config)
        if new_per_day is not None:
            updated["new"]["perDay"] = new_per_day
        if reviews_per_day is not None:
            updated["rev"]["perDay"] = reviews_per_day
        await self._save(updated)
        for p, c in configs.items():
            if c["id"] == config["id"]:
                configs[p] = updated
        totals = await self._recompute_totals(paths, configs)
        return {
            "deck": self.full(path),
            "preset": updated["name"],
            "new_per_day": updated["new"]["perDay"],
            "reviews_per_day": updated["rev"]["perDay"],
            "also_affects": shared,
            "totals": totals,
        }

    async def overview(self) -> dict[str, Any]:
        paths = await self.managed()
        if not paths:
            return {"root": self.root, "exists": False, "decks": []}
        configs = await self._configs(paths)
        stats = await self.client.invoke("getDeckStats", decks=[self.full(p) for p in paths])
        by_name = {value["name"]: value for value in stats.values()}
        decks = []
        for path in paths:
            name = self.full(path)
            stat = by_name.get(name, {})
            decks.append(
                {
                    "deck": name,
                    "preset": configs[path]["name"],
                    "new_per_day": configs[path]["new"]["perDay"],
                    "reviews_per_day": configs[path]["rev"]["perDay"],
                    "due_new": stat.get("new_count"),
                    "due_learning": stat.get("learn_count"),
                    "due_review": stat.get("review_count"),
                    "cards": stat.get("total_in_deck"),
                }
            )
        return {"root": self.root, "exists": "" in paths, "decks": decks}
