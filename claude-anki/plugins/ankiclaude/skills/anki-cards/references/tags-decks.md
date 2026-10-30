# Колоди й теги

Колод мало, тегів багато. У `deck` пиши шлях **відносно кореневої колоди** (`ML`, `Code::Python`), корінь додасться сам.

## Колоди

| Що | Колода |
|---|---|
| англійські слова (`vocab`) | `English::EN-UA` + `English::UA-EN` — автоматично |
| розрізнення (`distinction`) | `English::Distinctions` — автоматично |
| ML: лінійна алгебра, ймовірності, PyTorch, метрики, моделі | `ML` |
| університетський предмет | `Uni::<Предмет>`, напр. `Uni::Calculus`, `Uni::Databases` |
| мова програмування / інструмент / алгоритми не про ML | `Code::<Мова>`, напр. `Code::Python`, `Code::Git`, `Code::Algorithms` |

- Код **про предмет** (PyTorch-модель, numpy для лінійної алгебри) → `ML`; код **про мову чи інструмент** (декоратори, `git rebase`, сортування) → `Code::…`. Мову завжди дублюй тегом `lang::<мова>`.
- Колода створюється сама з першою карткою (`add_notes`). Порожніх колод не створюй. Нову колоду познач у превʼю: «нова колода: Code::Rust».
- Підколоди однієї гілки (`Code::*`, `Uni::*`) ділять пресет і денний ліміт гілки — це нормально.

## Теги

Латиницею, kebab-case, ієрархія через `::`, без пробілів (сервер нормалізує регістр і пробіли, але кирилицю відхилить).

| Префікс | Приклади |
|---|---|
| `topic::` | `topic::ml::linear-algebra`, `topic::ml::pytorch`, `topic::english::phrasal-verbs`, `topic::uni::calculus::limits` |
| `source::` | `source::cs231n-lecture-3`, `source::deep-learning-book-ch6`, `source::friends-s02e05` |
| `type::` | `definition`, `concept`, `formula`, `code`, `vocab`, `distinction`, `why` |
| `level::` | `a2`, `b1`, `b2`, `c1` — для англійської |
| `lang::` | `python`, `sql`, `bash`… — для коду |
| `status::to-check` | якщо є сумнів у точності |

`gen::claude` і `added::YYYY-MM` сервер додає сам. `status::pending-*` ставить і знімає лише сервер — не чіпай.
