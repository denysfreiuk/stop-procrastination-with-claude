"""MCP tools of the Anki&Claude plugin."""

from __future__ import annotations

import logging
import sys
from collections.abc import Awaitable, Callable
from typing import Annotated, Any, TypeVar

from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp_types import ToolAnnotations
from pydantic import Field

from . import __version__
from .anki import Anki
from .ankiconnect import AnkiConnect
from .config import load_config
from .errors import AnkiError
from .notes import DuplicateCandidate, NoteIn

T = TypeVar("T")

INSTRUCTIONS = """\
Інструменти для карток Anki через AnkiConnect (add-on у desktop-Anki).
- Якщо інструмент повертає помилку про недоступну Anki — передай користувачу підказку з помилки дослівно.
- sync сам відкладається, коли користувач повторює картки в desktop-Anki; не обходь це через force=true без його згоди.
"""

READ_ONLY = ToolAnnotations(read_only_hint=True, open_world_hint=False)
WRITES = ToolAnnotations(read_only_hint=False, destructive_hint=False, idempotent_hint=False, open_world_hint=False)


def build_server(get_anki: Callable[[], Anki]) -> MCPServer:
    server = MCPServer(
        name="anki", title="Anki&Claude", version=__version__, instructions=INSTRUCTIONS, log_level="WARNING"
    )

    async def run(call: Callable[[Anki], Awaitable[T]]) -> T:
        try:
            return await call(get_anki())
        except AnkiError as error:
            raise ToolError(str(error)) from error

    @server.tool(annotations=READ_ONLY)
    async def check_connection() -> dict[str, Any]:
        """Перевіряє, чи запущена Anki з AnkiConnect.

        Повертає версії AnkiConnect і Anki, активний профіль, стан кореневої колоди,
        які типи нотаток AC уже є і чи вони від цієї версії плагіна, чи користувач зараз
        повторює картки, попередження конфігу і наступні кроки. Викликай першим, якщо щось не працює.
        """
        return await run(lambda anki: anki.connection_report())

    @server.tool(annotations=READ_ONLY)
    async def get_config() -> dict[str, Any]:
        """Повертає налаштування плагіна: коренева колода, мова пояснень, рівень англійської,
        складність прикладів, максимум карток за раз, поріг розморожування, автосинхронізація.
        API-ключ не показується. Використовуй ці значення під час генерації карток."""
        return await run(lambda anki: _config(anki))

    @server.tool(annotations=READ_ONLY)
    async def review_status() -> dict[str, Any]:
        """Чи повторює користувач зараз картки в desktop-Anki (лише читання, нічого не перемикає)."""
        return await run(lambda anki: anki.review_status())

    @server.tool(annotations=ToolAnnotations(read_only_hint=False, destructive_hint=False, open_world_hint=True))
    async def sync(force: bool = False) -> dict[str, Any]:
        """Синхронізує desktop-Anki з AnkiWeb і чекає результату.

        Якщо користувач саме повторює картки в desktop-Anki, синхронізація відкладається
        (status=deferred). force=true — синхронізувати попри це, лише з явної згоди користувача.
        Помилка означає, що синхронізація НЕ відбулася: передай користувачу її текст і підказку.
        """
        return await run(lambda anki: anki.sync(force=force))

    @server.tool(annotations=READ_ONLY)
    async def list_decks() -> dict[str, Any]:
        """Колоди під кореневою: пресет, ліміти нових/повторень на день, скільки карток
        нових / у навчанні / на повторення сьогодні, усього карток."""
        return await run(lambda anki: anki.decks.overview())

    @server.tool(annotations=WRITES)
    async def setup_decks() -> dict[str, Any]:
        """Створює стандартну структуру колод (корінь, English::EN-UA/UA-EN/Distinctions, ML, Uni)
        і окремий пресет для кожної гілки з лімітами нових карток. Ідемпотентно: наявне не ламає,
        змінені користувачем ліміти не скидає. Ліміт кореня й English = сума підколод."""
        return await run(lambda anki: anki.decks.setup())

    @server.tool(annotations=WRITES)
    async def create_deck(deck: str) -> dict[str, Any]:
        """Створює колоду під кореневою (напр. Code::Python, Uni::Calculus) з пресетом її гілки.
        Створюй лише тоді, коли в неї вже йдуть картки — порожніх колод не треба."""

        async def call(anki: Anki) -> dict[str, Any]:
            name, created = await anki.decks.ensure(deck)
            return {"deck": name, "created": created}

        return await run(call)

    @server.tool(annotations=WRITES)
    async def set_deck_options(
        deck: str,
        new_per_day: Annotated[int | None, Field(ge=0, le=9999)] = None,
        reviews_per_day: Annotated[int | None, Field(ge=0, le=9999)] = None,
    ) -> dict[str, Any]:
        """Змінює денні ліміти колоди (нових і повторень). Зміна йде в пресет колоди: якщо його
        поділяють інші колоди гілки (also_affects), ліміт зміниться і в них. Ліміт кореня
        й English перераховується автоматично."""
        return await run(lambda anki: anki.decks.set_options(deck, new_per_day, reviews_per_day))

    @server.tool(annotations=READ_ONLY)
    async def list_note_types() -> dict[str, Any]:
        """Типи нотаток AC: чи є в колекції і чи актуальні, їхні поля; інші типи нотаток колекції."""
        return await run(lambda anki: anki.note_types.overview())

    @server.tool(annotations=WRITES)
    async def ensure_note_types(dry_run: bool = False) -> dict[str, Any]:
        """Створює відсутні типи нотаток AC (Concept, Cloze, Formula, Code, Vocab, Distinction) і оновлює
        застарілі: шаблони, CSS, колоду шаблону, медіафайли. Поля не видаляє. dry_run=true — лише показати,
        що зміниться. Якщо full_sync_required=true — попередь користувача: наступна синхронізація буде повною.
        Потрібен після зміни tts, tts_lang чи explanation_language; оновлення плагіна add_notes підхоплює сам.
        Відмовляє, якщо типи зробила новіша версія плагіна: тоді треба оновити плагін."""
        return await run(lambda anki: anki.note_types.ensure(dry_run=dry_run))

    @server.tool(annotations=WRITES)
    async def add_notes(notes: list[NoteIn], known: bool = False) -> dict[str, Any]:
        """Додає нотатки пакетом і повертає звіт: added / duplicates / errors / decks_created.

        Сервер перевіряє правила (≥2 приклади з <b>слово</b> у vocab, пропуск ___ у distinction,
        {{c1::…}} у cloze, короткі пояснення, теги kebab-case), додає теги gen::claude і added::YYYY-MM,
        кладе картки у свої колоди. У vocab картка UA→EN створюється призупиненою, доки EN→UA не
        закріпиться (known=true — одразу активна); картка форм завжди чекає UA→EN.
        Дублікати не додаються — покажи їх користувачу. Після додавання сам синхронізує, якщо ввімкнено auto_sync.
        Перший виклик після оновлення плагіна сам оновлює типи нотаток AC (note_types_update): updated — скажи
        користувачу одним рядком; needs_confirmation — спитай його (потрібна повна синхронізація).
        """
        return await run(lambda anki: anki.add_notes(notes, known=known))

    @server.tool(annotations=READ_ONLY)
    async def find_notes(
        query: str,
        limit: Annotated[int, Field(ge=1, le=200)] = 30,
        with_fields: bool = True,
    ) -> dict[str, Any]:
        """Шукає нотатки синтаксисом пошуку Anki (напр. deck:"Den::ML" tag:topic::ml::metrics,
        note:"AC Vocab" "Word:give up", added:7, prop:lapses>=3). Повертає поля, теги і картки
        (шаблон, колода, інтервал, кількість забувань, чи призупинена)."""
        return await run(lambda anki: anki.notes.find(query, limit, with_fields))

    @server.tool(annotations=READ_ONLY)
    async def check_duplicates(candidates: list[DuplicateCandidate]) -> dict[str, Any]:
        """Перевіряє кандидатів у нові картки на дублікати перед превʼю: exact — така сама нотатка вже є,
        similar — схожа (інша форма слова, близьке питання). Схожі покажи користувачу, а не дублюй."""
        return await run(lambda anki: anki.notes.check_duplicates(candidates))

    @server.tool(annotations=WRITES)
    async def update_note_fields(note_id: int, fields: dict[str, str], known: bool = False) -> dict[str, Any]:
        """Змінює поля однієї нотатки з тими самими перевірками, що й add_notes. У vocab: якщо Active стає yes —
        створена картка UA→EN чекає закріплення EN→UA (known=true — одразу активна); якщо DrillForms стає yes —
        картка форм чекає. Для правок багатьох нотаток спершу покажи план і отримай згоду користувача."""
        return await run(lambda anki: anki.notes.update_fields(note_id, fields, known))

    @server.tool(annotations=WRITES)
    async def add_tags(note_ids: list[int], tags: list[str], confirm_token: str | None = None) -> dict[str, Any]:
        """Додає теги нотаткам. Понад 20 нотаток — масова зміна: перший виклик повертає превʼю і confirm_token,
        повторний виклик з токеном виконує, лише після явного «так» користувача."""
        return await run(lambda anki: anki.notes.change_tags("add", note_ids, tags, anki.confirmations, confirm_token))

    @server.tool(annotations=WRITES)
    async def remove_tags(note_ids: list[int], tags: list[str], confirm_token: str | None = None) -> dict[str, Any]:
        """Прибирає теги з нотаток (напр. leech після виправлення картки). Понад 20 нотаток — лише з confirm_token
        після явного «так» користувача."""
        return await run(lambda anki: anki.notes.change_tags("remove", note_ids, tags, anki.confirmations, confirm_token))

    @server.tool(annotations=ToolAnnotations(read_only_hint=False, destructive_hint=True, open_world_hint=False))
    async def delete_notes(note_ids: list[int], confirm_token: str | None = None) -> dict[str, Any]:
        """Видаляє нотатки з усіма картками й історією — незворотно. Перший виклик лише показує, що буде видалено,
        і дає confirm_token. Видалення відбудеться тільки при повторному виклику з токеном — роби його лише
        після того, як користувач побачив список і явно погодився."""
        return await run(lambda anki: anki.notes.delete(note_ids, anki.confirmations, confirm_token))

    @server.tool(annotations=READ_ONLY)
    async def get_leeches(
        min_lapses: Annotated[int, Field(ge=1, le=50)] = 4,
        limit: Annotated[int, Field(ge=1, le=100)] = 30,
    ) -> dict[str, Any]:
        """Проблемні картки під кореневою колодою: з тегом leech або забуті щонайменше min_lapses разів.
        Повертає нотатки з полями, тегами і проблемними картками, найгірші першими."""
        return await run(lambda anki: anki.insights.leeches(min_lapses, limit))

    @server.tool(annotations=READ_ONLY)
    async def get_stats() -> dict[str, Any]:
        """Статистика: картки до повторення сьогодні, повторено сьогодні і за 7 днів, кількість нотаток і карток,
        призупинені, leech, відкладені UA→EN і форми, status::to-check, топ тем за тегами, ліміти колод."""
        return await run(lambda anki: anki.insights.stats())

    @server.tool(annotations=WRITES)
    async def promote_cards(dry_run: bool = False, force: bool = False) -> dict[str, Any]:
        """Розморожує відкладені картки слів: UA→EN, коли EN→UA закріпилась (інтервал ≥ promote_after_days),
        і картку форм, коли закріпилась UA→EN. Спершу синхронізує (щоб врахувати повторення з телефону), потім
        синхронізує ще раз. Якщо синхронізація не вдалась — нічого не розморожує. Якщо користувач зараз
        повторює в desktop-Anki — відкладає (force=true лише з його згоди). dry_run — лише показати."""
        return await run(lambda anki: anki.promote(dry_run=dry_run, force=force))

    return server


async def _config(anki: Anki) -> dict[str, Any]:
    return anki.config.public_dict()


_anki: Anki | None = None


def _default_anki() -> Anki:
    global _anki
    if _anki is None:
        config = load_config()
        _anki = Anki(config, AnkiConnect(config.anki_connect_url, config.anki_connect_key))
    return _anki


def main() -> None:
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    # httpx logs every request at INFO; the server's stderr ends up in Claude Code's MCP logs.
    logging.getLogger("httpx").setLevel(logging.WARNING)
    build_server(_default_anki).run("stdio")


if __name__ == "__main__":
    main()
