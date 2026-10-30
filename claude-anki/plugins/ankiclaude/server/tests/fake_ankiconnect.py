"""In-memory stand-in for AnkiConnect, served through httpx.MockTransport.

It keeps a tiny collection (decks, presets, note types, notes, cards, media) and
generates cards the way Anki does: a card exists only when its front template
renders at least one non-empty field.
"""

from __future__ import annotations

import base64
import copy
import itertools
import json
import re
from dataclasses import dataclass, field
from typing import Any

import httpx

SECTION = re.compile(r"\{\{([#^])([^}]+)\}\}(.*?)\{\{/\2\}\}", re.S)
REFERENCE = re.compile(r"\{\{(?![#^/!])([^}]+)\}\}")


def plain(value: str) -> str:
    return re.sub(r"<[^>]+>", "", value or "").strip()


def front_has_content(template: str, fields: dict[str, str]) -> bool:
    """Anki's card generation rule for normal note types."""
    text = template
    while (match := SECTION.search(text)) is not None:
        filled = bool(plain(fields.get(match.group(2).strip(), "")))
        keep = filled if match.group(1) == "#" else not filled
        text = text[: match.start()] + (match.group(3) if keep else "") + text[match.end():]
    for reference in REFERENCE.findall(text):
        name = reference.split(":")[-1].strip()
        if name in fields and plain(fields[name]):
            return True
    return False


TOKEN = re.compile(r'\(|\)|[^\s()"]*"(?:[^"\\]|\\.)*"|[^\s()]+')


def _unquote(term: str) -> str:
    if term.startswith('"') and term.endswith('"'):
        term = term[1:-1]
    return term


def _like(pattern: str, value: str) -> bool:
    """Anki-style match: case-insensitive, * wildcard, backslash escapes."""
    regex = ""
    i = 0
    while i < len(pattern):
        ch = pattern[i]
        if ch == "\\" and i + 1 < len(pattern):
            regex += re.escape(pattern[i + 1])
            i += 2
            continue
        regex += ".*" if ch == "*" else re.escape(ch)
        i += 1
    return re.fullmatch(regex, value, re.IGNORECASE | re.S) is not None


def default_preset() -> dict:
    return {
        "id": 1, "name": "Типовий", "new": {"perDay": 20, "bury": False, "delays": [1.0, 10.0]},
        "rev": {"perDay": 200, "bury": False}, "lapse": {"leechFails": 8},
        "newGatherPriority": 0, "newSortOrder": 0, "buryInterdayLearning": False,
    }


