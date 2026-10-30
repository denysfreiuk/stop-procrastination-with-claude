---
description: Розморожує відкладені картки слів — UA→EN, коли закріпилась EN→UA, і картки форм, коли закріпилась UA→EN. Синхронізує до і після, щоб врахувати повторення з телефону.
argument-hint: "[--dry-run]"
disable-model-invocation: true
allowed-tools:
  - mcp__plugin_ankiclaude_anki__check_connection
  - mcp__plugin_ankiclaude_anki__get_config
  - mcp__plugin_ankiclaude_anki__review_status
  - mcp__plugin_ankiclaude_anki__promote_cards
---

# /anki-promote

Аргументи: $ARGUMENTS

1. `promote_cards` (з `dry_run=true`, якщо є `--dry-run`).
2. За `status`:
   - `ok` — «Розморожено N: …» списком слів і карток; скільки ще чекає, і 3–5 найближчих (слово, інтервал зараз / потрібно `threshold_days`). Якщо друга синхронізація не вдалась — скажи.
   - `deferred` — користувач саме повторює картки в desktop-Anki; запропонуй запустити після повторення. `force=true` — лише якщо він прямо попросить.
   - `sync_failed` — нічого не розморожено; передай причину і підказку з `message`.
3. Нагадай одним рядком: розморожені картки йдуть як нові в межах денного ліміту колоди UA-EN.
