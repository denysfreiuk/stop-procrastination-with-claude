---
description: Картки Anki з коду твого проєкту — ідіоми, API, концепції, типові помилки (не дрібниці). Читає файл або фрагмент, робить картки AC Code і Concept.
argument-hint: "<шлях до файлу або фрагмент коду> [--auto]"
disable-model-invocation: true
allowed-tools:
  - Read
  - Glob
  - Grep
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

# /anki-code

Вхід: $ARGUMENTS

Процес, правила якості, типи нотаток, колоди й теги — у скілі `anki-cards`: прочитай `${CLAUDE_PLUGIN_ROOT}/skills/anki-cards/SKILL.md` і потрібні довідки з `${CLAUDE_PLUGIN_ROOT}/skills/anki-cards/references/`, якщо ще не читав їх у цій розмові. Дотримуйся їх суворо.

1. Шлях — прочитай файл (Read; за потреби сусідні файли для контексту). Фрагмент — працюй з ним.
2. **Ніколи не переносити в картки секрети**: ключі API, токени, паролі, URL з креденшалами, особисті дані. Заміни на `<KEY>`.
3. Відбери, що варто пам'ятати: неочевидні ідіоми й API, концепції, чому код написано саме так, типові помилки. Тривіальне і специфічне лише для цього проєкту пропускай.
4. Типи: `code` — «що виведе / яка форма / що вставити замість ___» (код ≤ 12 рядків, лише суть); `concept` — «чому / коли / чим відрізняється».
5. Колода: код про ML (PyTorch, numpy для моделей) → `ML`; про мову чи інструмент → `Code::<Мова>`. Тег `lang::<мова>` завжди, `source::<проєкт-або-файл>`.
6. Превʼю → питання → `add_notes` → звіт.
