"""Read-only views over the collection: problem cards and statistics."""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any

from .ankiconnect import AnkiConnect
from .decks import Decks
from .notes import PENDING_FORMS, PENDING_PRODUCTION, Notes

TOP_TOPICS = 15


def last_days(by_day: list[list], days: int, today: date | None = None) -> list[dict[str, Any]]:
    """Reviews per calendar day for the last `days` days; Anki lists only days that had reviews."""
    counts = {str(day): count for day, count in by_day}
    today = today or date.today()
    out = []
    for offset in range(days - 1, -1, -1):
        day = (today - timedelta(days=offset)).isoformat()
        out.append({"date": day, "cards": counts.get(day, 0)})
    return out


class Insights:
    def __init__(self, client: AnkiConnect, decks: Decks, notes: Notes) -> None:
        self.client = client
        self.decks = decks
        self.notes = notes

    def _in_root(self, query: str) -> str:
        return f'deck:"{self.decks.root}" ({query})'

    async def leeches(self, min_lapses: int = 4, limit: int = 30) -> dict[str, Any]:
        """Cards Anki tagged as leeches or that were forgotten at least `min_lapses` times."""
        card_ids = await self.client.invoke("findCards", query=self._in_root(f"tag:leech OR prop:lapses>={min_lapses}"))
        cards = await self.client.invoke("cardsInfo", cards=card_ids) if card_ids else []
        worst: dict[int, int] = {}
        for card in cards:
            worst[card["note"]] = max(worst.get(card["note"], 0), card["lapses"])
        ranked = sorted(worst, key=lambda note_id: -worst[note_id])[:limit]
        described = await self.notes.describe(ranked)
        problems = []
        for note in described:
            bad = [c for c in note["cards"] if c["lapses"] >= min_lapses or "leech" in note["tags"]]
            problems.append({**note, "problem_cards": bad or note["cards"]})
        return {"min_lapses": min_lapses, "total_notes": len(worst), "shown": len(problems), "notes": problems}

    async def stats(self) -> dict[str, Any]:
        root = self.decks.root
        overview = await self.decks.overview()
        counts_queries = {
            "notes": "",
            "cards": "",
            "suspended": "is:suspended",
            "leeches": "tag:leech",
            "waiting_production": f"tag:{PENDING_PRODUCTION}",
            "waiting_forms": f"tag:{PENDING_FORMS}",
            "to_check": "tag:status::to-check",
            "generated_by_claude": "tag:gen::claude",
            "added_today": "added:1",
        }
        actions = []
        for name, query in counts_queries.items():
            action = "findNotes" if name not in ("cards", "suspended") else "findCards"
            actions.append((action, {"query": f'deck:"{root}"' + (f" {query}" if query else "")}))
        actions += [("getNumCardsReviewedToday", {}), ("getNumCardsReviewedByDay", {}), ("getTags", {})]
        results = await self.client.multi(actions)
        for value in results:
            if isinstance(value, Exception):
                raise value
        counts = {name: len(value) for name, value in zip(counts_queries, results, strict=False)}
        reviewed_today, by_day, all_tags = results[len(counts_queries):]

        topics = sorted({"::".join(t.split("::")[:3]) for t in all_tags if t.startswith("topic::")})
        topic_counts = []
        if topics:
            found = await self.client.multi(
                # tag:a::b also matches its children a::b::c.
                [("findNotes", {"query": f'deck:"{root}" "tag:{topic}"'}) for topic in topics]
            )
            topic_counts = sorted(
                ({"topic": t, "notes": len(f)} for t, f in zip(topics, found, strict=True) if not isinstance(f, Exception)),
                key=lambda item: -item["notes"],
            )[:TOP_TOPICS]

        root_row = next((d for d in overview["decks"] if d["deck"] == root), {})
        return {
            "root": root,
            "due_today": {
                "new": root_row.get("due_new"),
                "learning": root_row.get("due_learning"),
                "review": root_row.get("due_review"),
            },
            "reviewed_today": reviewed_today,
            "reviews_last_7_days": last_days(by_day, 7),
            "counts": counts,
            "top_topics": topic_counts,
            "decks": overview["decks"],
        }
