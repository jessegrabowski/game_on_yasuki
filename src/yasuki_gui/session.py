from pathlib import Path

from yasuki_core.engine.players import PlayerId
from yasuki_core.game_setup import DEFAULT_DEAL_SEEDS
from yasuki_core.engine.setup import setup_seat
from yasuki_core.engine.table import TableState
from yasuki_core.game_pieces.constants import Side
from yasuki_core.game_pieces.dynasty import (
    DynastyCard,
    DynastyEvent,
    DynastyHolding,
    DynastyPersonality,
)
from yasuki_core.game_pieces.factory import ResolvedDeck
from yasuki_core.game_pieces.fate import FateAction, FateAttachment, FateCard, FateRing
from yasuki_core.game_pieces.pregame import StrongholdCard

# The deck dealt to both seats on launch. Bundled in the repo so the desktop has a real board out of
# the box; rendering its art needs the set images on disk (SETS_DIR / YASUKI_SETS_DIR).
DEMO_DECK_PATH = Path(__file__).parent / "assets" / "decks" / "spider_oni_control.yaml"

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
    # One Legacy holding so the Legacy rulebook ability has something to find; without it every
    # Legacy search would whiff and lose the game.
    dynasty.append(
        DynastyHolding(
            id=f"{prefix}-LEG",
            name="Ancestral Shrine",
            side=Side.DYNASTY,
            owner=seat,
            keywords=("Legacy",),
        )
    )
    # A Millet Farm so the activated-ability path is exercisable: once recruited it can bow to give
    # a Farm (itself, at least) +2 Gold Production.
    dynasty.append(
        DynastyHolding(
            id=f"{prefix}-MILLET",
            name="Millet Farm",
            side=Side.DYNASTY,
            owner=seat,
            printed_id="millet_farm",
            keywords=("Farm",),
            gold_cost=1,
            gold_production=1,
        )
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
        gold_production=8,
    )
    return ResolvedDeck(pre_game=[stronghold], dynasty=dynasty, fate=fate)


def build_demo_state() -> tuple[TableState, PlayerId]:
    """Build a fully set-up two-seat table from placeholder decks, returning it and the human seat.

    The human plays P1; P2 is the AI-reserved opponent, dealt the same way so the board is
    populated on both sides. Shuffles use fixed seeds, so a fresh launch is reproducible.
    """
    state = TableState.empty_two_seat("You", "Opponent")
    for seat in PlayerId:
        dynasty_seed, fate_seed = DEFAULT_DEAL_SEEDS[seat]
        setup_seat(
            state,
            seat,
            _resolved_demo_deck(seat),
            dynasty_seed=dynasty_seed,
            fate_seed=fate_seed,
        )
    state.validate()
    return state, PlayerId.P1
