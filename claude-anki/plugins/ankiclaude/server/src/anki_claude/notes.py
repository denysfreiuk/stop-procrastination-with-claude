"""Adding notes: validation, duplicates, card routing and delayed production cards."""

from __future__ import annotations

import html
import re
from dataclasses import dataclass, field
from datetime import date
from typing import Any, Literal

from pydantic import BaseModel, Field

from .ankiconnect import AnkiConnect
from .confirm import MASS_CHANGE_LIMIT, Confirmations, needs_confirmation
from .decks import Decks
from .errors import AnkiError
from .notetypes import NoteTypeSpec, build_specs

NoteKind = Literal["concept", "cloze", "formula", "code", "vocab", "distinction"]

TAG_RE = re.compile(r"^[a-z0-9]+(?:[-.][a-z0-9]+)*(?:::[a-z0-9]+(?:[-.][a-z0-9]+)*)*$")
PENDING_PRODUCTION = "status::pending-production"
PENDING_FORMS = "status::pending-forms"
REGISTERS = {"neutral", "formal", "informal", "slang"}
SHORT_FIELDS = {"WhyThisWord": 300, "Explanation": 300, "Why": 300}
YES = {"yes", "y", "true", "1", "так", "+"}
NO = {"no", "n", "false", "0", "ні", "-", ""}
PRODUCTION_ORD = 1
FORMS_ORD = 2


class NoteIn(BaseModel):
    type: NoteKind = Field(description="Тип нотатки")
    fields: dict[str, str] = Field(description="Поля нотатки за назвами (див. list_note_types)")
    deck: str | None = Field(
        default=None,
        description="Колода відносно кореневої, напр. ML, Uni::Calculus, Code::Python. "
        "Для vocab і distinction не потрібна — вони йдуть у свої колоди English.",
    )
    tags: list[str] = Field(default_factory=list, description="Теги kebab-case латиницею, напр. topic::ml::pytorch")
    known: bool | None = Field(default=None, description="vocab: картка UA→EN одразу активна (без чекання)")


class DuplicateCandidate(BaseModel):
    type: NoteKind = Field(description="Тип майбутньої нотатки")
    key: str = Field(description="Головне поле: слово (vocab), питання (concept), текст (cloze) тощо")


class NoteValidationError(AnkiError):
    code = "invalid_note"


@dataclass
class Prepared:
    index: int
    spec: NoteTypeSpec
    deck: str  # relative to the root
    fields: dict[str, str]
    tags: list[str]
    pending: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def key(self) -> str:
        return plain_text(self.fields[self.spec.fields[0]])[:80]


def plain_text(value: str) -> str:
    return html.unescape(re.sub(r"<[^>]+>", " ", value)).replace("\xa0", " ").strip()


def normalize_tag(tag: str) -> str:
    value = tag.strip().lower().replace(" ", "-").replace("_", "-")
    value = re.sub(r"-{2,}", "-", value)
    if not TAG_RE.match(value):
        raise NoteValidationError(
            f"тег «{tag}» має бути латиницею в kebab-case, з ієрархією через :: (напр. topic::ml::linear-algebra)"
        )
    return value


def _flag(value: str, name: str) -> str:
    lowered = plain_text(value).lower()
    if lowered in YES:
        return "yes"
    if lowered in NO:
        return ""
    raise NoteValidationError(f"{name} має бути yes або no, а не «{value}»")


def _markdown_bold(value: str) -> str:
    return re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", value)


def _text(value: str) -> str:
    return value.strip().replace("\r\n", "\n").replace("\n", "<br>")


def clean_fields(spec: NoteTypeSpec, raw: dict[str, str]) -> dict[str, str]:
    """Normalize the given fields (any subset of the note type's fields)."""
    fields: dict[str, str] = {}
    for name, value in raw.items():
        value = value or ""
        if name == "Code":
            code = value.replace("\r\n", "\n").strip("\n")
            fields[name] = html.escape(code, quote=False).replace("\n", "<br>")
            continue
        value = _text(value)
        if name in ("Example1", "Example2", "Example3"):
            value = _markdown_bold(value)
            if plain_text(value) and not re.search(r"<(b|strong)>.+?</\1>", value):
                raise NoteValidationError(f"{name}: виділи слово в реченні як <b>…</b>")
        elif spec.key == "vocab" and name in ("Active", "DrillForms"):
            value = _flag(value, name)
        elif spec.key == "vocab" and name == "Register":
            value = plain_text(value).lower()
            if value and value not in REGISTERS:
                raise NoteValidationError(f"Register має бути одним із {sorted(REGISTERS)}")
        elif name == "Language":
            value = re.sub(r"[^a-z0-9+#-]", "", plain_text(value).lower())
        if name in SHORT_FIELDS and len(plain_text(value)) > SHORT_FIELDS[name]:
            raise NoteValidationError(
                f"{name} довше {SHORT_FIELDS[name]} символів — скороти до 1–2 рядків або винеси в окрему картку"
            )
        fields[name] = value
    return fields