@dataclass
class FakeAnkiConnect:
    running: bool = True
    api_version: int = 6
    v1: bool = True
    key: str | None = None
    logged_in: bool = True
    reviewing: bool = False
    has_gui_review_active: bool = True
    # States collection.sync passes through on API v1; the last one is final.
    sync_states: list[str] = field(default_factory=lambda: ["running", "succeeded"])
    sync_error_type: str = "ioError"
    profile: str = "Користувач 1"
    decks: list[str] = field(default_factory=lambda: ["Типовий"])
    models: list[str] = field(default_factory=lambda: ["Базовий"])
    calls: list[str] = field(default_factory=list)
    syncs: int = 0
    deck_ids: dict[str, int] = field(default_factory=dict)
    deck_preset: dict[str, int] = field(default_factory=dict)
    presets: dict[int, dict] = field(default_factory=lambda: {1: default_preset()})
    note_types: dict[str, dict] = field(default_factory=dict)
    notes: dict[int, dict] = field(default_factory=dict)
    cards: dict[int, dict] = field(default_factory=dict)
    media: dict[str, bytes] = field(default_factory=dict)
    _ids: Any = field(default_factory=lambda: itertools.count(1000))
    _operations: dict[str, list[str]] = field(default_factory=dict)

    def __post_init__(self) -> None:
        for name in self.decks:
            self._create_deck(name)
        for name in self.models:
            self.note_types.setdefault(name, {"kind": "normal", "fields": ["Front", "Back"], "css": "",
                                              "templates": [{"name": "Card 1", "front": "{{Front}}", "back": "{{Back}}", "did": None}]})

    # Collection helpers

    def _create_deck(self, name: str) -> int:
        parts = name.split("::")
        for i in range(1, len(parts) + 1):
            prefix = "::".join(parts[:i])
            if prefix not in self.deck_ids:
                self.deck_ids[prefix] = next(self._ids)
                self.deck_preset[prefix] = 1
                if prefix not in self.decks:
                    self.decks.append(prefix)
        return self.deck_ids[name]

    def _deck_name(self, deck_id: int) -> str:
        return next(name for name, i in self.deck_ids.items() if i == deck_id)

    def _generate_cards(self, note_id: int) -> None:
        note = self.notes[note_id]
        model = self.note_types[note["model"]]
        existing = {c["ord"] for c in self.cards.values() if c["note"] == note_id}
        if model["kind"] == "cloze":
            numbers = sorted({int(n) for n in re.findall(r"\{\{c(\d+)::", note["fields"].get("Text", ""))})
            wanted = [(n - 1, None) for n in numbers]
        else:
            wanted = [(ord_, t["did"]) for ord_, t in enumerate(model["templates"]) if front_has_content(t["front"], note["fields"])]
        for ord_, did in wanted:
            if ord_ not in existing:
                deck = self._deck_name(did) if did else note["deck"]
                self.cards[next(self._ids)] = {"note": note_id, "ord": ord_, "deck": deck, "queue": 0, "ivl": 0, "lapses": 0}

    def card_ids(self, note_id: int) -> list[int]:
        return sorted(cid for cid, c in self.cards.items() if c["note"] == note_id)

    def card(self, note_id: int, ord_: int) -> dict | None:
        return next((c for c in self.cards.values() if c["note"] == note_id and c["ord"] == ord_), None)

    def transport(self) -> httpx.MockTransport:
        return httpx.MockTransport(self.handle)

    def handle(self, request: httpx.Request) -> httpx.Response:
        if not self.running:
            raise httpx.ConnectError("connection refused", request=request)
        body = json.loads(request.content)
        if request.url.path == "/api/v1":
            return self._v1(request, body)
        return httpx.Response(200, json=self._v6(body))

    # API v6

    def _v6(self, body: dict) -> dict:
        action = body["action"]
        self.calls.append(action)
        if action != "requestPermission" and body.get("key") != self.key:
            return {"result": None, "error": "valid api key must be provided"}
        try:
            return {"result": self._v6_action(action, body.get("params", {})), "error": None}
        except Exception as error:  # noqa: BLE001 - mirrors AnkiConnect's catch-all reply
            return {"result": None, "error": str(error)}

    def _v6_action(self, action: str, p: dict) -> Any:  # noqa: C901 - one branch per action, like AnkiConnect
        if action == "version":
            return self.api_version
        if action == "getActiveProfile":
            return self.profile
        if action == "deckNames":
            return list(self.decks)
        if action == "deckNamesAndIds":
            return dict(self.deck_ids)
        if action == "modelNames":
            return list(self.note_types)
        if action == "guiReviewActive":
            if not self.has_gui_review_active:
                raise Exception("unsupported action")
            return self.reviewing
        if action == "guiCurrentCard":
            if not self.reviewing:
                raise Exception("Gui review is not currently active.")
            return {"cardId": 1}
        if action == "sync":
            if not self.logged_in:
                raise Exception("sync: auth not configured")
            self.syncs += 1
            return None
        if action == "multi":
            return [self._v6(dict(item, key=self.key)) for item in p["actions"]]

        # Decks and presets
        if action == "createDeck":
            return self._create_deck(p["deck"])
        if action == "getDeckConfig":
            if p["deck"] not in self.deck_ids:
                return False
            return copy.deepcopy(self.presets[self.deck_preset[p["deck"]]])
        if action == "saveDeckConfig":
            if p["config"]["id"] not in self.presets:
                return False
            self.presets[p["config"]["id"]] = copy.deepcopy(p["config"])
            return True
        if action == "cloneDeckConfigId":
            source = int(p.get("cloneFrom", 1))
            if source not in self.presets:
                return False
            new_id = next(self._ids)
            self.presets[new_id] = dict(copy.deepcopy(self.presets[source]), id=new_id, name=p["name"])
            return new_id
        if action == "setDeckConfigId":
            if p["configId"] not in self.presets:
                return False
            for deck in p["decks"]:
                self.deck_preset[deck] = p["configId"]
            return True
        if action == "getDeckStats":
            out = {}
            for name in p["decks"]:
                ids = [cid for cid, c in self.cards.items() if c["deck"] == name or c["deck"].startswith(name + "::")]
                new = sum(1 for cid in ids if self.cards[cid]["queue"] == 0)
                out[str(self.deck_ids[name])] = {"deck_id": self.deck_ids[name], "name": name, "new_count": new,
                                                 "learn_count": 0, "review_count": 0, "total_in_deck": len(ids)}
            return out

        # Note types
        if action == "createModel":
            if p["modelName"] in self.note_types:
                raise Exception("Model name already exists")
            self.note_types[p["modelName"]] = {
                "kind": "cloze" if p.get("isCloze") else "normal",
                "fields": list(p["inOrderFields"]),
                "css": p.get("css") or "",
                "templates": [{"name": t["Name"], "front": t["Front"], "back": t["Back"], "did": None} for t in p["cardTemplates"]],
            }
            return {"name": p["modelName"]}
        if action == "modelFieldNames":
            return list(self.note_types[p["modelName"]]["fields"])
        if action == "modelTemplates":
            return {t["name"]: {"Front": t["front"], "Back": t["back"]} for t in self.note_types[p["modelName"]]["templates"]}
        if action == "modelStyling":
            return {"css": self.note_types[p["modelName"]]["css"]}
        if action == "updateModelTemplates":
            model = self.note_types[p["model"]["name"]]
            for t in model["templates"]:
                patch = p["model"]["templates"].get(t["name"], {})
                t["front"] = patch.get("Front", t["front"])
                t["back"] = patch.get("Back", t["back"])
            return None
        if action == "updateModelStyling":
            self.note_types[p["model"]["name"]]["css"] = p["model"]["css"]
            return None
        if action == "modelFieldAdd":
            fields = self.note_types[p["modelName"]]["fields"]
            fields.insert(p.get("index", len(fields)), p["fieldName"])
            for note in self.notes.values():
                if note["model"] == p["modelName"]:
                    note["fields"].setdefault(p["fieldName"], "")
            return None
        if action == "modelTemplateAdd":
            t = p["template"]
            self.note_types[p["modelName"]]["templates"].append({"name": t["Name"], "front": t["Front"], "back": t["Back"], "did": None})
            return None

        # Media
        if action == "getMediaFilesNames":
            pattern = re.escape(p.get("pattern", "*")).replace(r"\*", ".*")
            return [name for name in self.media if re.fullmatch(pattern, name)]
        if action == "storeMediaFile":
            self.media[p["filename"]] = base64.b64decode(p["data"])
            return p["filename"]

        # Notes and cards
        if action == "canAddNotesWithErrorDetail":
            return [self._can_add(note) for note in p["notes"]]
        if action == "addNotes":
            checks = [self._can_add(note) for note in p["notes"]]
            if not all(c["canAdd"] for c in checks):
                raise Exception(str([c.get("error") for c in checks if not c["canAdd"]]))
            ids = []
            for note in p["notes"]:
                note_id = next(self._ids)
                self.notes[note_id] = {"model": note["modelName"], "fields": dict(note["fields"]),
                                       "tags": list(note.get("tags", [])), "deck": note["deckName"]}
                self._generate_cards(note_id)
                ids.append(note_id)
            return ids
        if action == "findNotes":
            return self._find_notes(p["query"])
        if action == "findCards":
            return self._find_cards(p["query"])
        if action == "notesInfo":
            out = []
            for note_id in p["notes"]:
                note = self.notes.get(note_id)
                if note is None:
                    out.append({})
                    continue
                fields = self.note_types[note["model"]]["fields"]
                out.append({"noteId": note_id, "modelName": note["model"], "tags": list(note["tags"]),
                            "fields": {name: {"value": note["fields"].get(name, ""), "order": i} for i, name in enumerate(fields)},
                            "cards": self.card_ids(note_id)})
            return out
        if action == "updateNoteFields":
            note = self.notes[p["note"]["id"]]
            note["fields"].update(p["note"]["fields"])
            self._generate_cards(p["note"]["id"])
            return None
        if action == "addTags":
            for note_id in p["notes"]:
                for tag in p["tags"].split():
                    if tag not in self.notes[note_id]["tags"]:
                        self.notes[note_id]["tags"].append(tag)
            return None
        if action == "removeTags":
            for note_id in p["notes"]:
                self.notes[note_id]["tags"] = [t for t in self.notes[note_id]["tags"] if t not in p["tags"].split()]
            return None
        if action == "deleteNotes":
            for note_id in p["notes"]:
                self.notes.pop(note_id, None)
                for cid in [c for c, card in self.cards.items() if card["note"] == note_id]:
                    del self.cards[cid]
            return None
        if action == "unsuspend":
            for cid in p["cards"]:
                self.cards[cid]["queue"] = 0
            return True
        if action == "getNumCardsReviewedToday":
            return 5
        if action == "getNumCardsReviewedByDay":
            return [["2026-10-29", 5], ["2026-10-28", 12]]
        if action == "getTags":
            return sorted({t for n in self.notes.values() for t in n["tags"]})
        if action == "cardsInfo":
            return [{"cardId": cid, "note": self.cards[cid]["note"], "ord": self.cards[cid]["ord"],
                     "deckName": self.cards[cid]["deck"], "queue": self.cards[cid]["queue"],
                     "interval": self.cards[cid]["ivl"], "lapses": self.cards[cid]["lapses"],
                     "modelName": self.notes[self.cards[cid]["note"]]["model"]} for cid in p["cards"]]
        if action == "changeDeck":
            self._create_deck(p["deck"])
            for cid in p["cards"]:
                self.cards[cid]["deck"] = p["deck"]
            return None
        if action == "suspend":
            changed = False
            for cid in p["cards"]:
                changed |= self.cards[cid]["queue"] != -1
                self.cards[cid]["queue"] = -1
            return changed
        raise Exception("unsupported action")

    def _first_field(self, model: str) -> str:
        return self.note_types[model]["fields"][0]

    def _can_add(self, note: dict) -> dict:
        model = note["modelName"]
        if model not in self.note_types:
            return {"canAdd": False, "error": "model was not found: " + model}
        if note["deckName"] not in self.deck_ids:
            return {"canAdd": False, "error": "deck was not found: " + note["deckName"]}
        first = self._first_field(model)
        value = plain(note["fields"].get(first, "")).lower()
        if not value:
            return {"canAdd": False, "error": "cannot create note because it is empty"}
        if any(n["model"] == model and plain(n["fields"].get(first, "")).lower() == value for n in self.notes.values()):
            return {"canAdd": False, "error": "cannot create note because it is a duplicate"}
        return {"canAdd": True}

    # A small subset of Anki's search syntax: AND by space, OR, parentheses and the terms the plugin uses.

    def _matches(self, card_id: int, tokens: list[str]) -> bool:
        position = 0

        def expr() -> bool:
            nonlocal position
            result = conj()
            while position < len(tokens) and tokens[position].upper() == "OR":
                position += 1
                right = conj()
                result = result or right
            return result

        def conj() -> bool:
            nonlocal position
            result = True
            while position < len(tokens) and tokens[position] != ")" and tokens[position].upper() != "OR":
                if tokens[position] == "(":
                    position += 1
                    value = expr()
                    position += 1  # ")"
                else:
                    value = self._term(card_id, _unquote(tokens[position]))
                    position += 1
                result = result and value
            return result

        return expr()

    def _term(self, card_id: int, term: str) -> bool:
        card = self.cards[card_id]
        note = self.notes[card["note"]]
        field, _, value = term.partition(":")
        value = _unquote(value)  # deck:"Den" — quotes around the value only
        key = field.lower()
        if key == "nid":
            return card["note"] in {int(n) for n in value.split(",")}
        if key == "deck":
            return _like(value, card["deck"]) or _like(value + "::*", card["deck"])
        if key == "tag":
            return any(_like(value, t) or _like(value + "::*", t) for t in note["tags"])
        if key == "note":
            return _like(value, note["model"])
        if key == "is" and value == "suspended":
            return card["queue"] == -1
        if key == "added":
            return True
        if key == "prop":
            match = re.fullmatch(r"(lapses|ivl)(>=|<=|=|>|<)(\d+)", value)
            actual = card["lapses" if match.group(1) == "lapses" else "ivl"]
            return eval(f"{actual}{'==' if match.group(2) == '=' else match.group(2)}{int(match.group(3))}")  # noqa: S307
        if value and field[:1].isupper():
            return _like(value, plain(note["fields"].get(field, "")))
        return any(term.lower() in plain(v).lower() for v in note["fields"].values())

    def _find_cards(self, query: str) -> list[int]:
        tokens = TOKEN.findall(query)
        return sorted(cid for cid in self.cards if self._matches(cid, tokens))

    def _find_notes(self, query: str) -> list[int]:
        if not query.strip():
            return sorted(self.notes)
        return sorted({self.cards[cid]["note"] for cid in self._find_cards(query)})

    # API v1

    def _v1(self, request: httpx.Request, body: dict) -> httpx.Response:
        if not self.v1:
            return httpx.Response(404)
        if self.key and request.headers.get("authorization") != f"Bearer {self.key}":
            return httpx.Response(401)
        method = body["method"]
        params = body.get("params", {})
        self.calls.append(method)

        def ok(result: Any) -> httpx.Response:
            return httpx.Response(200, json={"jsonrpc": "2.0", "id": body["id"], "result": result})

        def fail(kind: str, message: str) -> httpx.Response:
            return httpx.Response(
                200,
                json={"jsonrpc": "2.0", "id": body["id"], "error": {"code": 1000, "message": message, "data": {"type": kind}}},
            )

        if method == "api.describe":
            names = ["reviewer.get", "collection.sync", "operations.get", "noteTypes.create", "noteTypes.get", "noteTypes.editStructure"]
            return ok({"apiMajor": 1, "ankiVersion": "26.09.3", "methods": [{"name": n, "available": True, "reason": None} for n in names]})
        if method == "reviewer.get":
            return ok({"active": self.reviewing, "side": "question" if self.reviewing else "none"})
        if method == "collection.sync":
            if not self.logged_in:
                return fail("authenticationRequired", "Sync authentication is not configured.")
            operation_id = f"op{len(self._operations) + 1}"
            self._operations[operation_id] = list(self.sync_states)
            return ok({"operationId": operation_id, "method": "collection.sync", "session": None})
        if method == "operations.get":
            states = self._operations[params["operationId"]]
            state = states.pop(0) if len(states) > 1 else states[0]
            operation = {"operationId": params["operationId"], "method": "collection.sync", "state": state}
            if state == "succeeded":
                self.syncs += 1
                operation["result"] = {"collectionComplete": True, "mediaComplete": True}
            elif state in ("failed", "cancelled"):
                operation["error"] = {"code": 1012, "message": "network down", "data": {"type": self.sync_error_type}}
            return ok(operation)
        if method == "noteTypes.create":
            if params["name"] in self.note_types:
                return fail("conflict", "Note type already exists.")
            templates = []
            for t in params["templates"]:
                deck = t.get("deck")
                if deck and deck["name"] not in self.deck_ids:
                    return fail("notFound", "Deck not found.")
                templates.append({"name": t["name"], "front": t["questionHtml"], "back": t["answerHtml"],
                                  "did": self.deck_ids[deck["name"]] if deck else None})
            self.note_types[params["name"]] = {"kind": params.get("kind", "normal"), "fields": [f["name"] for f in params["fields"]],
                                               "css": params.get("css", ""), "templates": templates}
            return ok({"name": params["name"]})
        if method == "noteTypes.get":
            model = self.note_types[params["noteType"]["name"]]
            return ok({"name": params["noteType"]["name"], "templates": [
                {"name": t["name"], "deck": {"id": str(t["did"])} if t["did"] else None} for t in model["templates"]]})
        if method == "noteTypes.editStructure":
            model = self.note_types[params["noteType"]["name"]]
            for edit in params["edits"]:
                template = next(t for t in model["templates"] if t["name"] == edit["name"])
                deck = edit["patch"].get("deck")
                template["did"] = self.deck_ids[deck["name"]] if deck else None
            return ok({"name": params["noteType"]["name"]})
        return fail("methodNotFound", f"unknown method {method}")
