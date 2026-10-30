"""Specifications of the AC note types: fields, templates, CSS, deck per template.

Templates live in templates/*.html with three kinds of build-time placeholders
(Anki's own {{…}} syntax is left alone):
  [[ac:examples]]       hidden Example1–3 block the vocab script picks from
  [[ac:script NAME]]    inline <script> with js/NAME.js (vocab also gets Anki-Persistence)
  [[ac:tts FIELD]]      Anki text-to-speech of FIELD, or nothing when speech is turned off
  [[label:KEY]]         a label in the configured explanation language
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from functools import cache
from pathlib import Path

from .. import __version__

HERE = Path(__file__).resolve().parent
VERSION_MARKER = re.compile(r"/\* ankiclaude (\d+(?:\.\d+)*) \*/")
HIGHLIGHT_VERSION = "11.11.1"
HIGHLIGHT_MEDIA = f"_ac_highlight-{HIGHLIGHT_VERSION}.min.js"

LABELS = {
    "uk": {
        "why_word": "Чому саме це слово",
        "collocations": "Сполучення",
        "hint": "Підказка",
        "type_lemma": "Введи словникову форму",
        "name_forms": "Назви форми",
        "explanation": "Чому так",
        "example": "Приклад",
        "write_formula": "Запиши формулу",
        "terms": "Що означає",
        "when": "Коли використовувати",
        "choose": "Яке слово підходить?",
    },
    "en": {
        "why_word": "Why this word",
        "collocations": "Collocations",
        "hint": "Hint",
        "type_lemma": "Type the dictionary form",
        "name_forms": "Name the forms",
        "explanation": "Why",
        "example": "Example",
        "write_formula": "Write the formula",
        "terms": "Terms",
        "when": "When to use",
        "choose": "Which word fits?",
    },
}

EXAMPLES_BLOCK = (
    '<div class="ac-examples">'
    '<div class="ac-ex">{{Example1}}</div>'
    '<div class="ac-ex">{{Example2}}</div>'
    '<div class="ac-ex">{{Example3}}</div>'
    "</div>"
)

ENGLISH = "English"
EN_UA = "English::EN-UA"
UA_EN = "English::UA-EN"
DISTINCTIONS = "English::Distinctions"


@dataclass(frozen=True)
class TemplateSpec:
    name: str
    front: str
    back: str
    deck: str | None  # deck override relative to the root deck


@dataclass(frozen=True)
class NoteTypeSpec:
    key: str
    name: str
    kind: str  # "normal" or "cloze"
    fields: tuple[str, ...]
    required: tuple[str, ...]
    templates: tuple[TemplateSpec, ...]
    css: str
    deck: str | None  # where notes of this type always go; None: the caller chooses

    @property
    def fingerprint(self) -> str:
        data = "\0".join([self.css, *(t.front + t.back for t in self.templates)])
        return hashlib.sha256(data.encode()).hexdigest()[:12]


@cache
def _read(relative: str) -> str:
    return (HERE / relative).read_text(encoding="utf-8")


def _script(name: str) -> str:
    code = _read(f"js/{name}.js").replace("[[ac:highlight-file]]", HIGHLIGHT_MEDIA)
    if name == "vocab":
        code = _read("vendor/anki-persistence.js") + "\n" + code
    if "{{" in code or "}}" in code:
        # Anki parses {{…}} everywhere in a template, <script> included.
        raise ValueError(f"js/{name}.js contains '{{{{' or '}}}}', which breaks Anki templates")
    return f"<script>\n{code}\n</script>"


def render_template(text: str, language: str, tts: bool = True, tts_lang: str = "en_US") -> str:
    labels = LABELS.get(language, LABELS["en"])

    def label(match: re.Match) -> str:
        if match.group(1) not in labels:
            raise ValueError(f"unknown template label {match.group(0)}")
        return labels[match.group(1)]

    text = text.replace("[[ac:examples]]", EXAMPLES_BLOCK)
    text = re.sub(
        r"[ \t]*\[\[ac:tts (\w+)\]\]\n?",
        lambda m: f'  <div class="ac-tts">{{{{tts {tts_lang}:{m.group(1)}}}}}</div>\n' if tts else "",
        text,
    )
    text = re.sub(r"\[\[ac:script (\w+)\]\]", lambda m: _script(m.group(1)), text)
    text = re.sub(r"\[\[label:(\w+)\]\]", label, text)
    leftover = re.search(r"\[\[(ac|label):[^\]]*\]\]", text)
    if leftover:
        raise ValueError(f"unknown template placeholder {leftover.group(0)}")
    return text.strip() + "\n"


def made_by(css: str) -> str | None:
    """The plugin version recorded in a note type's CSS, or None for types from before 0.4.2."""
    match = VERSION_MARKER.search(css)
    return match.group(1) if match else None


