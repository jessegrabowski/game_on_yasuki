from fastapi import APIRouter, HTTPException, Path, Query, Request
from typing import Annotated
from asyncio import to_thread
import logging

from yasuki_core.database import (
    query_cards_page,
    query_random_cards,
    get_card_by_id,
    get_prints_by_card_id,
    get_cards_by_names,
    query_all_sets,
    query_all_formats,
    query_all_decks,
    query_all_clans,
    query_all_types,
    query_types_by_deck,
    get_card_backs,
)
from yasuki_core.card_art import back_era_for_set, classify, load_art_layout
from yasuki_core.search import parse_and_build_query
from yasuki_web.rate_limit import limiter

logger = logging.getLogger(__name__)
router = APIRouter()

# Baseline per-IP throttle for the read endpoints that hit the database. The search endpoint keeps a
# tighter limit and the name-lookup a looser one; everything else shares this default.
_READ_RATE_LIMIT = "120/minute"

# The deck_type enum values; used to reject unknown deck filters with a 422 rather than letting the
# Postgres enum cast fail as a 500.
_VALID_DECKS = {"Fate", "Dynasty", "Pre-Game", "Other"}


@router.get("/cards")
@limiter.limit("60/minute")
async def list_cards(
    request: Request,
    search: Annotated[
        str | None,
        Query(
            description="Search query (supports Scryfall-style syntax: clan:Crane type:personality force>3)"
        ),
    ] = None,
    deck: Annotated[str | None, Query(description="Filter by deck type: dynasty or fate")] = None,
    clan: Annotated[str | None, Query(description="Filter by specific clan")] = None,
    card_type: Annotated[str | None, Query(description="Filter by card type")] = None,
    format: Annotated[
        str | None, Query(description="Filter by format legality (e.g., Ivory Edition)")
    ] = None,
    sort: Annotated[
        str, Query(description="Sort column: name, force, chi, gold_cost, focus, etc.")
    ] = "name",
    order: Annotated[str, Query(description="Sort direction: asc or desc")] = "asc",
    limit: Annotated[int, Query(ge=1, le=1000, description="Maximum number of results")] = 100,
    offset: Annotated[int, Query(ge=0, description="Offset for pagination")] = 0,
):
    """
    List cards with optional filtering and pagination.

    The search parameter supports Scryfall-style query syntax:
    - Plain text searches name and rules text
    - clan:Crane, c:Crane — filter by clan
    - type:personality, t:personality — filter by type
    - force>3, chi>=2, gold<=3 — numeric comparisons
    - is:unique, is:cavalry, is:shadowlands — keyword/trait filters
    - "exact phrase" — exact match
    - -type:event — negation
    - term1 OR term2 — OR logic

    The deck, clan, and card_type query params still work for backwards compatibility
    and are merged with parsed search filters.
    """
    try:
        text_query = ""
        filter_options = {}

        if search:
            text_query, filter_options = parse_and_build_query(search)

        if deck:
            filter_options.setdefault("decks", []).append(deck)
        if clan:
            filter_options.setdefault("clans", []).append(clan)
        if card_type:
            filter_options.setdefault("types", []).append(card_type)
        if format:
            filter_options["legality"] = (format, None)

        results, total = await to_thread(
            query_cards_page,
            text_query=text_query,
            filter_options=filter_options if filter_options else None,
            limit=limit,
            offset=offset,
            sort=sort,
            order=order,
        )

        return {
            "cards": results,
            "total": total,
            "limit": limit,
            "offset": offset,
            "has_more": offset + limit < total,
        }

    except Exception as e:
        logger.error(f"Error listing cards: {e}")
        raise HTTPException(status_code=500, detail="Failed to retrieve cards")


@router.get("/cards/lookup")
@limiter.limit("500/minute")
async def lookup_cards_by_name(
    request: Request,
    name: Annotated[list[str], Query(description="Card names to look up (repeatable)")] = [],
):
    """
    Look up cards by name for deck import.

    Matches against both name and extended_title (case-insensitive) and returns
    each card with its full list of prints for set-specific resolution.
    """
    if len(name) > 200:
        raise HTTPException(status_code=400, detail="Too many names (max 200)")
    try:
        cards = await to_thread(get_cards_by_names, name)
        by_name: dict[str, dict] = {}
        for card in cards:
            key = (card.get("extended_title") or card["name"]).lower()
            by_name[key] = card
        for card in cards:
            name_key = card["name"].lower()
            if name_key not in by_name:
                by_name[name_key] = card
        return {"cards": by_name, "found": len(cards)}
    except Exception as e:
        logger.error(f"Error looking up cards by name: {e}")
        raise HTTPException(status_code=500, detail="Failed to look up cards")


def _prints_with_layout(card: dict, card_id: str) -> list[dict]:
    """Prints for a card, each annotated with its art-swap (era, layout_type) so the browser canvas
    can look up the art rect without reimplementing era classification."""
    prints = get_prints_by_card_id(card_id)
    for print_info in prints:
        set_name = print_info.get("set_name", "")
        era, layout_type = classify(card, set_name)
        print_info["era"] = era
        print_info["layout_type"] = layout_type
        print_info["back_era"] = back_era_for_set(set_name)
    return prints


