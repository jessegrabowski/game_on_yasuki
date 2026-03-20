from fastapi import APIRouter, HTTPException, Path, Query
from typing import Annotated
import logging

from app.database import (
    query_all_cards,
    search_cards,
    get_card_by_id,
    get_prints_by_card_id,
    query_all_sets,
    query_all_formats,
    query_all_decks,
)

logger = logging.getLogger(__name__)
router = APIRouter()


@router.get("/cards")
async def list_cards(
    search: Annotated[str | None, Query(description="Search query for card name or text")] = None,
    deck: Annotated[str | None, Query(description="Filter by deck type: dynasty or fate")] = None,
    clan: Annotated[str | None, Query(description="Filter by specific clan")] = None,
    card_type: Annotated[str | None, Query(description="Filter by card type")] = None,
    limit: Annotated[int, Query(ge=1, le=1000, description="Maximum number of results")] = 100,
    offset: Annotated[int, Query(ge=0, description="Offset for pagination")] = 0,
):
    """
    List cards with optional filtering and pagination.

    Returns card data including the first print's image path.
    Use search parameter for fuzzy text matching on name and rules text.
    """
    try:
        if search:
            results = search_cards(query=search, deck_filter=deck)
        else:
            results = query_all_cards()

        if clan:
            results = [c for c in results if c.get("clan") == clan]
        if card_type:
            results = [c for c in results if c.get("type") == card_type]

        total = len(results)
        paginated_results = results[offset : offset + limit]

        return {
            "cards": paginated_results,
            "total": total,
            "limit": limit,
            "offset": offset,
            "has_more": offset + limit < total,
        }

    except Exception as e:
        logger.error(f"Error listing cards: {e}")
        raise HTTPException(status_code=500, detail="Failed to retrieve cards")


@router.get("/cards/{card_id}")
async def get_card(card_id: str):
    """
    Get detailed information about a specific card.

    Includes all print variations with their set codes and image paths.
    """
    try:
        card = get_card_by_id(card_id)
        if not card:
            raise HTTPException(status_code=404, detail=f"Card '{card_id}' not found")

        prints = get_prints_by_card_id(card_id)

        return {
            "card": card,
            "prints": prints,
            "print_count": len(prints),
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error retrieving card {card_id}: {e}")
        raise HTTPException(status_code=500, detail="Failed to retrieve card details")


@router.get("/sets")
async def list_sets():
    """
    List all card sets available in the database.

    Returns set names that can be used for filtering cards by expansion.
    """
    try:
        sets = query_all_sets()
        return {
            "sets": sets,
            "count": len(sets),
        }
    except Exception as e:
        logger.error(f"Error listing sets: {e}")
        raise HTTPException(status_code=500, detail="Failed to retrieve sets")


@router.get("/formats")
async def list_formats():
    """
    List all game formats (e.g., Standard, Extended, Emperor).

    Formats define which cards are legal in different play modes.
    """
    try:
        formats = query_all_formats()
        return {
            "formats": formats,
            "count": len(formats),
        }
    except Exception as e:
        logger.error(f"Error listing formats: {e}")
        raise HTTPException(status_code=500, detail="Failed to retrieve formats")


@router.get("/decks")
async def list_deck_types():
    """
    List available deck types (Dynasty, Fate).

    In L5R, each player has two decks with different card types.
    """
    try:
        deck_types = query_all_decks()
        return {
            "deck_types": deck_types,
            "count": len(deck_types),
        }
    except Exception as e:
        logger.error(f"Error listing deck types: {e}")
        raise HTTPException(status_code=500, detail="Failed to retrieve deck types")


@router.get("/cards/random/{count}")
async def random_cards(
    count: Annotated[int, Path(ge=1, le=50, description="Number of random cards to return")],
    deck: Annotated[str | None, Query(description="Limit random cards to specific deck")] = None,
):
    """
    Get random cards from the database.

    Useful for testing, demo purposes, or generating sample hands.
    """
    import random

    try:
        if deck:
            all_cards = search_cards(deck_filter=deck)
        else:
            all_cards = query_all_cards()

        if not all_cards:
            return {"cards": [], "count": 0}

        selected_count = min(count, len(all_cards))
        selected = random.sample(all_cards, selected_count)

        return {
            "cards": selected,
            "count": len(selected),
            "requested": count,
        }

    except Exception as e:
        logger.error(f"Error getting random cards: {e}")
        raise HTTPException(status_code=500, detail="Failed to retrieve random cards")