def check_note(spec: NoteTypeSpec, fields: dict[str, str]) -> None:
    """Rules that look at the whole note."""
    missing = [name for name in spec.required if not plain_text(fields.get(name, ""))]
    if missing:
        raise NoteValidationError(f"порожні обов'язкові поля {missing}")
    if spec.key == "vocab":
        examples = [n for n in ("Example1", "Example2", "Example3") if plain_text(fields.get(n, ""))]
        if len(examples) < 2:
            raise NoteValidationError("потрібно щонайменше 2 непорожні приклади (Example1–3)")
        if fields.get("DrillForms") and not plain_text(fields.get("Forms", "")):
            raise NoteValidationError("DrillForms=yes, але поле Forms порожнє")
    elif spec.key == "cloze" and not re.search(r"\{\{c\d+::", fields.get("Text", "")):
        raise NoteValidationError("у Text немає жодного пропуску {{c1::…}}")
    elif spec.key == "distinction" and not re.search(r"_{3,}", fields.get("Sentence", "")):
        raise NoteValidationError("у Sentence має бути пропуск ___ і варіанти, напр. «___ a mistake (make / do)»")


def prepare(note: NoteIn, index: int, specs: dict[str, NoteTypeSpec], decks: Decks, known: bool) -> Prepared:
    spec = specs[note.type]
    unknown = sorted(set(note.fields) - set(spec.fields))
    if unknown:
        raise NoteValidationError(f"невідомі поля {unknown}; у {spec.name} є: {list(spec.fields)}")
    fields = clean_fields(spec, {name: note.fields.get(name, "") for name in spec.fields})
    check_note(spec, fields)

    tags = []
    for tag in [*note.tags, "gen::claude", f"added::{date.today():%Y-%m}"]:
        normalized = normalize_tag(tag)
        if normalized not in tags:
            tags.append(normalized)

    pending: list[str] = []
    warnings: list[str] = []
    if spec.key == "vocab":
        if fields["Active"] and not (note.known if note.known is not None else known):
            pending.append("production")
            tags.append(PENDING_PRODUCTION)
        if fields["DrillForms"]:
            pending.append("forms")
            tags.append(PENDING_FORMS)

    if spec.deck:
        if note.deck and decks.resolve(note.deck) != spec.deck:
            warnings.append(f"колоду {note.deck} проігноровано: {spec.name} завжди йде в {decks.full(spec.deck)}")
        deck = spec.deck
    elif note.deck:
        deck = decks.resolve(note.deck)
    else:
        raise NoteValidationError("не вказано колоду (deck), напр. ML, Uni або Code::Python")
    return Prepared(index, spec, deck, fields, tags, pending, warnings)


def field_query(name: str, value: str) -> str:
    escaped = re.sub(r'([\\"*_:])', r"\\\1", plain_text(value))
    return f'"{name}:{escaped}"'


