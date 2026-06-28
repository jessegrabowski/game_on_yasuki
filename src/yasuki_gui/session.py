from pathlib import Path

from yasuki_core.database import get_cards_by_names
from yasuki_core.decklist import parse_deck_yaml
from yasuki_core.engine.players import PlayerId
from yasuki_core.engine.setup import setup_seat
from yasuki_core.engine.table import TableState
from yasuki_core.game_pieces.constants import Side
from yasuki_core.game_pieces.dynasty import (
    DynastyCard,
    DynastyEvent,
    DynastyHolding,
    DynastyPersonality,
)
from yasuki_core.game_pieces.factory import ResolvedDeck, resolve_decklist
from yasuki_core.game_pieces.fate import FateAction, FateAttachment, FateCard, FateRing
from yasuki_core.game_pieces.pregame import StrongholdCard

# The deck dealt to both seats on launch. Bundled in the repo so the desktop has a real board out of
# the box; rendering its art needs the set images on disk (SETS_DIR / YASUKI_SETS_DIR).
DEMO_DECK_PATH = Path(__file__).parent / "assets" / "decks" / "spider_oni_control.yaml"

# Per-seat (dynasty, fate) shuffle seeds, so a fresh launch deals a reproducible board.
_SEEDS = {PlayerId.P1: (1001, 2001), PlayerId.P2: (1002, 2002)}

# A placeholder deck large enough to fill four provinces and draw an opening hand with cards to
# spare. Real decks will come from the database once campaign loading lands; this keeps the client
# launchable with no PostgreSQL connection.
_DYNASTY_PER_SEAT = 14
_FATE_PER_SEAT = 14

_DYNASTY_CYCLE: tuple[tuple[type[DynastyCard], str], ...] = (
    (DynastyPersonality, "Personality"),
    (DynastyHolding, "Holding"),
    (DynastyPersonality, "Personality"),
    (DynastyEvent, "Event"),
)
_FATE_CYCLE: tuple[tuple[type[FateCard], str], ...] = (
    (FateAction, "Strategy"),
    (FateAttachment, "Item"),
    (FateRing, "Ring"),
)


def _resolved_demo_deck(seat: PlayerId) -> ResolvedDeck:
    """Fabricate a placeholder resolved deck for one seat without touching the database."""
    prefix = seat.name
    dynasty: list[DynastyCard] = []
    for i in range(_DYNASTY_PER_SEAT):
        card_cls, label = _DYNASTY_CYCLE[i % len(_DYNASTY_CYCLE)]
        dynasty.append(
            card_cls(id=f"{prefix}-D{i}", name=f"{label} {i + 1}", side=Side.DYNASTY, owner=seat)
        )
    fate: list[FateCard] = []
    for i in range(_FATE_PER_SEAT):
        card_cls, label = _FATE_CYCLE[i % len(_FATE_CYCLE)]
        fate.append(
            card_cls(id=f"{prefix}-F{i}", name=f"{label} {i + 1}", side=Side.FATE, owner=seat)
        )
    stronghold = StrongholdCard(
        id=f"{prefix}-SH",
        name=f"{prefix} Stronghold",
        side=Side.STRONGHOLD,
        owner=seat,
        starting_honor=10,
    )
    return ResolvedDeck(pre_game=[stronghold], dynasty=dynasty, fate=fate)


def build_demo_state() -> tuple[TableState, PlayerId]:
    """Build a fully set-up two-seat table from placeholder decks, returning it and the human seat.

    The human plays P1; P2 is the AI-reserved opponent, dealt the same way so the board is
    populated on both sides. Shuffles use fixed seeds, so a fresh launch is reproducible.
    """
    state = TableState.empty_two_seat("You", "Opponent")
    for seat in PlayerId:
        dynasty_seed, fate_seed = _SEEDS[seat]
        setup_seat(
            state,
            seat,
            _resolved_demo_deck(seat),
            dynasty_seed=dynasty_seed,
            fate_seed=fate_seed,
        )
    state.validate()
    return state, PlayerId.P1


def _deck_card_names(parsed: dict) -> list[str]:
    """Every card name a decklist references, including donor cards named by art-swap entries."""
    names: list[str] = []
    for section in ("pre_game", "dynasty", "fate"):
        for entry in parsed.get(section, []):
            names.append(entry["name"])
            art = entry.get("art")
            if art:
                names.append(art["name"])
    return names


def build_state_from_deck(
    deck_path: Path | str = DEMO_DECK_PATH, p1_name: str = "You", p2_name: str = "Opponent"
) -> tuple[TableState, PlayerId]:
    """Build a two-seat table from a decklist file, dealing the same deck to both seats.

    Resolves the decklist's cards against the database, so it needs a reachable database. P2 is the
    AI-reserved opponent dealt the mirror of the human's deck. Returns the table and the human seat.
    """
    parsed = parse_deck_yaml(Path(deck_path).read_text())
    records = get_cards_by_names(_deck_card_names(parsed))
    state = TableState.empty_two_seat(p1_name, p2_name)
    for seat in PlayerId:
        dynasty_seed, fate_seed = _SEEDS[seat]
        resolved = resolve_decklist(parsed, records, seat)
        setup_seat(state, seat, resolved, dynasty_seed=dynasty_seed, fate_seed=fate_seed)
    state.validate()
    return state, PlayerId.P1
