---
description: Англійські слова в Anki (AC Vocab) — зі списку через кому або з тексту (сам обирає корисні слова під твій рівень), з живими прикладами, WhyThisWord і пропозицією, які слова зробити активними.
argument-hint: "<слова через кому або текст> [--auto] [--known]"
disable-model-invocation: true
allowed-tools:
  - mcp__plugin_ankiclaude_anki__check_connection
  - mcp__plugin_ankiclaude_anki__get_config
  - mcp__plugin_ankiclaude_anki__review_status
  - mcp__plugin_ankiclaude_anki__list_decks
  - mcp__plugin_ankiclaude_anki__list_note_types
  - mcp__plugin_ankiclaude_anki__find_notes
  - mcp__plugin_ankiclaude_anki__check_duplicates
  - mcp__plugin_ankiclaude_anki__add_notes
  - mcp__plugin_ankiclaude_anki__sync
---

# /anki-vocab

Вхід: $ARGUMENTS

Процес, правила якості, типи нотаток, колоди й теги — у скілі `anki-cards`: прочитай `${CLAUDE_PLUGIN_ROOT}/skills/anki-cards/SKILL.md` і довідки з `${CLAUDE_PLUGIN_ROOT}/skills/anki-cards/references/`, особливо `vocab-guide.md`, якщо ще не читав їх у цій розмові. Дотримуйся їх суворо.

1. Список через кому → по нотатці на слово (у словниковій формі). Текст → обери слова за правилами вибору з `vocab-guide.md` (рівень — з `get_config`), не більше `max_cards_per_batch`.
2. Слово з кількома значеннями — візьми значення з контексту тексту або спитай. Одна нотатка = одне значення.
3. Для кожного слова: IPA, частина мови, Forms (лише неправильні), MeaningEN, TranslationUA, 2–3 живі приклади з `<b>словом</b>` (хоча б один у словниковій формі), WhyThisWord, Collocations, Register, Hint.
4. Active — запропонуй для кожного слова з коротким «чому». DrillForms — лише для неправильних форм, які реально плутаються.
5. Пари, які легко сплутати, — запропонуй ще картки `distinction`.
6. Превʼю: № | слово | переклад | приклад (скорочено) | Active | теги. Питання: «Додати все / змінити № … / видалити № … / зробити активними № …?»
7. `add_notes` (з `known=true`, якщо є `--known`) → звіт: що додано і які картки UA→EN чекають, поки закріпиться EN→UA.