class Notes:
    def __init__(self, client: AnkiConnect, decks: Decks, language: str) -> None:
        self.client = client
        self.decks = decks
        self.specs = build_specs(language)

    async def add(self, notes: list[NoteIn], known: bool = False) -> dict[str, Any]:
        report: dict[str, Any] = {"added": [], "duplicates": [], "errors": [], "decks_created": [], "warnings": []}
        prepared: list[Prepared] = []
        for index, note in enumerate(notes):
            try:
                item = prepare(note, index, self.specs, self.decks, known)
            except NoteValidationError as error:
                key = next(iter(note.fields.values()), "") if note.fields else ""
                report["errors"].append({"index": index, "type": note.type, "key": plain_text(key)[:80], "error": str(error)})
                continue
            prepared.append(item)
            report["warnings"] += [f"№{index + 1}: {w}" for w in item.warnings]
        if not prepared:
            return self._summarize(report)

        for deck in sorted({p.deck for p in prepared}):
            _, created = await self.decks.ensure(deck)
            report["decks_created"] += created

        anki_notes = [self._anki_note(p) for p in prepared]
        checks = await self.client.invoke("canAddNotesWithErrorDetail", notes=anki_notes)
        addable: list[tuple[Prepared, dict]] = []
        for item, payload, check in zip(prepared, anki_notes, checks, strict=True):
            if check.get("canAdd"):
                addable.append((item, payload))
            elif "duplicate" in str(check.get("error", "")).lower():
                existing = await self.client.invoke(
                    "findNotes",
                    query=f'note:"{item.spec.name}" {field_query(item.spec.fields[0], item.fields[item.spec.fields[0]])}',
                )
                report["duplicates"].append({"index": item.index, "type": item.spec.key, "key": item.key, "existing_note_ids": existing})
            else:
                report["errors"].append({"index": item.index, "type": item.spec.key, "key": item.key, "error": str(check.get("error"))})
        if not addable:
            return self._summarize(report)

        ids = await self.client.invoke("addNotes", notes=[payload for _, payload in addable])
        added = [(item, note_id) for (item, _), note_id in zip(addable, ids, strict=True) if note_id]
        for (item, _), note_id in zip(addable, ids, strict=True):
            if not note_id:
                report["errors"].append({"index": item.index, "type": item.spec.key, "key": item.key, "error": "Anki не додала нотатку"})

        cards_by_note = await self._route_and_suspend(added)
        for item, note_id in added:
            report["added"].append(
                {
                    "index": item.index,
                    "note_id": note_id,
                    "type": item.spec.key,
                    "key": item.key,
                    "deck": self.decks.full(item.deck),
                    "cards": cards_by_note.get(note_id, 0),
                    "pending": item.pending,
                }
            )
        return self._summarize(report)

    def _anki_note(self, item: Prepared) -> dict[str, Any]:
        return {
            "deckName": self.decks.full(item.deck),
            "modelName": item.spec.name,
            "fields": item.fields,
            "tags": item.tags,
            "options": {"allowDuplicate": False, "duplicateScope": "collection"},
        }

    async def _route_and_suspend(self, added: list[tuple[Prepared, int]]) -> dict[int, int]:
        """Move every card to its template's deck and suspend delayed cards.

        With API v1 the template deck override already put the cards in place; this pass
        is what routes them on older AnkiConnect, and a no-op otherwise.
        """
        if not added:
            return {}
        by_note = {note_id: item for item, note_id in added}
        card_ids = await self.client.invoke("findCards", query="nid:" + ",".join(str(n) for n in by_note))
        cards = await self.client.invoke("cardsInfo", cards=card_ids)
        moves: dict[str, list[int]] = {}
        suspend: list[int] = []
        counts: dict[int, int] = {}
        for card in cards:
            item = by_note[card["note"]]
            counts[card["note"]] = counts.get(card["note"], 0) + 1
            template = item.spec.templates[card["ord"]] if card["ord"] < len(item.spec.templates) else None
            wanted = self.decks.full(template.deck) if template and template.deck else self.decks.full(item.deck)
            if card["deckName"] != wanted:
                moves.setdefault(wanted, []).append(card["cardId"])
            if item.spec.key == "vocab" and (
                (card["ord"] == PRODUCTION_ORD and "production" in item.pending)
                or (card["ord"] == FORMS_ORD and "forms" in item.pending)
            ):
                suspend.append(card["cardId"])
        for deck, ids in moves.items():
            await self.client.invoke("changeDeck", cards=ids, deck=deck)
        if suspend:
            await self.client.invoke("suspend", cards=suspend)
        return counts

    def _summarize(self, report: dict[str, Any]) -> dict[str, Any]:
        report["summary"] = (
            f"додано {len(report['added'])}, дублікатів {len(report['duplicates'])}, помилок {len(report['errors'])}"
        )
        return report

    # Reading

    def spec_by_name(self, model: str) -> NoteTypeSpec | None:
        return next((s for s in self.specs.values() if s.name == model), None)

    def template_name(self, model: str, ord_: int) -> str:
        spec = self.spec_by_name(model)
        if spec and spec.kind == "cloze":
            return f"Cloze {ord_ + 1}"
        if spec and ord_ < len(spec.templates):
            return spec.templates[ord_].name
        return f"Card {ord_ + 1}"

    async def describe(self, note_ids: list[int], with_fields: bool = True) -> list[dict[str, Any]]:
        if not note_ids:
            return []
        infos = await self.client.invoke("notesInfo", notes=note_ids)
        card_ids = [cid for info in infos for cid in info.get("cards", [])]
        cards = await self.client.invoke("cardsInfo", cards=card_ids) if card_ids else []
        by_note: dict[int, list[dict]] = {}
        for card in cards:
            by_note.setdefault(card["note"], []).append(card)
        out = []
        for info in infos:
            model = info["modelName"]
            spec = self.spec_by_name(model)
            fields = {name: value["value"] for name, value in sorted(info["fields"].items(), key=lambda kv: kv[1]["order"])}
            entry: dict[str, Any] = {
                "note_id": info["noteId"],
                "type": spec.key if spec else model,
                "key": plain_text(next(iter(fields.values()), ""))[:80],
                "tags": info["tags"],
                "cards": [
                    {
                        "card_id": card["cardId"],
                        "template": self.template_name(model, card["ord"]),
                        "deck": card["deckName"],
                        "interval_days": card["interval"],
                        "lapses": card["lapses"],
                        "suspended": card["queue"] == -1,
                    }
                    for card in sorted(by_note.get(info["noteId"], []), key=lambda c: c["ord"])
                ],
            }
            if with_fields:
                entry["fields"] = fields
            out.append(entry)
        return out

    async def find(self, query: str, limit: int = 30, with_fields: bool = True) -> dict[str, Any]:
        note_ids = await self.client.invoke("findNotes", query=query)
        shown = sorted(note_ids)[:limit]
        return {"query": query, "total": len(note_ids), "shown": len(shown), "notes": await self.describe(shown, with_fields)}

    async def check_duplicates(self, candidates: list[DuplicateCandidate]) -> dict[str, Any]:
        results = []
        for candidate in candidates:
            spec = self.specs[candidate.type]
            first = spec.fields[0]
            key = plain_text(candidate.key)
            exact = await self.client.invoke("findNotes", query=f'note:"{spec.name}" {field_query(first, key)}')
            similar_query = self._similar_query(spec, key)
            similar = [n for n in await self.client.invoke("findNotes", query=similar_query) if n not in exact] if similar_query else []
            described = {n["note_id"]: n for n in await self.describe([*exact, *similar[:5]], with_fields=False)}
            results.append(
                {
                    "type": candidate.type,
                    "key": key,
                    "exact": [{"note_id": n, "key": described[n]["key"]} for n in exact if n in described],
                    "similar": [{"note_id": n, "key": described[n]["key"]} for n in similar[:5] if n in described],
                }
            )
        clashes = sum(1 for r in results if r["exact"] or r["similar"])
        return {"checked": len(results), "with_matches": clashes, "results": results}

    @staticmethod
    def _similar_query(spec: NoteTypeSpec, key: str) -> str | None:
        words = re.findall(r"[^\W\d_]{3,}", key.lower())
        if not words:
            return None
        if spec.key == "vocab":
            # Same headword in another form: "give up" vs "gave up", "reluctant" vs "reluctantly".
            stems = [w[:-3] if len(w) > 6 and w.endswith(("ing", "ed", "ly")) else w[: max(4, len(w) - 2)] for w in words]
            return f'note:"{spec.name}" ' + " ".join(f'"{spec.fields[0]}:*{s}*"' for s in stems)
        significant = sorted(set(words), key=len, reverse=True)[:3]
        return f'note:"{spec.name}" ' + " ".join(significant)

    # Writing

    async def update_fields(self, note_id: int, raw: dict[str, str], known: bool = False) -> dict[str, Any]:
        (info,) = await self.client.invoke("notesInfo", notes=[note_id])
        if not info or "modelName" not in info:
            raise NoteValidationError(f"нотатки {note_id} немає")
        spec = self.spec_by_name(info["modelName"])
        current = {name: value["value"] for name, value in info["fields"].items()}
        unknown = sorted(set(raw) - set(current))
        if unknown:
            raise NoteValidationError(f"невідомі поля {unknown}; у {info['modelName']} є: {list(current)}")
        cleaned = clean_fields(spec, raw) if spec else dict(raw)
        merged = {**current, **cleaned}
        if spec:
            check_note(spec, merged)
        changed = {name: value for name, value in cleaned.items() if current.get(name) != value}
        if not changed:
            return {"note_id": note_id, "changed": [], "message": "нічого не змінилось"}
        await self.client.invoke("updateNoteFields", note={"id": note_id, "fields": changed})
        report: dict[str, Any] = {"note_id": note_id, "changed": sorted(changed)}
        if spec and spec.key == "vocab":
            report.update(await self._after_vocab_update(note_id, spec, current, merged, info["tags"], known))
        return report

    async def _after_vocab_update(
        self, note_id: int, spec: NoteTypeSpec, before: dict, after: dict, tags: list[str], known: bool
    ) -> dict[str, Any]:
        """Route cards a field change created, and keep new Production/Forms cards waiting."""
        card_ids = await self.client.invoke("findCards", query=f"nid:{note_id}")
        cards = {c["ord"]: c for c in await self.client.invoke("cardsInfo", cards=card_ids)}
        notes: list[str] = []
        suspend, unsuspend, add_tags, remove_tags = [], [], [], []
        for ord_, template in enumerate(spec.templates):
            card = cards.get(ord_)
            if card and template.deck and card["deckName"] != self.decks.full(template.deck):
                await self.client.invoke("changeDeck", cards=[card["cardId"]], deck=self.decks.full(template.deck))
        production, forms = cards.get(PRODUCTION_ORD), cards.get(FORMS_ORD)
        if after.get("Active") and not before.get("Active") and production:
            if known:
                unsuspend.append(production["cardId"])
                notes.append("картка UA→EN створена й активна")
            else:
                suspend.append(production["cardId"])
                add_tags.append(PENDING_PRODUCTION)
                notes.append("картка UA→EN створена і чекає закріплення EN→UA")
        if not after.get("Active") and before.get("Active") and production:
            suspend.append(production["cardId"])
            remove_tags.append(PENDING_PRODUCTION)
            notes.append("Active вимкнено: картку UA→EN призупинено")
        if after.get("DrillForms") and plain_text(after.get("Forms", "")) and forms and not (before.get("DrillForms") and plain_text(before.get("Forms", ""))):
            suspend.append(forms["cardId"])
            add_tags.append(PENDING_FORMS)
            notes.append("картка форм створена і чекає закріплення UA→EN")
        if not after.get("DrillForms") and before.get("DrillForms") and forms:
            suspend.append(forms["cardId"])
            remove_tags.append(PENDING_FORMS)
            notes.append("DrillForms вимкнено: картку форм призупинено")
        if suspend:
            await self.client.invoke("suspend", cards=suspend)
        if unsuspend:
            await self.client.invoke("unsuspend", cards=unsuspend)
        if add_tags:
            await self.client.invoke("addTags", notes=[note_id], tags=" ".join(add_tags))
        if remove_tags and any(t in tags for t in remove_tags):
            await self.client.invoke("removeTags", notes=[note_id], tags=" ".join(remove_tags))
        return {"cards": notes} if notes else {}

    async def change_tags(
        self, action: Literal["add", "remove"], note_ids: list[int], tags: list[str], confirmations: Confirmations, token: str | None
    ) -> dict[str, Any]:
        normalized = sorted({normalize_tag(t) for t in tags})
        if not normalized or not note_ids:
            raise NoteValidationError("потрібні note_ids і хоча б один тег")
        payload = {"notes": sorted(note_ids), "tags": normalized}
        name = f"{action}_tags"
        if len(note_ids) > MASS_CHANGE_LIMIT and not confirmations.consume(token, name, payload):
            preview = await self.describe(sorted(note_ids)[:10], with_fields=False)
            verb = "Додати" if action == "add" else "Прибрати"
            return needs_confirmation(
                confirmations.issue(name, payload),
                {"notes": len(note_ids), "tags": normalized, "first_notes": [p["key"] for p in preview]},
                f"{verb} теги {normalized} у {len(note_ids)} нотатках — це масова зміна.",
            )
        await self.client.invoke("addTags" if action == "add" else "removeTags", notes=note_ids, tags=" ".join(normalized))
        return {"done": True, "action": name, "notes": len(note_ids), "tags": normalized}

    async def delete(self, note_ids: list[int], confirmations: Confirmations, token: str | None) -> dict[str, Any]:
        if not note_ids:
            raise NoteValidationError("не вказано note_ids")
        payload = sorted(note_ids)
        if not confirmations.consume(token, "delete_notes", payload):
            preview = await self.describe(payload[:20], with_fields=False)
            return needs_confirmation(
                confirmations.issue("delete_notes", payload),
                {"notes": len(payload), "list": [{"note_id": p["note_id"], "type": p["type"], "key": p["key"]} for p in preview]},
                f"Видалити {len(payload)} нотаток разом з усіма їхніми картками й історією повторень — це незворотно.",
            )
        await self.client.invoke("deleteNotes", notes=payload)
        return {"deleted": len(payload)}
