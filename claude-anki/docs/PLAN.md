# Anki&Claude — план і журнал рішень

Статус (2026-10-29): етапи 1–5 зроблено (версія 0.4.0). Лишилось: перевірка на AnkiDroid і macOS,
тест синхронізації під час повторення, публікація репозиторію. Як користуватись — [README](../README.md).

### Знахідки етапів 4–5
- Хуки: SessionStart розморожує лише коли є відкладені картки і не частіше ніж раз на 3 год; Stop
  нагадує про картки не частіше ніж раз на 3 год. Плагін увімкнено для всіх проєктів, тож інакше
  хуки заважали б звичайним сесіям. Anki закрита — хуки мовчать.
- `auto_sync=false` — розморожування працює локально, без AnkiWeb.
- Видалення завжди, а теги понад 20 нотаток — лише з одноразовим `confirm_token`, прив'язаним до аргументів.
- Перевірено на живій Anki: розморожена картка стає новою і підпадає під денний ліміт колоди
  (ліміт 1 → Anki показує 1 нову з 3).
- Озвучка: мова — налаштування `tts_lang` (`en_US` / `en_GB`).
- JS шаблонів покрито тестами в jsdom (`tests/js`), Python — на 3.12 і 3.14; CI: GitHub Actions.

### Рішення, прийняті з тобою
- Python **3.14** (не 3.12), uv, FastMCP.
- Конфіг — `userConfig` плагіна, `.env` як запасний варіант.
- UA→EN: вводиш словникову форму (`go`), поруч підказка «введи словникову форму»; на звороті
  в реченні виділена реальна форма (`went`); нове поле `Forms` (go – went – gone).
- Озвучка `{{tts en_US:Word}}` — так.
- Ліміти нових: EN-UA 10, UA-EN 7, Distinctions 3, ML 2, Uni 2, Code 2. Стеля на `Den` = сума
  підколод (зараз 26) і перераховується сама, коли змінюєш ліміт підколоди — тобто ніколи не «з'їдає»
  ліміт. Повторення не обмежуються (9999), щоб не накопичувався борг.
- Колоди під мови/теми/предмети створюються ліниво — лише коли з'являється перша картка
  (`Den::Code::<мова>`, `Den::Uni::<предмет>`).
- Відкладений Production з `/anki-promote` — так (деталі в §5).
- Повторюєш і на desktop, і на AnkiDroid → sync перед і після promote, автоматичний sync після
  додавання/редагування; плагін не заважає, якщо ти саме повторюєш у desktop-Anki (§3).
- GitHub: публічний репо з MIT на етапі 5; комітимо з етапу 2.

### Знахідки етапу 2 (2026-10-29)
- **AnkiConnect 2026 має два API**: класичний v6 (`POST /`) і новий v1 (JSON-RPC 2.0, `POST /api/v1`,
  94 методи). Плагін працює через v6 (є в усіх), а v1 бере, лише якщо він є, для того, чого v6 не вміє:
  sync зі статусом операції, `reviewer.get`, а на етапі 3 — **Deck Override у шаблонах**
  (`noteTypes.create/update` приймають `deck` для шаблону). Без v1 лишається маршрутизація через `changeDeck`.
- **v6 `sync` не чекає завершення**: повертається одразу, і помилку не видно. Тому без v1 sync іде
  всередині `multi`, де AnkiConnect його дочікується. З v1 — `collection.sync` + опитування `operations.get`.
- **Повна синхронізація**: AnkiConnect сам показує в Anki діалог Upload/Download (стан `waitingForUser`).
  Плагін це розпізнає і просить тебе обрати у вікні Anki. Зміна **структури** типу нотатки (нове поле,
  шаблон) вимагає повної синхронізації, тому всі поля закладаю відразу; HTML/CSS шаблонів змінюю вільно.
- **Smart App Control (Windows 11)** блокує непідписані `.exe`, які uv кладе у `.venv`. Тому сервер не
  використовує venv: `launch.py` (лише stdlib) один раз ставить залежності через `uv pip install --target`
  у `${CLAUDE_PLUGIN_DATA}` і запускає їх базовим Python. Перший запуск ~6 с, далі ~2,5 с.
