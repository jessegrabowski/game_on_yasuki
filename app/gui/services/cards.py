"""Database-backed card and set fetchers for the deck builder."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import psycopg2
import psycopg2.extras

from app.gui.config import load_database_dsn


@dataclass(frozen=True)
class CardRecord:
    card_id: str
    name: str
    deck: str
    type: str
    text: str
    image_path: Path | None

    @property
    def side(self) -> str:
        return "FATE" if self.deck.upper() == "FATE" else "DYNASTY"


@dataclass(frozen=True)
class SetRecord:
    name: str
    code: str | None


class CardRepository:
    def __init__(self, dsn: str | None = None):
        self.dsn = dsn or load_database_dsn()

    def _connect(self):
        return psycopg2.connect(self.dsn)

    def fetch_cards(self) -> list[CardRecord]:
        with self._connect() as conn:
            with conn.cursor(cursor_factory=psycopg2.extras.DictCursor) as cur:
                cur.execute(
                    """
                    SELECT id, name, deck, type, rules_text, extra ->> 'image_path' AS image_path
                    FROM cards
                    ORDER BY name
                    """
                )
                rows = cur.fetchall()
        cards: list[CardRecord] = []
        for row in rows:
            img_raw = row["image_path"] if row["image_path"] else None
            img_path: Path | None = Path(img_raw) if img_raw else None
            cards.append(
                CardRecord(
                    card_id=row["id"],
                    name=row["name"],
                    deck=row["deck"],
                    type=row["type"],
                    text=row["rules_text"] or "",
                    image_path=img_path,
                )
            )
        return cards


class SetRepository:
    def __init__(self, dsn: str | None = None):
        self.dsn = dsn or load_database_dsn()

    def fetch_sets(self) -> list[SetRecord]:
        with psycopg2.connect(self.dsn) as conn:
            with conn.cursor(cursor_factory=psycopg2.extras.DictCursor) as cur:
                cur.execute("SELECT set_name, code FROM l5r_sets ORDER BY set_name")
                rows = cur.fetchall()
        return [SetRecord(name=row["set_name"], code=row["code"]) for row in rows]
