---
description: Розбір проблемних карток Anki (leech, часто забуваються) — діагноз причини і виправлення — переписати, розбити, додати контекст або картку на розрізнення.
argument-hint: "[мінімум забувань, за замовчуванням 4]"
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
  - mcp__plugin_ankiclaude_anki__get_leeches
  - mcp__plugin_ankiclaude_anki__update_note_fields
  - mcp__plugin_ankiclaude_anki__remove_tags
---

# /anki-leeches

Аргументи: $ARGUMENTS (число — поріг забувань для `get_leeches`).

Процес, правила якості, типи нотаток, колоди й теги — у скілі `anki-cards`: прочитай `${CLAUDE_PLUGIN_ROOT}/skills/anki-cards/SKILL.md` і потрібні довідки з `${CLAUDE_PLUGIN_ROOT}/skills/anki-cards/references/`, якщо ще не читав їх у цій розмові. Дотримуйся їх суворо.

1. `get_leeches` (з порогом, якщо вказано). Порожньо — порадій і завершуй.
2. Для кожної нотатки (до 10 за раз) визнач причину одним словом:
   - **неоднозначність** — кілька правильних відповідей; **інтерференція** — плутається зі схожим;
   - **забагато** — список чи кілька фактів; **без контексту** — абстрактно, немає прикладу;
   - **не зрозуміло** — не зрозумілий сам матеріал (тоді спершу поясни).
3. Запропонуй конкретне виправлення: переписати (покажи «було → стане»), розбити на кілька (нові — `add_notes`, стару — видалити чи залишити, на вибір користувача), додати приклад чи Hint, додати `distinction`.
4. Таблиця: № | картка | причина | що зробити. Питання: «Застосувати все / лише № … / пропустити № …?»
5. Після згоди: `update_note_fields` / `add_notes`; потім зніми тег `leech` з виправлених (`remove_tags`). Видалення — лише `delete_notes` з токеном після окремого «так».
