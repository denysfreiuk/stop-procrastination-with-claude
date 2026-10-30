"""Unsuspend delayed vocab cards once the card before them in the chain is learned.

Chain: Recognition (EN→UA) → Production (UA→EN) → Forms. A waiting card is released
when the previous card's interval reaches `promote_after_days`. Words without a
Production card (Active = no) release Forms after Recognition. Only cards that the
plugin itself suspended (tagged status::pending-*) are touched.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from .errors import SyncError
from .notes import FORMS_ORD, PENDING_FORMS, PENDING_PRODUCTION, PRODUCTION_ORD, plain_text

if TYPE_CHECKING:
    from .anki import Anki

RECOGNITION_ORD = 0
SUSPENDED = -1


async def promote(anki: Anki, dry_run: bool = False, force: bool = False) -> dict[str, Any]:
    threshold = anki.config.promote_after_days
    report: dict[str, Any] = {"threshold_days": threshold, "dry_run": dry_run, "promoted": [], "sync": []}
    if anki.config.auto_sync:
        review = await anki.review_status()
        if review["reviewing"] and not force:
            return {**report, "status": "deferred",
                    "message": "Ти зараз повторюєш картки в Anki — перевірку відкладено. Запусти /anki-promote після повторення."}
        try:
            report["sync"].append(await anki.sync(force=True))
        except SyncError as error:
            return {**report, "status": "sync_failed", "reason": error.reason,
                    "message": f"Нічого не розморожено: спершу треба синхронізуватись, щоб врахувати повторення з телефону. {error}"}

    client = anki.client
    root = anki.decks.root
    card_ids = await client.invoke(
        "findCards", query=f'deck:"{root}" note:"AC Vocab" (tag:{PENDING_PRODUCTION} OR tag:{PENDING_FORMS})'
    )
    cards = await client.invoke("cardsInfo", cards=card_ids) if card_ids else []
    by_note: dict[int, dict[int, dict]] = {}
    for card in cards:
        by_note.setdefault(card["note"], {})[card["ord"]] = card
    infos = await client.invoke("notesInfo", notes=list(by_note)) if by_note else []

    release: list[int] = []
    untag: dict[str, list[int]] = {PENDING_PRODUCTION: [], PENDING_FORMS: []}
    waiting: list[dict[str, Any]] = []
    for info in infos:
        note_id = info["noteId"]
        word = plain_text(info["fields"]["Word"]["value"])
        notes_cards = by_note[note_id]
        recognition = notes_cards.get(RECOGNITION_ORD)
        production = notes_cards.get(PRODUCTION_ORD)
        forms = notes_cards.get(FORMS_ORD)

        if PENDING_PRODUCTION in info["tags"]:
            if production is None or production["queue"] != SUSPENDED:
                untag[PENDING_PRODUCTION].append(note_id)  # Active cleared, or the user unsuspended it already
            elif recognition and recognition["interval"] >= threshold:
                release.append(production["cardId"])
                untag[PENDING_PRODUCTION].append(note_id)
                report["promoted"].append({"word": word, "card": "UA→EN", "after": f"EN→UA {recognition['interval']} дн."})
                production = {**production, "queue": 0}
            else:
                waiting.append({"word": word, "card": "UA→EN", "needs": "EN→UA",
                                "interval": recognition["interval"] if recognition else 0})

        if PENDING_FORMS in info["tags"]:
            base, base_name = (production, "UA→EN") if production else (recognition, "EN→UA")
            base_waiting = production is not None and production["queue"] == SUSPENDED
            if forms is None or forms["queue"] != SUSPENDED:
                untag[PENDING_FORMS].append(note_id)
            elif base and not base_waiting and base["interval"] >= threshold:
                release.append(forms["cardId"])
                untag[PENDING_FORMS].append(note_id)
                report["promoted"].append({"word": word, "card": "Форми", "after": f"{base_name} {base['interval']} дн."})
            else:
                waiting.append({"word": word, "card": "Форми", "needs": base_name,
                                "interval": 0 if base_waiting or not base else base["interval"]})

    if not dry_run:
        if release:
            await client.invoke("unsuspend", cards=release)
        for tag, note_ids in untag.items():
            if note_ids:
                await client.invoke("removeTags", notes=note_ids, tags=tag)
        if release and anki.config.auto_sync:
            try:
                report["sync"].append(await anki.sync(force=True))
            except SyncError as error:
                report["sync"].append({"status": "failed", "reason": error.reason, "message": str(error)})

    waiting.sort(key=lambda item: -item["interval"])
    count = len(report["promoted"])
    words = ", ".join(f"{p['word']} ({p['card']})" for p in report["promoted"])
    report.update(
        status="ok",
        waiting_total=len(waiting),
        waiting_next=waiting[:10],
        message=(f"Розморожено {count}: {words}." if count else "Нічого розморожувати: ще не закріпилось.")
        + (" (пробний запуск, нічого не змінено)" if dry_run and count else ""),
    )
    return report
