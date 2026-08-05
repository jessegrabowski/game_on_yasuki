from pathlib import Path
from typing import Any

from yasuki_core.database import get_cards_by_names
from yasuki_core.decklist import parse_deck_yaml
from yasuki_core.engine.players import PlayerId
from yasuki_core.engine.setup import setup_seat
from yasuki_core.engine.table import TableState
from yasuki_core.game_pieces.factory import resolve_decklist

# A parsed decklist: section names to their entries.
Decklist = dict[str, Any]

# Per-seat (dynasty, fate) shuffle seeds, so the same decklist deals the same board every time.
DEFAULT_DEAL_SEEDS = {PlayerId.P1: (1001, 2001), PlayerId.P2: (1002, 2002)}


def build_state_from_deck(
    deck_path: Path | str,
    opponent_deck_path: Path | str | None = None,
    p1_name: str = "P1",
    p2_name: str = "P2",
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

    Returns
    -------
    tuple of (TableState, PlayerId)
        The dealt table and the seat P1 occupies.
    """
    seats = ((PlayerId.P1, deck_path), (PlayerId.P2, opponent_deck_path or deck_path))
    state = TableState.empty_two_seat(p1_name, p2_name)
    resolved_by_path: dict[str, tuple[Decklist, list[dict]]] = {}
    for seat, path in seats:
        key = str(path)
        if key not in resolved_by_path:
            parsed = parse_deck_yaml(Path(path).read_text())
            resolved_by_path[key] = (parsed, get_cards_by_names(_deck_card_names(parsed)))
        parsed, records = resolved_by_path[key]
        dynasty_seed, fate_seed = DEFAULT_DEAL_SEEDS[seat]
        resolved = resolve_decklist(parsed, records, seat)
        setup_seat(state, seat, resolved, dynasty_seed=dynasty_seed, fate_seed=fate_seed)
    state.validate()
    return state, PlayerId.P1


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
