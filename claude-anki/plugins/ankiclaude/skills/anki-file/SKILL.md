---
description: Картки Anki з файлу — PDF лекції, Markdown, конспект, стаття. Читає файл, відбирає найважливіше, показує превʼю і додає.
argument-hint: "<шлях до файлу> [сторінки, напр. 5-12] [--auto]"
disable-model-invocation: true
allowed-tools:
  - Read
  - Glob
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

# /anki-file

Аргументи: $ARGUMENTS

Процес, правила якості, типи нотаток, колоди й теги — у скілі `anki-cards`: прочитай `${CLAUDE_PLUGIN_ROOT}/skills/anki-cards/SKILL.md` і потрібні довідки з `${CLAUDE_PLUGIN_ROOT}/skills/anki-cards/references/`, якщо ще не читав їх у цій розмові. Дотримуйся їх суворо.

1. Прочитай файл інструментом Read. PDF понад 10 сторінок читай частинами (`pages`); якщо сторінки не вказано, а файл великий — візьми зміст і запропонуй, які розділи взяти.
2. `Source` і тег `source::…` — з назви курсу, лекції чи файлу (латиницею kebab-case, напр. `source::cs231n-lecture-3`).
3. Спершу 3–6 рядків: про що матеріал і що з нього варто закріпити. Складне поясни простіше, ніж у джерелі.
4. Відбери найважливіше (не більше `max_cards_per_batch` за раз; для великого файлу запропонуй продовжити наступною порцією).
5. Далі — кроки 4–6 процесу: `check_duplicates` → превʼю і питання → `add_notes` → звіт.
