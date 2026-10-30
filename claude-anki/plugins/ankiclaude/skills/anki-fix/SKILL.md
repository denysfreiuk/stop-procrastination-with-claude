---
description: Покращення наявних карток Anki за правилами якості — знаходить картки пошуком Anki, показує «було → стане» і після згоди виправляє.
argument-hint: "<пошуковий запит Anki, напр. tag:status::to-check>"
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
  - mcp__plugin_ankiclaude_anki__update_note_fields
  - mcp__plugin_ankiclaude_anki__add_tags
  - mcp__plugin_ankiclaude_anki__remove_tags
---

# /anki-fix

Запит: $ARGUMENTS

Процес, правила якості, типи нотаток, колоди й теги — у скілі `anki-cards`: прочитай `${CLAUDE_PLUGIN_ROOT}/skills/anki-cards/SKILL.md` і довідки з `${CLAUDE_PLUGIN_ROOT}/skills/anki-cards/references/`, особливо `quality-rules.md`, якщо ще не читав їх у цій розмові. Дотримуйся їх суворо.

1. `find_notes` з запитом. Без запиту — спитай, що перевірити (корисне: `tag:status::to-check`, `added:7`, `deck:"<корінь>::ML"`).
2. Перевір кожну нотатку за 13 правилами. Що добре — не чіпай.
3. Таблиця: № | картка | що не так | було → стане. Для «розбити» — нові картки окремим списком.
4. Питання: «Застосувати все / лише № … / пропустити № …?» Понад 20 нотаток — масова зміна: покажи план і отримай явне «так».
5. Після згоди: `update_note_fields` (по одній), нові — `add_notes`; зніми `status::to-check`, якщо перевірив факти. Видалення — лише `delete_notes` з токеном після окремого «так».
