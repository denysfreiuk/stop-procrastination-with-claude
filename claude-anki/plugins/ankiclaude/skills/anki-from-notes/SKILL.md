---
description: Картки Anki зі щоденника Obsidian — бере «Що вивчив» і «Нові слова» з нотаток, де anki_done false, показує превʼю, додає і ставить anki_done true.
argument-hint: "[дата або період, напр. 2026-10-30 або 2026-10-24..2026-10-30; без дати — усі необроблені] [--auto] [--known]"
disable-model-invocation: true
allowed-tools:
  - mcp__plugin_ankiclaude_anki__read_journal
  - mcp__plugin_ankiclaude_anki__mark_anki_done
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

# /anki-from-notes

Аргументи: $ARGUMENTS

Процес, правила якості, типи нотаток, колоди й теги — у скілі `anki-cards`: прочитай `${CLAUDE_PLUGIN_ROOT}/skills/anki-cards/SKILL.md` і потрібні довідки з `${CLAUDE_PLUGIN_ROOT}/skills/anki-cards/references/`, якщо ще не читав їх у цій розмові. Дотримуйся їх суворо.

1. `get_config`, потім `read_journal` з `only_pending_anki=true`; дату передай як `date_from` і `date_to`, період `a..b` — як `date_from=a`, `date_to=b`.
2. Якщо днів немає — скажи «усе вже оброблено» і зупинись. Інакше одним рядком: які дні беру, скільки слів і записів.
3. **«Нові слова»** — картки `vocab` за `vocab-guide.md`. Рядок `- слово — контекст` означає, де користувач зустрів слово. Значення бери саме те, що в цьому контексті. Якщо контекст — речення з цим словом, зроби його одним із прикладів (слово в `<b>…</b>`, текст не переписуй), а решту прикладів додай свої. Звідки воно (серіал, стаття, лекція) — у `Source`. Кілька рядків з одним словом — одна нотатка з кількома прикладами. **«Що вивчив»** — за типом матеріалу (`concept`, `cloze`, `formula`, `code`). Запис занадто короткий чи незрозумілий — не вигадуй: познач його в превʼю й спитай. Якщо запис складний, спершу коротко поясни суть.
4. `source::journal` як джерело (тег) і дата дня в полі `Source`, де воно є.
5. Не більше `max_cards_per_batch` нотаток за раз. Якщо матеріалу більше, бери найдавніші дні й запропонуй продовжити наступним запуском.
6. Далі — кроки 4–6 процесу: `check_duplicates` → превʼю і питання → `add_notes` → звіт і синхронізація. `--auto` і `--known` працюють як звичайно. Новий запис у вже обробленому дні знову робить його необробленим, тому те, що вже є в Anki, `check_duplicates` відсіє: у превʼю такого не показуй, лише скажи скільки.
7. **Тільки після цього** `mark_anki_done` для днів, чий матеріал оброблено повністю: кожен запис або додано, або він дублікат, або користувач явно відхилив. Дні, що лишились на наступну порцію, не познач. Якщо користувач відмовився від превʼю, не познач нічого.
8. Звіт: скільки карток додано, які дні позначені, що лишилось.
