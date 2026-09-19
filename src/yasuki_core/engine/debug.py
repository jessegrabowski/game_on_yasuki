from dataclasses import dataclass

from yasuki_core.engine import ops
from yasuki_core.engine.players import PlayerId
from yasuki_core.engine.rules.board.queries import province_cards, province_key_of
from yasuki_core.engine.rules.state import GameState
from yasuki_core.engine.rules.vocabulary.decisions import DecisionRequest, DecisionResponse
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
    """A developer's step: put a new copy of ``printed`` on the table, from nowhere. A Fate card
    lands in ``seat``'s hand. A Dynasty card lands in one of its Provinces, which the seat picks on
    the board the way it places a Legacy card, discarding the card already there.

    Attributes
    ----------
    seat : PlayerId
        The seat that owns the new card.
    card_id : str
        The id the new card takes, chosen by the caller so a replay makes the same card.
    printed : CardPrint
        What the card is.
    """

    seat: PlayerId
    card_id: str
    printed: CardPrint


DebugStep = DebugGold | DebugCard


@dataclass(frozen=True, slots=True)
class PlaceDebugCard(DecisionRequest):
    """The seat must choose which Province a debug card fills, discarding the card there. The
    candidates are the cards in the seat's Provinces, as for a Legacy placement.

    Attributes
    ----------
    card_id : str
        The new card, already on the table and in no zone.
    """

    card_id: str

    def prompt(self, partial: DecisionResponse = DecisionResponse()) -> str:
        return "Choose a Province for the card, discarding the card there"

    @property
    def confirm_label(self) -> str:
        return "Place"

    def accepts(self, response: DecisionResponse) -> bool:
        return len(response.choices) == 1 and response.choices[0] in self.candidates


def apply_debug(game: GameState, step: DebugStep) -> None:
    """Apply a developer's step to the game, outside any action or decision.

    Raise ``RuntimeError`` while a decision is pending, since a card or Gold appearing under an
    open question would leave the question about a board it was not asked on. Raise ``ValueError``
    for a card id already on the table, or a Dynasty card for a seat with no Province card to
    displace.
    """
    if game.pending is not None:
        raise RuntimeError("a debug step cannot land while a decision is pending")
    match step:
        case DebugGold(seat=seat, amount=amount):
            game.gold[seat] = game.gold.get(seat, 0) + amount
        case DebugCard(seat=seat, card_id=card_id, printed=printed):
            _add_card(game, seat, card_id, printed)


def apply_debug_placement(
    game: GameState, request: PlaceDebugCard, response: DecisionResponse
) -> None:
    """Fill the chosen Province with the debug card, face up, discarding the card there."""
    seat = request.seat
    displaced = game.table.cards_by_id[response.choices[0]]
    zone = province_key_of(game, seat, displaced.id)
    ops.move_card(game.table, displaced, ZoneKey(seat, ZoneRole.DYNASTY_DISCARD))
    card = game.table.cards_by_id[request.card_id]
    ops.move_card(game.table, card, zone)
    card.turn_face_up()


def _add_card(game: GameState, seat: PlayerId, card_id: str, printed: CardPrint) -> None:
    table = game.table
    if card_id in table.cards_by_id:
        raise ValueError(f"a card with id {card_id!r} is already on the table")
    card = L5RCard(id=card_id, printed=printed, owner=seat)
    if printed.side is Side.FATE:
        table.cards_by_id[card_id] = card
        ops.move_card(table, card, ZoneKey(seat, ZoneRole.HAND))
        return
    candidates = tuple(occupant.id for occupant in province_cards(game, seat))
    if not candidates:
        raise ValueError(f"{seat.name} has no Province card to displace")
    table.cards_by_id[card_id] = card
    game.pending = PlaceDebugCard(seat, candidates, card_id)
