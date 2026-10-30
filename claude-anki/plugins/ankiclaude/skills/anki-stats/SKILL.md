---
description: Коротка статистика Anki — що чекає сьогодні, скільки повторено, проблемні й відкладені картки, теми — і що варто підтягнути.
disable-model-invocation: true
allowed-tools:
  - mcp__plugin_ankiclaude_anki__check_connection
  - mcp__plugin_ankiclaude_anki__get_config
  - mcp__plugin_ankiclaude_anki__get_stats
  - mcp__plugin_ankiclaude_anki__get_leeches
  - mcp__plugin_ankiclaude_anki__list_decks
---

# /anki-stats

1. `get_stats`.
2. Відповідь — коротко:
   - **Сьогодні**: нових / у навчанні / на повторення; повторено сьогодні; динаміка за 7 днів одним рядком.
   - **Колекція**: нотаток і карток, по колодах (з лімітами нових на день).
   - **Увага**: leech, призупинені, `status::to-check`, слова, що чекають UA→EN чи форм.
   - **Топ тем** за тегами.
3. 2–4 поради з командами: багато leech → `/anki-leeches`; є `status::to-check` → `/anki-fix tag:status::to-check`; закріплені слова чекають → `/anki-promote`; великий борг повторень → кілька днів не додавати нових; тема без карток «чому» → `/anki-add`.