@router.get("/cards/{card_id}")
@limiter.limit(_READ_RATE_LIMIT)
async def get_card(
    request: Request,
    card_id: Annotated[str, Path(max_length=200, pattern=r"^[\w\s\-\.\,\'\!\(\)]+$")],
):
    """
    Get detailed information about a specific card.

    Includes all print variations with their set codes and image paths.
    """
    try:
        card = await to_thread(get_card_by_id, card_id)
        if not card:
            raise HTTPException(status_code=404, detail=f"Card '{card_id}' not found")

        prints = await to_thread(_prints_with_layout, card, card_id)

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
@limiter.limit(_READ_RATE_LIMIT)
async def list_sets(request: Request):
    """
    List all card sets available in the database.

    Returns set names that can be used for filtering cards by expansion.
    """
    try:
        sets = await to_thread(query_all_sets)
        return {
            "sets": sets,
            "count": len(sets),
        }
    except Exception as e:
        logger.error(f"Error listing sets: {e}")
        raise HTTPException(status_code=500, detail="Failed to retrieve sets")


ARC_ORDER = [
    "Clan Wars (Imperial)",
    "Hidden Emperor (Jade)",
    "Four Winds (Gold)",
    "Rain of Blood (Diamond)",
    "Age of Enlightenment (Lotus)",
    "Race for the Throne (Samurai)",
    "Destroyer War (Celestial)",
    "Age of Conquest (Emperor)",
    "A Brother's Destiny (Twenty Festivals)",
    "War of the Seals (Onyx Edition)",
    "Shattered Empire",
]

OTHER_ORDER = ["Modern", "Legacy", "Not Legal (Proxy)", "Unreleased"]


@router.get("/formats")
@limiter.limit(_READ_RATE_LIMIT)
async def list_formats(request: Request):
    """
    List all game formats in chronological order.

    Returns arc formats (story arcs by release date) followed by
    cross-arc formats like Modern and Legacy.
    """
    try:
        all_formats = set(await to_thread(query_all_formats))
        arcs = [f for f in ARC_ORDER if f in all_formats]
        other = [f for f in OTHER_ORDER if f in all_formats]
        return {
            "formats": arcs + other,
            "arcs": arcs,
            "other": other,
            "count": len(arcs) + len(other),
        }
    except Exception as e:
        logger.error(f"Error listing formats: {e}")
        raise HTTPException(status_code=500, detail="Failed to retrieve formats")


@router.get("/decks")
@limiter.limit(_READ_RATE_LIMIT)
async def list_deck_types(request: Request):
    """
    List available deck types (Dynasty, Fate).

    In L5R, each player has two decks with different card types.
    """
    try:
        deck_types = await to_thread(query_all_decks)
        return {
            "deck_types": deck_types,
            "count": len(deck_types),
        }
    except Exception as e:
        logger.error(f"Error listing deck types: {e}")
        raise HTTPException(status_code=500, detail="Failed to retrieve deck types")


@router.get("/clans")
@limiter.limit(_READ_RATE_LIMIT)
async def list_clans(request: Request):
    """List all clans available in the card database."""
    try:
        clans = await to_thread(query_all_clans)
        return {"clans": clans, "count": len(clans)}
    except Exception as e:
        logger.error(f"Error listing clans: {e}")
        raise HTTPException(status_code=500, detail="Failed to retrieve clans")


@router.get("/card-backs")
@limiter.limit(_READ_RATE_LIMIT)
async def list_card_backs(request: Request):
    """
    List the generic card backs, nested as ``{deck: {era: image_path}}``.

    The deck builder uses these to show a card's reverse when it has no printed back face.
    """
    try:
        backs = await to_thread(get_card_backs)
        nested: dict[str, dict[str, str]] = {}
        for (deck, era), image_path in backs.items():
            nested.setdefault(deck, {})[era] = image_path
        return {"backs": nested}
    except Exception as e:
        logger.error(f"Error listing card backs: {e}")
        raise HTTPException(status_code=500, detail="Failed to retrieve card backs")


@router.get("/art-layout")
@limiter.limit(_READ_RATE_LIMIT)
async def art_layout(request: Request):
    """The art-swap layout data (rects, era bands, layout map) shared with the browser canvas.

    Serving it from the same JSON the Python renderers read keeps the GUI and web composites in
    step."""
    return load_art_layout()


@router.get("/card-types")
@limiter.limit(_READ_RATE_LIMIT)
async def list_card_types(request: Request):
    """List all card types (Personality, Holding, Event, etc.)."""
    try:
        types = await to_thread(query_all_types)
        return {"card_types": types, "count": len(types)}
    except Exception as e:
        logger.error(f"Error listing card types: {e}")
        raise HTTPException(status_code=500, detail="Failed to retrieve card types")


@router.get("/card-types-by-deck")
@limiter.limit(_READ_RATE_LIMIT)
async def list_card_types_by_deck(
    request: Request,
    deck: Annotated[
        str, Query(description="Deck type to filter card types by (e.g. DYNASTY, FATE)")
    ],
):
    """List card types available for a specific deck type."""
    deck_title = deck.title()
    if deck_title not in _VALID_DECKS:
        raise HTTPException(status_code=422, detail=f"Unknown deck type: {deck}")
    try:
        types = await to_thread(query_types_by_deck, [deck_title])
        return {"card_types": types, "deck": deck_title, "count": len(types)}
    except Exception as e:
        logger.error(f"Error listing card types by deck: {e}")
        raise HTTPException(status_code=500, detail="Failed to retrieve card types")


@router.get("/cards/random/{count}")
@limiter.limit(_READ_RATE_LIMIT)
async def random_cards(
    request: Request,
    count: Annotated[int, Path(ge=1, le=50, description="Number of random cards to return")],
    deck: Annotated[str | None, Query(description="Limit random cards to specific deck")] = None,
):
    """
    Get random cards from the database.

    Useful for testing, demo purposes, or generating sample hands.
    """
    try:
        selected = await to_thread(query_random_cards, count, deck)

        return {
            "cards": selected,
            "count": len(selected),
            "requested": count,
        }

    except Exception as e:
        logger.error(f"Error getting random cards: {e}")
        raise HTTPException(status_code=500, detail="Failed to retrieve random cards")
