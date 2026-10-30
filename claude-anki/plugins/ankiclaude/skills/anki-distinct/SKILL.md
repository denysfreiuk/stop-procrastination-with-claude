---
description: Картки Anki на розрізнення схожих англійських слів (make/do, say/tell, borrow/lend, affect/effect, actually/currently…) — кілька речень, де правильні різні варіанти.
argument-hint: "<пара або група слів, напр. make/do>"
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

# /anki-distinct

Пара: $ARGUMENTS

Процес, правила якості, типи нотаток, колоди й теги — у скілі `anki-cards`: прочитай `${CLAUDE_PLUGIN_ROOT}/skills/anki-cards/SKILL.md` і потрібні довідки з `${CLAUDE_PLUGIN_ROOT}/skills/anki-cards/references/`, якщо ще не читав їх у цій розмові. Дотримуйся їх суворо.

1. Сформулюй правило розрізнення в 1–2 рядки простими словами, з типовою помилкою українців.
2. Зроби 2–4 нотатки `distinction`: у кожній `Sentence` з `___` і варіантами в дужках; `Answer` — точна форма, що підходить. Правильні відповіді мають бути **різні** (і перше, і друге слово), контексти — різні й живі.
3. `Why` — 1–2 рядки, чому саме цей варіант. `Pair` — «make / do». Теги: `topic::english::confusables`, `type::distinction`, рівень.
4. Якщо якогось слова пари ще немає як vocab (`find_notes`) — запропонуй додати і його.
5. Превʼю → питання → `add_notes` → звіт.
