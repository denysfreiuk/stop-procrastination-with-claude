---
description: Картки Anki з будь-якого тексту чи теми — превʼю, перевірка дублікатів, додавання пакетом. Прапорці --auto (без підтвердження) і --known (слова вже знайомі).
argument-hint: "<текст або тема> [--auto] [--known]"
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

# /anki-add

Матеріал: $ARGUMENTS

Процес, правила якості, типи нотаток, колоди й теги — у скілі `anki-cards`: прочитай `${CLAUDE_PLUGIN_ROOT}/skills/anki-cards/SKILL.md` і потрібні довідки з `${CLAUDE_PLUGIN_ROOT}/skills/anki-cards/references/`, якщо ще не читав їх у цій розмові. Дотримуйся їх суворо.

1. Якщо аргументів немає — спитай, з чого робити картки.
2. Визнач, що це: готовий матеріал (текст, конспект, пояснення) чи лише тема. Для теми — коротко поясни ключове і зроби картки з загальновідомих фактів; сумнівне — `status::to-check`.
3. Обери тип нотатки для кожного факту (concept / cloze / formula / code / vocab / distinction), колоду й теги.
4. Далі — кроки 4–6 процесу: `check_duplicates` → превʼю таблицею і питання → `add_notes` → короткий звіт.
