from yasuki_core.engine.players import PlayerId
from yasuki_core.engine.rules import flow
from yasuki_core.engine.rules.state import GameState
from yasuki_core.engine.table import DeckKey, TableState, ZoneKey, ZoneRole
from yasuki_core.engine.zones import ProvinceZone
from yasuki_core.game_pieces.constants import Side
from yasuki_core.game_pieces.dynasty import DynastyHolding
from yasuki_core.game_pieces.fate import FateCard
from yasuki_core.game_pieces.pregame import StrongholdCard

# Only shapes duplicated across two or more test modules belong here; one that would have to contort
# to serve a single caller belongs in that caller's module.


def register(state: TableState, card):
    """Index ``card`` in the table's id map and return it. Cards built directly rather than dealt
    are not otherwise reachable by id, and most engine reads go through ``cards_by_id``."""
    state.cards_by_id[card.id] = card
    return card


def put_in_play(target: GameState | TableState, card):
    """Register ``card`` and add it to the battlefield. Accepts a game or a bare table."""
    state = target.table if isinstance(target, GameState) else target
    register(state, card)
    state.battlefield.add(card)
    return card


def holding(
    card_id: str,
    *,
    printed_id: str | None = None,
    owner: PlayerId = PlayerId.P1,
    name: str | None = None,
    keywords: tuple[str, ...] = (),
    gold_production: int = 0,
    gold_cost: int | None = None,
    clan: str | None = None,
    counters: dict[str, int] | None = None,
) -> DynastyHolding:
    """A Dynasty Holding. ``name`` defaults to ``card_id``, which keeps failure output readable."""
    return DynastyHolding(
        id=card_id,
        name=name or card_id,
        side=Side.DYNASTY,
        owner=owner,
        printed_id=printed_id,
        keywords=keywords,
        gold_production=gold_production,
        gold_cost=gold_cost,
        clan=clan,
        counters=dict(counters or {}),
    )


def stronghold(
    owner: PlayerId = PlayerId.P1,
    *,
    gold_production: int = 0,
    clan: str | None = None,
    starting_honor: int = 0,
) -> StrongholdCard:
    return StrongholdCard(
        id=f"{owner.name}-SH",
        name="SH",
        side=Side.STRONGHOLD,
        owner=owner,
        gold_production=gold_production,
        clan=clan,
        starting_honor=starting_honor,
    )


def fate_card(card_id: str, owner: PlayerId, *, name: str = "F") -> FateCard:
    return FateCard(id=card_id, name=name, side=Side.FATE, owner=owner)


def two_seat_game(first_player: PlayerId = PlayerId.P1) -> GameState:
    """An empty two-seat game — the starting point for tests that build their own board."""
    return GameState.start(TableState.empty_two_seat(), first_player)


def dealt_table(*, fate_deck: int = 1, hand: int | None = None) -> TableState:
    """A two-seat table with ``fate_deck`` cards in each seat's fate deck and ``hand`` cards in P1's
    hand. The hand defaults to the maximum, so P1's turns end in a discard while P2's do not."""
    hand = flow.MAX_HAND_SIZE if hand is None else hand
    state = TableState.empty_two_seat()
    for seat in PlayerId:
        state.decks[DeckKey(seat, Side.FATE)].cards = [
            register(state, fate_card(f"{seat.name}-fd{i}", seat)) for i in range(fate_deck)
        ]
    p1_hand = state.zones[ZoneKey(PlayerId.P1, ZoneRole.HAND)]
    for i in range(hand):
        p1_hand.add(register(state, fate_card(f"P1-h{i}", PlayerId.P1, name="H")))
    return state


def province_card(
    target: GameState | TableState,
    card_id: str,
    *,
    seat: PlayerId = PlayerId.P1,
    printed_id: str | None = None,
    keywords: tuple[str, ...] = (),
    gold_cost: int | None = None,
    gold_production: int = 0,
    counters: dict[str, int] | None = None,
    face_up: bool = True,
    index: int = 0,
) -> DynastyHolding:
    """Put a Holding into ``seat``'s province at ``index``, replacing whatever zone was there."""
    state = target.table if isinstance(target, GameState) else target
    card = register(
        state,
        holding(
            card_id,
            printed_id=printed_id,
            owner=seat,
            keywords=keywords,
            gold_cost=gold_cost,
            gold_production=gold_production,
            counters=counters,
        ),
    )
    if face_up:
        card.turn_face_up()
    else:
        card.turn_face_down()
    zone = state.zones.get(ZoneKey(seat, ZoneRole.PROVINCE, index)) or ProvinceZone(owner=seat)
    zone.add(card)
    state.zones[ZoneKey(seat, ZoneRole.PROVINCE, index)] = zone
    return card
