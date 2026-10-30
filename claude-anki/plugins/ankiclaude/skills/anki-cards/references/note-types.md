# Типи нотаток AC і як їх заповнювати

Поля приймають простий HTML: `<b>`, `<i>`, `<br>`, `<code>`, `<sub>`, `<sup>`. Новий рядок можна писати як `\n`.
Формули — MathJax: `\( … \)` у рядку, `\[ … \]` окремо; знаки `<`/`>` у формулах пиши як `\lt`/`\gt`.

| type | Коли | Обов'язкові поля | Колода |
|---|---|---|---|
| `concept` | питання → коротка відповідь; «чому?», «коли?», «чим відрізняється?» | Front, Back | вказати (`deck`) |
| `cloze` | означення, факт у реченні, термін у контексті | Text з `{{c1::…}}` | вказати |
| `formula` | формула + що означають члени + коли застосовувати | Name, Formula | вказати |
| `code` | що робить код / який вивід / що вставити в пропуск | Prompt, Code, Answer | вказати |
| `vocab` | англійське слово чи вираз | Word, MeaningEN, TranslationUA, ≥2 Example | English::EN-UA (автоматично) |
| `distinction` | розрізнення схожих слів (make/do) | Sentence з `___` і варіантами, Answer, Pair | English::Distinctions (автоматично) |

Усі мають поле `Source` — назва курсу, лекції, книги, серіалу, файлу (коротко).

## concept
- `Front` — питання, однозначне. `Back` — коротка відповідь (одне речення).
- `Explanation` — чому так, 1–2 рядки. `Example` — короткий приклад.

## cloze
- `Text` — речення з 1–2 пропусками: `{{c1::softmax}}`, можна підказку `{{c1::softmax::функція}}`.
- Різні `c1`, `c2` = різні картки. Однаковий номер = приховуються разом.
- `Extra` — пояснення або приклад на звороті.

## formula
- `Name` — як називається (лицьова сторона: «Запиши формулу»).
- `Formula` — `\[ … \]`. `MeaningOfTerms` — що означає кожен символ. `WhenToUse` — коли застосовувати. `Example` — числовий приклад.

## code
- `Prompt` — конкретне завдання: «Що виведе код?», «Яку форму матиме тензор?», «Що вставити замість ___?».
- `Code` — ≤ 12 рядків, лише суть; звичайний текст з `\n` (сервер сам екранує і зберігає відступи).
- `Answer` — коротко. `Explanation` — 1–2 рядки чому. `Language` — `python`, `bash`, `sql`, `javascript`…
- Ніколи не переносити в картки секрети з коду (ключі, токени, паролі, особисті дані).

## vocab
Див. `vocab-guide.md`. Мінімальний приклад для `add_notes`:

```json
{"type": "vocab", "fields": {
  "Word": "give up", "IPA": "/ɡɪv ˈʌp/", "PartOfSpeech": "phrasal verb",
  "Forms": "give up – gave up – given up",
  "MeaningEN": "to stop trying, or to stop doing a habit",
  "TranslationUA": "кинути (звичку); перестати пробувати",
  "Example1": "Don't <b>give up</b> now — you're almost there.",
  "Example2": "She <b>gave</b> it <b>up</b> after two weeks.",
  "Example3": "He has <b>given up</b> sugar completely.",
  "WhyThisWord": "Про припинення спроб або звички. Не плутай з give in — «поступитися».",
  "Collocations": "give up smoking · give up on sb · never give up",
  "Register": "neutral", "Hint": "g… u…", "Active": "yes", "DrillForms": "no",
  "Source": "Friends S02E05"},
 "tags": ["topic::english::phrasal-verbs", "level::b1", "type::vocab", "source::friends"]}
```

## distinction
- `Sentence` — речення з пропуском і варіантами: `Don't worry — everyone ___ mistakes. (make / do)`.
- `Answer` — точна форма, що підходить (`makes`). `Why` — 1–2 рядки правила. `Pair` — `make / do`.
- На одну пару — 2–4 нотатки, де правильні **різні** варіанти (і make, і do), інакше вчиш «завжди make».