- **`mcp` SDK 2.x**: FastMCP перейменовано на `MCPServer` (`mcp.server.mcpserver`) — це він.
- Налаштування без діалогу: `claude plugin install ankiclaude@ankiclaude --config root_deck=Den`,
  змінити потім: `/plugin` → Configure (`claude plugin configure` є лише з Claude Code 2.1.285; у тебе 2.1.274).
- Плагін з маркетплейсу-папки твій Claude Code копіює в кеш (`~/.claude/plugins/cache/...`), а не читає
  з проєкту. Тому кожен етап, який ти тестуєш, отримує нову `version` у plugin.json, і ти оновлюєш плагін
  командою `claude plugin update ankiclaude@ankiclaude` + новий чат.
- Тести лежать у `plugins/ankiclaude/server/tests/`; запуск: `uv run python -m pytest`.

### Знахідки етапу 3 (2026-10-29)
- Колоди, пресети `AC · …` і 6 типів нотаток створені у твоїй Anki; повторний `ensure_note_types`
  нічого не змінює. Створення типів нотаток і колод **не** вимагає повної синхронізації (перевірено).
- Deck Override у шаблонах (API v1) працює: Recognition → EN-UA, Production і Forms → UA-EN,
  Distinction → Distinctions — без `changeDeck`. Без v1 картки переносить `add_notes`.
- `addNotes` у новому AnkiConnect атомарний: одна погана нотатка зриває весь пакет, тому спершу
  `canAddNotesWithErrorDetail`, потім додаються лише придатні.
- JS шаблонів перевірено в браузері на картках, які відрендерила сама Anki (`cards.render`), у режимі
  «лицьова → зворот на одній сторінці», як в Anki desktop: 40/40 той самий приклад на звороті для всіх
  vocab-карток; вибір випадковий; Production бере приклади з базовою формою; Forms — з іншою формою.
