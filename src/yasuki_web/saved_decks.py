import asyncio
import logging
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi import Path as PathParam
from pydantic import BaseModel, Field

from yasuki_web.auth import current_user, current_user_optional
from yasuki_web.rate_limit import limiter

from yasuki_core.accounts import deck_repo, decks
from yasuki_core.accounts.db import get_accounts_connection
from yasuki_core.accounts.decks import DeckCard, DeckSummary, UnknownCardError
from yasuki_core.database import card_display_names, get_cards_by_names
from yasuki_core.decklist import parse_deck_yaml

logger = logging.getLogger(__name__)
router = APIRouter()

MAX_DECKS_PER_USER = 200
# Distinct (card, side, printing, art) entries; a legal deck is far smaller, but alt-art variants and
# casual formats leave generous headroom below anything abusive.
MAX_DECK_ENTRIES = 250
MAX_COPIES_PER_ENTRY = 100
MAX_NAME_LEN = 80
MAX_DESCRIPTION_LEN = 2000
MAX_YAML_LEN = 16384

_Slug = Annotated[str, PathParam(max_length=32, pattern=r"^[A-Za-z0-9_-]+$")]


class SaveDeckRequest(BaseModel):
    name: str = Field(min_length=1, max_length=MAX_NAME_LEN)
    yaml: str = Field(min_length=1, max_length=MAX_YAML_LEN)
    description: str | None = Field(None, max_length=MAX_DESCRIPTION_LEN)
    visibility: Literal["private", "unlisted", "public"] = "private"
    format: str | None = Field(None, max_length=60)


class DeckLimitError(ValueError):
    """A deck or a user is over a storage cap — distinct from an unknown-card rejection."""


def _deck_names(parsed: dict) -> set[str]:
    """Every card and art-swap-donor name a parsed decklist references, for one card-DB lookup."""
    names: set[str] = set()
    for side in decks.SIDES:
        for entry in parsed.get(side, []):
            names.add(entry["name"])
            if entry.get("art"):
                names.add(entry["art"]["name"])
    return names


def _resolve_deck(yaml_text: str) -> tuple[list[DeckCard], DeckSummary]:
    """Parse, resolve, validate, and summarize a decklist — the save path's card-DB work.

    Raises ``UnknownCardError`` for any unresolved card and ``DeckLimitError`` for an empty or
    oversized deck.
    """
    parsed = parse_deck_yaml(yaml_text)
    records = get_cards_by_names(list(_deck_names(parsed)))
    cards = decks.resolve_deck_cards(parsed, decks.build_name_index(records))
    if not cards:
        raise DeckLimitError("Deck has no recognizable cards")
    if len(cards) > MAX_DECK_ENTRIES:
        raise DeckLimitError(f"Deck exceeds {MAX_DECK_ENTRIES} entries")
    if any(card.quantity > MAX_COPIES_PER_ENTRY for card in cards):
        raise DeckLimitError(f"An entry exceeds {MAX_COPIES_PER_ENTRY} copies")
    summary = decks.summarize(cards, {record["card_id"]: record for record in records})
    return cards, summary


def _persist_deck(owner_id: int, body: SaveDeckRequest, cards, summary) -> dict:
    with get_accounts_connection() as conn:
        if deck_repo.count_active_decks(conn, owner_id) >= MAX_DECKS_PER_USER:
            raise DeckLimitError(f"At the {MAX_DECKS_PER_USER}-deck limit")
        return deck_repo.save_deck(
            conn,
            owner_id,
            name=body.name,
            cards=cards,
            summary=summary,
            format=body.format,
            description=body.description,
            visibility=body.visibility,
        )


def _public_deck(deck: dict) -> dict:
    """The deck fields safe to return — owner id and surrogate key stay internal."""
    return {
        "slug": deck["slug"],
        "name": deck["name"],
        "format": deck["format"],
        "description": deck["description"],
        "visibility": deck["visibility"],
        "stronghold_card_id": deck["stronghold_card_id"],
        "clan": deck["clan"],
        "dynasty_count": deck["dynasty_count"],
        "fate_count": deck["fate_count"],
        "created_at": deck["created_at"],
        "updated_at": deck["updated_at"],
    }


def _card_json(card: DeckCard) -> dict:
    return {
        "card_id": card.card_id,
        "card_name": card.card_name,
        "set_name": card.set_name,
        "side": card.side,
        "quantity": card.quantity,
        "art_donor_card_id": card.art_donor_card_id,
        "art_donor_set": card.art_donor_set,
    }


@router.post("/me/decks", status_code=201)
@limiter.limit("20/minute")
async def save_my_deck(request: Request, body: SaveDeckRequest, user: dict = Depends(current_user)):
    """Validate and store a deck for the signed-in user, returning its summary."""
    try:
        cards, summary = await asyncio.to_thread(_resolve_deck, body.yaml)
        deck = await asyncio.to_thread(_persist_deck, user["id"], body, cards, summary)
    except UnknownCardError as unknown:
        raise HTTPException(
            status_code=400, detail={"error": "unknown_cards", "cards": unknown.unknown}
        )
    except DeckLimitError as limit:
        raise HTTPException(status_code=422, detail=str(limit))
    return {"deck": _public_deck(deck)}


@router.get("/me/decks")
async def list_my_decks(request: Request, user: dict = Depends(current_user)):
    """The signed-in user's saved decks, newest-edited first."""
    rows = await asyncio.to_thread(_list_decks, user["id"])
    return {"decks": [_public_deck(deck) for deck in rows]}


def _list_decks(owner_id: int) -> list[dict]:
    with get_accounts_connection() as conn:
        return deck_repo.list_decks(conn, owner_id)


@router.delete("/me/decks/{slug}")
async def delete_my_deck(request: Request, slug: _Slug, user: dict = Depends(current_user)):
    """Soft-delete one of the signed-in user's decks."""
    if not await asyncio.to_thread(_delete_deck, slug, user["id"]):
        raise HTTPException(status_code=404, detail="Deck not found")
    return {"deleted": slug}


def _delete_deck(slug: str, owner_id: int) -> bool:
    with get_accounts_connection() as conn:
        return deck_repo.soft_delete_deck(conn, slug, owner_id)


@router.get("/decks/{slug}")
async def read_deck(
    request: Request, slug: _Slug, user: dict | None = Depends(current_user_optional)
):
    """A shared deck by slug, with a YAML rendering ready to feed LOAD_DECK.

    Public and unlisted decks are readable by anyone with the link; a private deck is visible only
    to its owner and otherwise 404s, so its existence stays hidden.
    """
    deck = await asyncio.to_thread(_get_deck, slug)
    if deck is None:
        raise HTTPException(status_code=404, detail="Deck not found")
    viewer_id = user["id"] if user else None
    if deck["visibility"] == "private" and deck["owner_id"] != viewer_id:
        raise HTTPException(status_code=404, detail="Deck not found")

    donor_ids = {card.art_donor_card_id for card in deck["cards"] if card.art_donor_card_id}
    donor_names = await asyncio.to_thread(card_display_names, donor_ids)
    deck_yaml = decks.to_yaml(deck["cards"], name=deck["name"], donor_names=donor_names)
    return {
        "deck": _public_deck(deck),
        "cards": [_card_json(card) for card in deck["cards"]],
        "yaml": deck_yaml,
    }


def _get_deck(slug: str) -> dict | None:
    with get_accounts_connection() as conn:
        return deck_repo.get_deck(conn, slug)
