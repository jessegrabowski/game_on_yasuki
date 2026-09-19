from dataclasses import dataclass

from yasuki_core.engine import ops
from yasuki_core.engine.players import PlayerId
from yasuki_core.engine.rules.state import GameState
from yasuki_core.engine.table import ZoneKey, ZoneRole
from yasuki_core.game_pieces.cards import L5RCard
from yasuki_core.game_pieces.constants import Side
from yasuki_core.game_pieces.prints import CardPrint


@dataclass(frozen=True, slots=True)
class DebugGold:
    """A developer's step: put ``amount`` Gold in ``seat``'s pool, from nowhere.

    Attributes
    ----------
    seat : PlayerId
        The seat whose pool grows.
    amount : int
        How much.
    """

    seat: PlayerId
    amount: int


@dataclass(frozen=True, slots=True)
class DebugCard:
    """A developer's step: put a new copy of ``printed`` into ``seat``'s hand or one of its
    Provinces, from nowhere. A card already in that Province goes to the Dynasty discard pile.

    Attributes
    ----------
    seat : PlayerId
        The seat that owns the new card.
    card_id : str
        The id the new card takes, chosen by the caller so a replay makes the same card.
    printed : CardPrint
        What the card is.
    zone : ZoneKey
        Where it lands: the seat's hand, or one of its Provinces.
    """

    seat: PlayerId
    card_id: str
    printed: CardPrint
    zone: ZoneKey


DebugStep = DebugGold | DebugCard

_SIDE_FOR = {ZoneRole.HAND: Side.FATE, ZoneRole.PROVINCE: Side.DYNASTY}


def apply_debug(game: GameState, step: DebugStep) -> None:
    """Apply a developer's step to the game, outside any action or decision.

    Raise ``RuntimeError`` while a decision is pending, since a card or Gold appearing under an
    open question would leave the question about a board it was not asked on. Raise ``ValueError``
    for a card id already on the table, a zone that is neither a hand nor a Province, or a print
    of the wrong side for the zone: a hand holds Fate cards and a Province holds Dynasty cards.
    """
    if game.pending is not None:
        raise RuntimeError("a debug step cannot land while a decision is pending")
    match step:
        case DebugGold(seat=seat, amount=amount):
            game.gold[seat] = game.gold.get(seat, 0) + amount
        case DebugCard(seat=seat, card_id=card_id, printed=printed, zone=zone):
            _place_card(game, seat, card_id, printed, zone)


def _place_card(
    game: GameState, seat: PlayerId, card_id: str, printed: CardPrint, zone: ZoneKey
) -> None:
    table = game.table
    if card_id in table.cards_by_id:
        raise ValueError(f"a card with id {card_id!r} is already on the table")
    if zone.role not in _SIDE_FOR:
        raise ValueError(f"a debug card lands in a hand or a Province, not {zone.role.value}")
    if printed.side is not _SIDE_FOR[zone.role]:
        raise ValueError(f"a {printed.side.value} card cannot land in a {zone.role.value}")
    card = L5RCard(id=card_id, printed=printed, owner=seat)
    table.cards_by_id[card_id] = card
    if zone.role is ZoneRole.PROVINCE:
        for occupant in list(table.zones[zone].cards):
            ops.move_card(table, occupant, ZoneKey(seat, ZoneRole.DYNASTY_DISCARD))
    ops.move_card(table, card, zone)
    if zone.role is ZoneRole.PROVINCE:
        card.turn_face_up()
