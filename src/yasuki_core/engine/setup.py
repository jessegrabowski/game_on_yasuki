from yasuki_core.engine.players import PlayerId
from yasuki_core.engine.table import TableState, ZoneKey, ZoneRole, DeckKey, BoardPos
from yasuki_core.engine.zones import ProvinceZone
from yasuki_core.game_pieces.cards import L5RCard
from yasuki_core.game_pieces.constants import Side
from yasuki_core.game_pieces.factory import ResolvedDeck
from yasuki_core.game_pieces.pregame import StrongholdCard

# Pre-game permanents are dealt face-up into a horizontal row, one row per seat; the client refines
# the final table layout.
_PREGAME_CARD_GAP = 110.0
_PREGAME_ROW_Y = {PlayerId.P1: 0.0, PlayerId.P2: 220.0}


def setup_seat(
    state: TableState,
    seat: PlayerId,
    resolved: ResolvedDeck,
    *,
    dynasty_seed: int,
    fate_seed: int,
) -> None:
    """Build ``seat``'s table slice from its resolved deck.

    Load the dynasty and fate cards into their decks face-down, shuffling each with the given seed,
    open the stronghold's provinces as empty zones, deal the pre-game permanents (stronghold, sensei,
    wind) face-up onto the battlefield, and register every card in the table's identity map. The
    hand, discards, and banishes stay empty — players draw and fill provinces manually — and no deck
    legality is enforced (a manual sandbox).

    Parameters
    ----------
    state : TableState
        The table to populate in place.
    seat : PlayerId
        The seat being set up.
    resolved : ResolvedDeck
        The seat's cards, as produced by ``resolve_decklist``.
    dynasty_seed : int
        Seed for the dynasty deck shuffle.
    fate_seed : int
        Seed for the fate deck shuffle.
    """
    _load_deck(state, DeckKey(seat, Side.DYNASTY), resolved.dynasty, dynasty_seed)
    _load_deck(state, DeckKey(seat, Side.FATE), resolved.fate, fate_seed)
    for idx in range(_province_count(resolved)):
        state.zones[ZoneKey(seat, ZoneRole.PROVINCE, idx)] = ProvinceZone(owner=seat)
    _place_pregame(state, seat, resolved.pre_game)


def _province_count(resolved: ResolvedDeck) -> int:
    stronghold = next(
        (card for card in resolved.pre_game if isinstance(card, StrongholdCard)), None
    )
    if stronghold is not None:
        return stronghold.province_count
    return StrongholdCard.__dataclass_fields__["province_count"].default


def _place_pregame(state: TableState, seat: PlayerId, cards: list[L5RCard]) -> None:
    row_y = _PREGAME_ROW_Y[seat]
    for idx, card in enumerate(cards):
        card.turn_face_up()
        state.cards_by_id[card.id] = card
        state.battlefield.add(card)
        state.positions[card.id] = BoardPos(idx * _PREGAME_CARD_GAP, row_y)


def _load_deck(state: TableState, key: DeckKey, cards: list[L5RCard], seed: int) -> None:
    for card in cards:
        card.turn_face_down()
        state.cards_by_id[card.id] = card
    deck = state.decks[key]
    deck.cards = list(cards)
    deck.shuffle(seed)
