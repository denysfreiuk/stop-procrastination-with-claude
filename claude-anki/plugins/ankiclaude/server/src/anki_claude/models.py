"""Create and update the AC note types in the user's collection."""

from __future__ import annotations

import base64
from typing import Any

from . import __version__
from .ankiconnect import AnkiConnect
from .decks import Decks
from .errors import AnkiError
from .notetypes import NoteTypeSpec, build_specs, made_by, media_files

# Changes to a note type's structure: Anki needs a full sync after them.
FULL_SYNC_CHANGES = ("нове поле", "новий шаблон")


def _version(text: str) -> tuple[int, ...]:
    return tuple(int(part) for part in text.split("."))


def _older(version: str | None) -> bool:
    """Made by an earlier plugin version (types from before 0.4.2 carry no version)."""
    return version is None or _version(version) < _version(__version__)


def _newer(version: str | None) -> bool:
    return version is not None and _version(version) > _version(__version__)


def older_types(plan: dict[str, Any]) -> list[str]:
    """Types in an ensure report that differ because an earlier plugin version made them."""
    return [name for name in plan["updated"] if _older(plan["made_by"].get(name))]


def newer_types(plan: dict[str, Any]) -> list[str]:
    return [name for name in plan["updated"] if _newer(plan["made_by"].get(name))]


def needs_full_sync(plan: dict[str, Any], names: list[str]) -> bool:
    return any(c.startswith(FULL_SYNC_CHANGES) for name in names for c in plan["changes"][name])


def update_hint(plan: dict[str, Any]) -> str | None:
    """A next step for check_connection when the AC note types do not match this plugin version."""
    newer = newer_types(plan)
    if newer:
        return (
            f"Плагін ({__version__}) старіший за типи нотаток AC ({plan['made_by'][newer[0]]}): онови плагін "
            "і перезапусти його (новий чат або /mcp → Reconnect). Не запускай ensure_note_types — це відкотить шаблони."
        )
    older = older_types(plan)
    if older and needs_full_sync(plan, older):
        return (
            "Нова версія плагіна додає поля чи шаблони в типи нотаток AC: після цього Anki попросить повну "
            "синхронізацію. Спитай користувача і, якщо згоден, запусти ensure_note_types."
        )
    if older:
        return "Типи нотаток AC зробила старіша версія плагіна: вони оновляться самі під час наступного add_notes."
    return None