- `tools/preview.py` — галерея карток (телефон/комп'ютер, світла/нічна) з живої Anki, для перевірки
  дизайну і скріншотів README.
- Нове поле `Source` додано також у Formula і Code (щоб не міняти структуру пізніше).
- **Озвучка на Windows**: Anki 26 бере голоси через WinRT; якщо не встановлено жодного OneCore-голосу
  (так буває з українською Windows — для неї вбудованого голосу немає), кожен `{{tts}}` дає вікно помилки
  `all_tts_voices … 0x80070002`. Лікування: Параметри → Час і мова → Мовлення → Додати голоси →
  English (United States). У плагіні є `tts` (за замовчуванням увімкнено), щоб за потреби вимкнути.
  README: розділ «Усунення проблем».
- `sync` під час повторення справді відкладається (перевірено на твоїй Anki).

## 0. Що я перевірив перед планом

### Claude Code (документація code.claude.com, CLI у тебе — v2.1.274)
- Плагін = папка з `.claude-plugin/plugin.json` (маніфест), `skills/<name>/SKILL.md`,
  `hooks/hooks.json`, `.mcp.json` або `mcpServers` у маніфесті.
- **Slash-команди тепер — це скіли.** `skills/anki-add/SKILL.md` дає `/anki-add`
  (повна форма `/ankiclaude:anki-add`, коротка працює, якщо немає конфлікту).
  Папка `commands/` ще підтримується, але для нових плагінів радять `skills/`.
- Фронтматер скіла: `description`, `argument-hint`, `allowed-tools`,
  `disable-model-invocation`, `$ARGUMENTS`, `${CLAUDE_SKILL_DIR}`, `${CLAUDE_PLUGIN_ROOT}`.
- MCP у плагіні стартує автоматично; змінні `${CLAUDE_PLUGIN_ROOT}` (код, міняється при
  оновленні) і `${CLAUDE_PLUGIN_DATA}` (`~/.claude/plugins/data/<id>/`, переживає оновлення —
  туди піде `.venv`). Інструменти називаються `mcp__plugin_<плагін>_<сервер>__<tool>`.
- **`userConfig`** у маніфесті: Claude Code сам питає значення при ввімкненні плагіна,
  зберігає в settings (секрети — у системному сховищі), підставляє в env MCP-сервера через
  `${user_config.KEY}`; змінюється потім у `/config`. Це зручніше для друзів, ніж ручний `.env`.
- Хуки: `Stop`, `Notification`, `SessionStart`…; exec-форма (`command` + `args`) без shell —
  кросплатформенно; JSON-відповідь `systemMessage` показується користувачу.
- Поширення: `.claude-plugin/marketplace.json` у корені GitHub-репо →
  `claude plugin marketplace add <user>/<repo>` + `claude plugin install ankiclaude@ankiclaude`.
- Ім'я плагіна: заборонено `claude-*`; `claude` як окреме слово (`anki-claude`) дає warning.
  Тому `name: "ankiclaude"`, `displayName: "Anki&Claude"`.

### AnkiConnect (add-on 2055492159, API v6, остання версія 25.11.9.0)
- Є все потрібне: `createModel` (кілька шаблонів, CSS, `isCloze`), `updateModelTemplates`,
  `updateModelStyling`, `modelFieldAdd`, `modelTemplateAdd`, `getDeckConfig`/`saveDeckConfig`/
  `cloneDeckConfigId`/`setDeckConfigId`, `canAddNotesWithErrorDetail`, `addNotes`,
  `updateNoteFields`, `addTags`/`removeTags`, `findNotes`/`notesInfo`/`findCards`/`cardsInfo`,
  `changeDeck`, `getDeckStats`, `getNumCardsReviewedByDay`, `storeMediaFile`, `sync`, `multi`.
- ⚠️ **Deck Override через AnkiConnect виставити НЕ можна** — жодна дія не пише поле `did`
  шаблону. Рішення (два шари):
  1. MCP-сервер сам маршрутизує картки: після `addNotes`/`updateNoteFields` знаходить картки
     шаблону `Production` і переносить їх у `UA-EN` через `changeDeck`. Працює завжди.
  2. README: один раз вручну поставити Deck Override у Anki (Cards → Options) — тоді й
     ручне додавання в Anki працюватиме правильно. Я перевірив код Anki (`rslib/.../cardgen.rs`):
     override шаблону має пріоритет над колодою, яку передає `addNote`, тож шари не конфліктують.
- Ліміти в Anki (мануал): **пресети спільні між колодами** → для кожної колоди треба окремий
  пресет (`cloneDeckConfigId`), інакше зміна ліміту EN-UA змінить і ML. Ліміти батьківської
  колоди за замовчуванням не діють, якщо клікаєш на підколоду (є опція «Limits start from top»).
- Стан Anki на старті (2026-10-29): Anki 26.09 з AnkiConnect (API 6, 122 дії), колекція порожня.
- Інтерфейс Anki український → стандартні назви локалізовані («Типовий», «Базовий»…).
  Плагін ніколи не покладається на назву `Default`/`Basic` — працює зі своїми типами і колодами.
- У пресеті через AnkiConnect видно `new.perDay`, `rev.perDay`, `new.bury`, `newGatherPriority`,
  `desiredRetention`, але **немає** `applyAllParentLimits` («Limits start from top») — його
  через API не виставити, лише вручну (див. §4).

## 1. Структура репозиторію

```
anki-claude/                          ← GitHub-репо = маркетплейс
├── .claude-plugin/marketplace.json   ← name: ankiclaude, plugins: [./plugins/ankiclaude]
├── plugins/ankiclaude/
│   ├── .claude-plugin/plugin.json    ← metadata, userConfig, mcpServers
│   ├── skills/
│   │   ├── anki-cards/               ← ГОЛОВНИЙ скіл (Claude вантажить сам, коли просиш картки)
│   │   │   ├── SKILL.md              ← робочий процес: вхід → колода/теги/тип → превʼю → додавання
│   │   │   └── references/
│   │   │       ├── quality-rules.md  ← 13 правил якості + приклади добрих/поганих карток
│   │   │       ├── note-types.md     ← поля кожного типу, коли який обирати
│   │   │       ├── tags-decks.md     ← таксономія тегів і колод
│   │   │       └── vocab-guide.md    ← як писати приклади B1–B2, WhyThisWord, Active, Hint
│   │   ├── anki-add/  anki-file/  anki-vocab/  anki-distinct/
│   │   ├── anki-code/ anki-leeches/ anki-stats/ anki-fix/   ← slash-команди (тонкі, посилаються на anki-cards)
│   ├── hooks/hooks.json              ← Stop (звук/нагадування), SessionStart (прогрів uv)
│   └── server/                       ← Python 3.14 + uv + FastMCP
│       ├── pyproject.toml, uv.lock, .python-version
│       └── src/anki_claude/
│           ├── server.py             ← реєстрація MCP-інструментів
│           ├── ankiconnect.py        ← клієнт: таймаути, ретраї, зрозумілі помилки
│           ├── config.py             ← env (з userConfig) + опційний .env
│           ├── decks.py              ← структура колод, пресети, ліміти
│           ├── notetypes/            ← специфікації типів: fields, *.html шаблони, style.css, js/
│           ├── routing.py            ← картка → колода (замість Deck Override)
│           ├── validation.py         ← перевірка карток і тегів перед додаванням
│           └── hooks/                ← stop.py, session_start.py
├── tests/                            ← pytest + фейковий AnkiConnect (без реальної Anki)
├── tools/preview.py                  ← рендер шаблонів у HTML (десктоп/телефон, світла/темна тема)
├── docs/ (PLAN.md, screenshots/)
├── README.md (українською), LICENSE (MIT)
└── .github/workflows/ci.yml          ← тести на Windows / macOS / Linux
```

MCP запускається як
`uv run --frozen --project ${CLAUDE_PLUGIN_ROOT}/server anki-claude-mcp`
з `UV_PROJECT_ENVIRONMENT=${CLAUDE_PLUGIN_DATA}/.venv`. `.python-version` = 3.14; якщо в друга
її немає, uv завантажить сам. Єдина вимога до друга: встановлений `uv`.

## 2. Конфіг

`userConfig` (питається при встановленні, змінюється в `/config`) → env MCP-сервера:

| Ключ | За замовчуванням | Опис |
|---|---|---|
| `root_deck` | — (обов'язково) | коренева колода, у тебе `Den` |
| `anki_connect_url` | `http://127.0.0.1:8765` | адреса AnkiConnect |
| `anki_connect_key` | — (sensitive) | якщо в AnkiConnect ввімкнений apiKey |
| `explanation_language` | `uk` | мова пояснень у картках |
| `english_level` / `english_goal` | `B1` / `C1` | рівень і ціль |
| `example_level` | `B1-B2` | складність прикладів |
| `max_cards_per_batch` | `15` | максимум карток за раз |
| `promote_after_days` | `3` | поріг інтервалу для розморожування UA-EN і Forms |
| `auto_sync` | `true` | sync після додавання/редагування |
| `review_reminder` | `true` | нагадування про due-картки |
| `sound_on_stop` | `false` | звук після завершення задачі |

Той самий сервер читає ці значення з `.env` (для запуску поза плагіном / розробки).
Ліміти колод живуть у самій Anki (джерело правди), стартові значення — у `decks.py`;
міняються командою на кшталт «постав UA-EN 5 на день» → `set_deck_options`.
У коді — жодних особистих даних, `Den` лише в моєму локальному конфігу.

## 3. MCP-інструменти

| Інструмент | Що робить |
|---|---|
| `check_connection` | версія AnkiConnect, профіль, чи є колоди/типи; помилка «Anki не запущена — відкрий її» / «немає AnkiConnect — код 2055492159» |
| `get_config` | ефективний конфіг (щоб скіли знали корінь, рівень, ліміти) |
| `list_decks` | колоди + кількість карток/due |
| `create_deck` | створює колоду під коренем |
| `setup_decks` | створює стандартну структуру + окремі пресети з лімітами (ідемпотентно) |
| `set_deck_options` | ліміти нових/повторень, bury siblings; створює власний пресет, якщо колода на спільному |
| `list_note_types` | типи нотаток + чи наші типи актуальні |
| `ensure_note_types` | створює/оновлює наші 6 типів: поля, шаблони, CSS, медіа (JS); версія в CSS-маркері; поля ніколи не видаляє |
| `find_notes(query, limit)` | пошук, компактний вивід (id, тип, ключові поля, теги) |
| `check_duplicates(batch)` | точні дублікати + схожі (за Word/Front, леми, без регістру) — для показу тобі |
| `add_notes(batch)` | валідація → `canAddNotesWithErrorDetail` → `addNotes` → маршрутизація карток → звіт: додано / дублікати / помилки; сам додає `gen::claude`, `added::YYYY-MM` |
| `update_note_fields` | точкові правки (+ перемаршрутизація, якщо Active став yes) |
| `add_tags` / `remove_tags` | теги з валідацією формату |
| `get_leeches` | тег `leech` + `prop:lapses>=N`; лапси, інтервал, складність, поля |
| `get_stats` | картки по колодах і топ-тегах, due сьогодні, повторено сьогодні/за 7 днів, `status::to-check` |
| `sync` | синхронізація з AnkiWeb; чітка помилка, якщо немає логіну / інтернету / потрібна повна синхронізація |
| `promote_cards(dry_run)` | sync → перевірка інтервалів → розморожування UA-EN/Forms → sync → звіт (див. §5) |
| `review_status` | чи ти зараз повторюєш у desktop-Anki (`guiCurrentCard`, лише читання) |
| `delete_notes` | **лише з підтвердженням** (див. нижче) |

**Безпека**: видалення і масові зміни (> 20 нотаток) — двоетапні: перший виклик повертає
превʼю + одноразовий токен, другий виконує. Де клієнт підтримує MCP elicitation —
додатково діалог підтвердження в самому Claude Code. Ці інструменти не потрапляють в
`allowed-tools`, тож Claude Code теж спитає дозволу.

**Не заважати повторенню в desktop-Anki**: плагін не викликає жодних `gui*`-дій, що щось
перемикають (колода, браузер, вікна). Додавання і правки через AnkiConnect ідуть фоном. Якщо зараз
іде повторення, sync і promote відкладаються з повідомленням «ти повторюєш — синхронізую пізніше».
На етапі 2 окремо перевірю на твоїй Anki, чи sync під час повторення взагалі щось ламає; якщо ні —
обмеження послаблю.

**Валідація на сервері** (не лише в промпті): теги `^[a-z0-9]+(-[a-z0-9]+)*(::…)*$`;
Vocab — ≥2 непорожні приклади, у кожному виділене слово; Active лише yes/no;
WhyThisWord/Explanation ≤ ~200 символів; Distinction містить `___`; Cloze містить `{{c1::`.

## 4. Колоди і теги

```
Den                          стеля = сума підколод (26), порядок набору «Random notes»
├── Code                     2 на всю гілку (створюється з першою карткою)
│   ├── Python               2   ← ліниво, лише коли є картки
│   ├── Git                  2
│   └── Algorithms …         2
├── English
│   ├── EN-UA                10
│   ├── UA-EN                 7
│   └── Distinctions          3
├── ML                        2
└── Uni                       2 на всю гілку
    └── <предмет> …           ← ліниво, як у Code
```
- Створюються одразу: `Den`, `English` + 3 підколоди, `ML`, `Uni`. Усе інше (`Code`, `Code::Python`,
  `Uni::Calculus`…) — лише в момент додавання першої картки: `add_notes` сам створює колоду,
  призначає пресет її «сімʼї» і пише у звіті «створено нову колоду». У превʼю нова колода позначена.
- Куди йде код: картка про **предмет** (PyTorch, лінійна алгебра в numpy) → `ML`; картка про
  **мову/інструмент** (декоратори Python, git rebase, сортування) → `Code::<мова/тема>`.
  Мова завжди ще й у тезі `lang::python`, тож усі Python-картки знаходяться з будь-якої колоди.
- Пресети: `AC::Den`, `AC::EN-UA`, `AC::UA-EN`, `AC::Distinctions`, `AC::ML`, `AC::Uni`
  (спільний для гілки Uni), `AC::Code` (спільний для гілки Code). У всіх — «Bury new siblings».
- Стеля `Den` = сума лімітів підколод: так вона ніколи не відрізає ML/Uni (Anki набирає підколоди
  за алфавітом, і менша стеля віддавала б усе англійській). `set_deck_options` перераховує її сам.
- «Random notes» на `Den` — щоб нові картки з різних колод перемішувались (interleaving), а не
  йшли блоками «спершу весь код, потім уся англійська». Ставиться через API (`newGatherPriority`).
- Теги — як у ТЗ; `gen::claude` і `added::YYYY-MM` ставить сервер автоматично,
  `source::` — slug назви джерела.
- Порада в README: увімкнути FSRS (desired retention 0.9).

## 5. Типи нотаток

Назви з префіксом, щоб не конфліктувати з чужими: `AC Concept`, `AC Cloze`, `AC Formula`,
`AC Code`, `AC Vocab`, `AC Distinction`. Спільний CSS: великий шрифт для головного,
приглушений для другорядного, `.nightMode`/`.night_mode` для темної теми (desktop + AnkiDroid),
`max-width` + адаптивні відступи для телефона.

| Тип | Поля | Картки |
|---|---|---|
| AC Concept | Front, Back, Explanation, Example, Source | Front → Back + Explanation + Example |
| AC Cloze | Text, Extra, Source | стандартний cloze |
| AC Formula | Name, Formula, MeaningOfTerms, WhenToUse, Example | Name → Formula (MathJax `\( \)`), терміни, коли, приклад |
| AC Code | Prompt, Code, Answer, Explanation, Language | Prompt + Code → Answer + Explanation; підсвітка highlight.js (файл `_ac_highlight.js` у медіа, працює офлайн і на AnkiDroid) |
| AC Vocab | Word, IPA, PartOfSpeech, Forms, MeaningEN, TranslationUA, Example1–3, WhyThisWord, Collocations, Register, Hint, Active, DrillForms, Source | Recognition → EN-UA; Production (лише якщо Active) → UA-EN; Forms (лише якщо DrillForms і Forms непорожні) → UA-EN |
| AC Distinction | Sentence, Answer, Why, Pair, Source | Sentence → Answer + Why → Distinctions |

### Vocab — технічні рішення
- **Розмітка слова в прикладах — `<b>…</b>`** замість `**…**`: це рідний жирний Anki
  (у редакторі Ctrl+B), без JS приклад усе одно виглядає правильно, а шаблон знаходить `<b>`
  і або підсвічує його кольором (Recognition), або замінює на `_____` (Production). Підтримує
  форми (`<b>went</b>`) і розділені фразові дієслова (`<b>gave</b> it <b>up</b>`).
- **Випадковий приклад, той самий на звороті**: вибір серед непорожніх Example1–3, збереження
  вибору між сторонами через бібліотеку Anki-Persistence (MIT, вбудована в шаблон; desktop,
  AnkiDroid, AnkiMobile). Запасний варіант — детермінований вибір за хешем (слово + дата).
- **Умовна Production-картка**: Anki перевіряє лише «поле порожнє чи ні», тому `Active=no`
  все одно створив би картку. Сервер зберігає `yes` як `yes`, а `no` як порожнє поле;
  фронт шаблону обгорнутий у `{{#Active}}…{{/Active}}`. Якщо Active пізніше стане yes —
  Anki згенерує картку, сервер перенесе її в UA-EN.
- **`{{type:Word}}`** на обох сторонах Production: вводиш словникову форму, над полем —
  «введи словникову форму». Для Production шаблон **віддає перевагу прикладам, де виділене слово
  збігається з Word** (базова форма); якщо таких немає — бере будь-який.
- Зворот Production: результат порівняння, Word + IPA + 🔊, повне речення з **виділеною реальною
  формою** (`went`), `Forms` (якщо непорожнє), WhyThisWord, Collocations.
- **Озвучка**: `{{tts en_US:Word}}` на лицьовій стороні Recognition (слово там і так видно) і на
  звороті Production. Системні голоси: Windows SAPI / Android TTS / macOS — нічого не качаємо.
- **Картка форм** (неправильні дієслова, irregular plurals, good–better–best): третій шаблон того
  ж AC Vocab, генерується лише якщо `DrillForms = yes` і `Forms` непорожнє. Лицьова: «go → ? → ?»,
  зворот: `go – went – gone` + приклад. Дані живуть в одній нотатці зі словом — нічого не дублюється,
  основна картка не змішується з формами.
- WhyThisWord — лише в шаблонах звороту (перевіряється тестом).

### Відкладений Production (`/anki-promote`)
- Нові картки UA-EN і Forms додаються **призупиненими**; на нотатці теги
  `status::pending-production` і/або `status::pending-forms` — так promote чіпає лише свої картки,
  а не те, що ти або Anki (leech) призупинили з інших причин.
- Ланцюжок: EN-UA інтервал ≥ `promote_after_days` → розморожується UA-EN;
  UA-EN інтервал ≥ поріг → розморожується Forms. Якщо Active = no (UA-EN немає) — Forms чекає на EN-UA.
- `--known` при додаванні: UA-EN одразу активна; Forms усе одно чекає порогу UA-EN.
- Порядок дій: перевірити, що ти не повторюєш зараз → **sync** (щоб врахувати повторення з телефону)
  → перевірка інтервалів → розморожування → **sync**. Якщо перший sync не вдався (немає логіну, немає
  інтернету, потрібна повна синхронізація) — **нічого не розморожую** і пишу чому.
- Звіт: «розморожено 4: UA-EN — borrow, give up, reluctant; Forms — go».
- Запуск: `/anki-promote` вручну + хук на старті сесії Claude Code.
- Розморожена картка залишається **новою** (вона ще не мала повторень) і йде в денний ліміт нових
  своєї колоди. Перевірю на твоїй Anki: розморожу більше карток, ніж ліміт UA-EN, і подивлюсь, що
  `getDeckStats` показує не більше 7 нових.

## 6. Скіли й команди

- `anki-cards` (вантажиться автоматично): весь робочий процес з ТЗ —
  вхід → (якщо складно: коротке пояснення спершу) → колода/теги/тип → генерація за правилами
  → **превʼю-таблиця** `№ | тип | front | back | Active | теги` → «додати все / змінити № / видалити № /
  зробити активними №» → `check_duplicates` (схожі показую) → `add_notes` → звіт → `sync`
  (сам, якщо `auto_sync`; якщо ти зараз повторюєш — відкладаю і кажу).
  `--auto` у будь-якій команді — без підтвердження (але дублікати все одно не додаються);
  `--known` — UA-EN одразу активна.
- `/anki-add <текст|тема>`, `/anki-file <шлях>` (PDF через Read, MD, конспекти),
  `/anki-vocab <слова|текст>` (з тексту сам обирає слова твого рівня, пропонує кандидатів у Active),
  `/anki-distinct <пара>`, `/anki-code <файл|фрагмент>`,
  `/anki-leeches` (діагноз: неоднозначність / інтерференція / забагато інформації / брак контексту →
  переписати, розбити, додати Distinction; знімає тег leech після правки),
  `/anki-stats` (коротко + що підтягнути), `/anki-fix <запит>` (аудит за правилами → diff → підтвердження),
  `/anki-promote` (розморожування відкладених карток, §5).
- `allowed-tools` у скілах: читальні інструменти й `add_notes` (після твого «так» у превʼю не буде
  ще й системного запиту); видалення — ні.

## 7. Хуки
- `SessionStart`: `uv sync`, щоб перший виклик MCP не впирався в таймаут; потім promote
  (sync → розморожування → sync). Anki закрита — тихо пропускає; ти повторюєш — пропускає з
  повідомленням; звіт про розморожені картки показується тобі одним рядком.
- `Stop` (async, exec-форма Python): якщо `sound_on_stop` — короткий звук (winsound / afplay /
  paplay); якщо `review_reminder` і Anki відкрита та є due — повідомлення
  «📚 У Den чекає 23 картки», не частіше разу на 3 год (стан у `${CLAUDE_PLUGIN_DATA}`).

## 8. Тести
- Фейковий AnkiConnect (in-memory колекція: колоди, пресети, типи, нотатки, картки, теги) —
  емулює й генерацію карток Anki (порожній фронт ⇒ немає картки), щоб перевіряти Active.
- Тести: клієнт і помилки (Anki вимкнена, стара версія, apiKey), `ensure_note_types` (створення,
  оновлення застарілих, не чіпає чужі), `add_notes` (звіт, дублікати, валідація, маршрутизація),
  шаблони (усі `{{Поле}}` існують, WhyThisWord лише на звороті, `{{type:Word}}`, `{{#Active}}`),
  JS шаблону (вибір прикладу, виділення/пропуск для went/goes/going і фразових дієслів) у
  вбудованому JS-рушії без браузера.
- promote: ланцюжок EN-UA → UA-EN → Forms, поріг з конфігу, `--known`, чужі призупинені картки
  не чіпаються, sync не вдався ⇒ нічого не розморожено, ти повторюєш ⇒ пропуск.
- Перевірка шаблонів на пристроях: desktop — картки, які Anki сама відрендерила (`cardsInfo`),
  проганяю в браузері з її CSS і JS + ти дивишся в Anki; AnkiDroid — лише ти на телефоні, за моїм
  чеклистом (рандом, той самий приклад на звороті, введення, темна тема, озвучка).
- `tools/preview.py` рендерить картки в HTML — дизайн можна подивитись ще до встановлення Anki
  і зробити скріншоти для README.
- CI: GitHub Actions на Windows/macOS/Linux + `claude plugin validate`.

## 9. Етапи (після кожного — звіт і що перевірити тобі)
1. ✅ План (цей файл) → твоє підтвердження.
2. Репо на GitHub (`denysfreiuk/anki-claude`) + скелет плагіна + маркетплейс + MCP +
   `check_connection`/`get_config`/`sync`/`review_status` → підключаєш плагін, перевіряємо на твоїй
   Anki; перша синхронізація desktop ↔ AnkiWeb ↔ AnkiDroid; тест «sync під час повторення».
3. Колоди, пресети, 6 типів нотаток, шаблони + превʼю + тестові картки (`status::sample`, легко
   видалити) → дивишся на компʼютері й AnkiDroid (через sync).
4. Скіли й slash-команди + хук.
5. Тести, README зі скріншотами, CI, готовність до GitHub.

## 10. Відомі ризики
- macOS (у дівчини): App Nap присипляє Anki у фоні → AnkiConnect не відповідає. У README —
  команда `defaults write net.ankiweb.dtop NSAppSleepDisabled -bool true`.
- AnkiDroid: JS і `{{type:}}` підтримуються; Anki-Persistence там перевірю на реальному телефоні на етапі 3.
- `sync` через AnkiConnect працює лише якщо в Anki desktop виконано вхід в AnkiWeb.
- **Перша синхронізація** (робиш ти вручну, плагін її не запускає): на телефоні 6–7 слів, на
  desktop порожньо. Порядок: AnkiDroid → Sync (якщо спитає — «Upload»), потім desktop → вхід в AnkiWeb
  → Sync → «Download». Так нічого не губиться, а старі слова за бажанням переробимо в новий формат.
- README: увімкнути автосинхронізацію на обох пристроях (desktop: Preferences → Syncing →
  «Automatically sync on profile open/close»; AnkiDroid: Settings → Sync → Automatic synchronization)
  і синхронізувати при переході між пристроями.
- Windows-консоль у cp1251: хуки й сервер явно пишуть UTF-8 (інакше кирилиця ламається — уже
  бачив це, поки перевіряв твою Anki).
