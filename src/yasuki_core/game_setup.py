from pathlib import Path
from typing import Any

from numpy.random import Generator, default_rng

from yasuki_core.database import get_cards_by_names, get_creates_for_cards
from yasuki_core.decklist import parse_deck_yaml
from yasuki_core.engine.players import PlayerId
from yasuki_core.engine.setup import flip_second_player_stronghold, setup_seat
from yasuki_core.engine.table import TableState
from yasuki_core.game_pieces.factory import build_token_templates, resolve_decklist

# A parsed decklist: section names to their entries.
Decklist = dict[str, Any]


def build_state_from_deck(
    deck_path: Path | str,
    opponent_deck_path: Path | str | None = None,
    p1_name: str = "P1",
    p2_name: str = "P2",
    *,
    rng: Generator | None = None,
) -> tuple[TableState, PlayerId]:
    """
    Build a two-seat table from decklist files, dealing ``deck_path`` to P1 and
    ``opponent_deck_path`` to P2.

    Parameters
    ----------
    deck_path : path or str
        The decklist dealt to P1.
    opponent_deck_path : path or str, optional
        The decklist dealt to P2. Default is P1's deck, a mirror match.
    p1_name : str, optional
        P1's display name. Default 'P1'.
    p2_name : str, optional
        P2's display name. Default 'P2'.
    rng : numpy.random.Generator, optional
        Split into one stream per seat, so a caller holding a seeded generator lays out the same
        board. Default None, which deals from system entropy — what a game wants, where a repeated
        opening is a defect.

    Returns
    -------
    tuple of (TableState, PlayerId)
        The dealt table and the seat taking the first turn. Turn order is resolved by Family Honor:
        the lower-honor seat goes second and has its stronghold flipped to its back face, when it
        has one. Two seats on equal honor are separated by a draw.
    """
    seats = ((PlayerId.P1, deck_path), (PlayerId.P2, opponent_deck_path or deck_path))
    state = TableState.empty_two_seat(p1_name, p2_name)
    deal = default_rng() if rng is None else rng
    # One extra stream for the turn-order tie-break; the per-seat children are unchanged by it.
    *seat_streams, order_stream = deal.spawn(len(seats) + 1)
    seat_rngs = dict(zip((seat for seat, _ in seats), seat_streams, strict=True))
    resolved_by_path: dict[str, tuple[Decklist, list[dict], dict[str, list[str]]]] = {}
    for seat, path in seats:
        key = str(path)
        if key not in resolved_by_path:
            parsed = parse_deck_yaml(Path(path).read_text())
            records = get_cards_by_names(_deck_card_names(parsed))
            # One relational pull of every token the deck can create, so a card that creates one
            # mid-game needs no live database call — the templates sit on the table for the rest of
            # the game.
            creates, tokens = get_creates_for_cards([record["card_id"] for record in records])
            state.creatable_tokens.update(build_token_templates(tokens))
            resolved_by_path[key] = (parsed, records, creates)
        parsed, records, creates = resolved_by_path[key]
        resolved = resolve_decklist(parsed, records, seat, creates)
        setup_seat(state, seat, resolved, rng=seat_rngs[seat])
    second = flip_second_player_stronghold(state, (PlayerId.P1, PlayerId.P2), rng=order_stream)
    first = PlayerId.P2 if second is PlayerId.P1 else PlayerId.P1
    state.validate()
    return state, first


def _deck_card_names(parsed: Decklist) -> list[str]:
    """Every card name a decklist references, including donor cards named by art-swap entries."""
    names: list[str] = []
    for section in ("pre_game", "dynasty", "fate"):
        for entry in parsed.get(section, []):
            names.append(entry["name"])
            art = entry.get("art")
            if art:
                names.append(art["name"])
    return names