def build_specs(language: str = "uk", tts: bool = True, tts_lang: str = "en_US") -> dict[str, NoteTypeSpec]:
    # The version marker lets a newer plugin update the types and keeps an older one from rolling them back.
    css = f"/* ankiclaude {__version__} */\n" + _read("style.css")

    def _template(name: str, file: str, deck: str | None, language: str) -> TemplateSpec:
        return TemplateSpec(
            name=name,
            front=render_template(_read(f"templates/{file}.front.html"), language, tts, tts_lang),
            back=render_template(_read(f"templates/{file}.back.html"), language, tts, tts_lang),
            deck=deck,
        )

    def spec(key, name, fields, required, templates, kind="normal", deck=None):
        return NoteTypeSpec(key, name, kind, tuple(fields), tuple(required), tuple(templates), css, deck)

    return {
        s.key: s
        for s in (
            spec(
                "concept",
                "AC Concept",
                ["Front", "Back", "Explanation", "Example", "Source"],
                ["Front", "Back"],
                [_template("Concept", "concept", None, language)],
            ),
            spec(
                "cloze",
                "AC Cloze",
                ["Text", "Extra", "Source"],
                ["Text"],
                [_template("Cloze", "cloze", None, language)],
                kind="cloze",
            ),
            spec(
                "formula",
                "AC Formula",
                ["Name", "Formula", "MeaningOfTerms", "WhenToUse", "Example", "Source"],
                ["Name", "Formula"],
                [_template("Formula", "formula", None, language)],
            ),
            spec(
                "code",
                "AC Code",
                ["Prompt", "Code", "Answer", "Explanation", "Language", "Source"],
                ["Prompt", "Code", "Answer"],
                [_template("Code", "code", None, language)],
            ),
            spec(
                "vocab",
                "AC Vocab",
                [
                    "Word", "IPA", "PartOfSpeech", "Forms", "MeaningEN", "TranslationUA",
                    "Example1", "Example2", "Example3", "WhyThisWord", "Collocations",
                    "Register", "Hint", "Active", "DrillForms", "Source",
                ],
                ["Word", "MeaningEN", "TranslationUA"],
                [
                    _template("Recognition", "vocab.recognition", EN_UA, language),
                    _template("Production", "vocab.production", UA_EN, language),
                    _template("Forms", "vocab.forms", UA_EN, language),
                ],
                deck=EN_UA,
            ),
            spec(
                "distinction",
                "AC Distinction",
                ["Sentence", "Answer", "Why", "Pair", "Source"],
                ["Sentence", "Answer", "Pair"],
                [_template("Distinction", "distinction", DISTINCTIONS, language)],
                deck=DISTINCTIONS,
            ),
        )
    }


def media_files() -> dict[str, Path]:
    """Files ensure_note_types stores in the collection's media folder."""
    return {HIGHLIGHT_MEDIA: HERE / "vendor" / f"highlight-{HIGHLIGHT_VERSION}.min.js"}