class NoteTypes:
    def __init__(self, client: AnkiConnect, decks: Decks, language: str, tts: bool = True, tts_lang: str = "en_US") -> None:
        self.client = client
        self.decks = decks
        self.specs = build_specs(language, tts, tts_lang)

    async def overview(self) -> dict[str, Any]:
        report = await self.ensure(dry_run=True)
        names = await self.client.invoke("modelNames")
        ours = {spec.name for spec in self.specs.values()}

        def state(name: str) -> str:
            version = report["made_by"].get(name)
            if name in report["created"]:
                return "немає"
            if name not in report["updated"]:
                return "актуальний"
            if _newer(version):
                return f"новіший за плагін ({version})"
            if _older(version):
                return "застарів"
            return "не збігається з налаштуваннями"  # same version, e.g. tts or language changed

        return {
            "plugin_version": __version__,
            "ac_note_types": {spec.name: state(spec.name) for spec in self.specs.values()},
            "fields": {spec.name: list(spec.fields) for spec in self.specs.values()},
            "other_note_types": sorted(n for n in names if n not in ours),
        }

    async def auto_update(self) -> dict[str, Any] | None:
        """Bring note types made by an earlier plugin version up to date when that needs no full sync.

        Returns None when there is nothing to do. Types of this version that differ (the user changed
        tts or the language) are left to ensure, and so are types a newer plugin made.
        """
        plan = await self.ensure(dry_run=True)
        older = older_types(plan)
        if not older:
            return None
        changes = {name: plan["changes"][name] for name in older}
        if needs_full_sync(plan, older):
            return {
                "status": "needs_confirmation",
                "note_types": older,
                "changes": changes,
                "message": "Нова версія плагіна додає поля чи шаблони в типи нотаток AC: після цього Anki попросить "
                "повну синхронізацію. Спитай користувача і, якщо згоден, запусти ensure_note_types.",
            }
        await self.ensure(only=set(older))
        return {
            "status": "updated",
            "note_types": older,
            "changes": changes,
            "message": f"Типи нотаток AC оновлено до версії плагіна {__version__} (шаблони й стилі, без повної синхронізації).",
        }

    async def ensure(self, dry_run: bool = False, only: set[str] | None = None) -> dict[str, Any]:
        """Create missing AC note types and bring outdated ones up to date. Never removes fields.

        Refuses to change types a newer plugin version made: an older server (a chat started
        before the update, a laptop not updated yet) would roll their templates back.
        """
        caps = await self.client.capabilities()
        use_v1 = caps.has("noteTypes.create") and caps.has("noteTypes.get") and caps.has("noteTypes.editStructure")
        names = set(await self.client.invoke("modelNames"))
        specs = [s for s in self.specs.values() if only is None or s.name in only]
        versions = await self._made_by([s.name for s in specs if s.name in names])
        newer = [name for name, version in versions.items() if _newer(version)]
        if newer and not dry_run:
            raise AnkiError(
                f"Типи нотаток {', '.join(newer)} оновила новіша версія плагіна ({versions[newer[0]]}), "
                f"ніж запущена ({__version__}).",
                "Онови плагін (claude plugin update ankiclaude@ankiclaude) і перезапусти його: новий чат "
                "або /mcp → plugin:ankiclaude:anki → Reconnect.",
            )
        report: dict[str, Any] = {
            "dry_run": dry_run,
            "plugin_version": __version__,
            "created": [],
            "updated": [],
            "unchanged": [],
            "changes": {},
            "made_by": versions,
            "full_sync_required": False,
            "deck_overrides": "в шаблонах (API v1)" if use_v1 else "маршрутизація після додавання (API v6)",
            "media_stored": [],
        }
        if not dry_run:
            for deck in sorted({t.deck for s in specs for t in s.templates if t.deck}):
                await self.decks.ensure(deck)
        deck_ids = await self.client.invoke("deckNamesAndIds") if use_v1 else {}

        for spec in specs:
            if spec.name not in names:
                report["created"].append(spec.name)
                if not dry_run:
                    await self._create(spec, use_v1)
                continue
            changes = await self._sync_existing(spec, use_v1, deck_ids, dry_run)
            if changes:
                report["updated"].append(spec.name)
                report["changes"][spec.name] = changes
                if any(c.startswith(FULL_SYNC_CHANGES) for c in changes):
                    report["full_sync_required"] = True
            else:
                report["unchanged"].append(spec.name)

        if not dry_run:
            report["media_stored"] = await self._store_media()
        return report

    async def _made_by(self, names: list[str]) -> dict[str, str | None]:
        """The plugin version that last wrote each note type, from the marker in its CSS."""
        if not names:
            return {}
        stylings = await self.client.multi([("modelStyling", {"modelName": name}) for name in names])
        for value in stylings:
            if isinstance(value, Exception):
                raise value
        return {name: made_by(styling["css"]) for name, styling in zip(names, stylings)}

    async def _create(self, spec: NoteTypeSpec, use_v1: bool) -> None:
        if use_v1:
            await self.client.rpc(
                "noteTypes.create",
                {
                    "name": spec.name,
                    "kind": spec.kind,
                    "fields": [{"name": field} for field in spec.fields],
                    "templates": [
                        {
                            "name": t.name,
                            "questionHtml": t.front,
                            "answerHtml": t.back,
                            "deck": {"name": self.decks.full(t.deck)} if t.deck else None,
                        }
                        for t in spec.templates
                    ],
                    "css": spec.css,
                    "sortField": spec.fields[0],
                },
            )
            return
        await self.client.invoke(
            "createModel",
            modelName=spec.name,
            inOrderFields=list(spec.fields),
            css=spec.css,
            isCloze=spec.kind == "cloze",
            cardTemplates=[{"Name": t.name, "Front": t.front, "Back": t.back} for t in spec.templates],
        )

    async def _sync_existing(self, spec: NoteTypeSpec, use_v1: bool, deck_ids: dict, dry_run: bool) -> list[str]:
        fields, templates, styling = await self.client.multi(
            [
                ("modelFieldNames", {"modelName": spec.name}),
                ("modelTemplates", {"modelName": spec.name}),
                ("modelStyling", {"modelName": spec.name}),
            ]
        )
        for value in (fields, templates, styling):
            if isinstance(value, Exception):
                raise value
        changes: list[str] = []
        missing_fields = [f for f in spec.fields if f not in fields]
        missing_templates = [t for t in spec.templates if t.name not in templates]
        changed_templates = [
            t for t in spec.templates
            if t.name in templates and (templates[t.name]["Front"] != t.front or templates[t.name]["Back"] != t.back)
        ]
        changes += [f"нове поле {f}" for f in missing_fields]
        changes += [f"новий шаблон {t.name}" for t in missing_templates]
        changes += [f"оновлено шаблон {t.name}" for t in changed_templates]
        if styling["css"] != spec.css:
            changes.append("оновлено CSS")

        override_edits = []
        if use_v1:
            current = await self.client.rpc("noteTypes.get", {"noteType": {"name": spec.name}})
            current_decks = {t["name"]: (t.get("deck") or {}).get("id") for t in current["templates"]}
            for t in spec.templates:
                wanted = str(deck_ids[self.decks.full(t.deck)]) if t.deck and self.decks.full(t.deck) in deck_ids else None
                if t.deck and t.name in current_decks and current_decks[t.name] != wanted:
                    override_edits.append(
                        {"op": "updateTemplate", "name": t.name, "patch": {"deck": {"name": self.decks.full(t.deck)}}}
                    )
                    changes.append(f"колода шаблону {t.name} → {self.decks.full(t.deck)}")
        if dry_run or not changes:
            return changes

        for field in missing_fields:
            await self.client.invoke("modelFieldAdd", modelName=spec.name, fieldName=field, index=spec.fields.index(field))
        for t in missing_templates:
            await self.client.invoke("modelTemplateAdd", modelName=spec.name, template={"Name": t.name, "Front": t.front, "Back": t.back})
        if changed_templates:
            await self.client.invoke(
                "updateModelTemplates",
                model={"name": spec.name, "templates": {t.name: {"Front": t.front, "Back": t.back} for t in changed_templates}},
            )
        if styling["css"] != spec.css:
            await self.client.invoke("updateModelStyling", model={"name": spec.name, "css": spec.css})
        if use_v1 and missing_templates:
            # Templates added through v6 have no deck override yet.
            override_edits += [
                {"op": "updateTemplate", "name": t.name, "patch": {"deck": {"name": self.decks.full(t.deck)}}}
                for t in missing_templates if t.deck
            ]
        if override_edits:
            await self.client.rpc("noteTypes.editStructure", {"noteType": {"name": spec.name}, "edits": override_edits})
        return changes

    async def _store_media(self) -> list[str]:
        stored = []
        for name, path in media_files().items():
            present = await self.client.invoke("getMediaFilesNames", pattern=name)
            if name in present:
                continue
            data = base64.b64encode(path.read_bytes()).decode("ascii")
            await self.client.invoke("storeMediaFile", filename=name, data=data)
            stored.append(name)
        return stored
