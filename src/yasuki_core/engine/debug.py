from dataclasses import dataclass

from yasuki_core.engine import ops
from yasuki_core.engine.players import PlayerId
from yasuki_core.engine.rules.board.queries import province_cards, province_key_of
from yasuki_core.engine.rules.state import GameState
from yasuki_core.engine.rules.vocabulary.decisions import DecisionRequest, DecisionResponse
from yasuki_core.engine.table import BATTLEFIELD, UNPLACED_BOARD_POS, ZoneKey, ZoneRole
from yasuki_core.game_pieces.cards import L5RCard
from yasuki_core.game_pieces.constants import Side
from yasuki_core.game_pieces.prints import CardPrint, PersonalityPrint


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


@dataclass(frozen=True, slots=True)
class DebugPersonality:
    """A developer's step: put a new copy of a Personality straight into play, from nowhere. The
    seat that took the step then picks which player gets it, on the board.

    Attributes
    ----------
    seat : PlayerId
        The seat that took the step and answers which player gets the Personality.
    card_id : str
        The id the new card takes, chosen by the caller so a replay makes the same card.
    printed : CardPrint
        What the Personality is. A print of any other type is refused when the step is applied.
    """

    seat: PlayerId
    card_id: str
    printed: CardPrint


DebugStep = DebugGold | DebugCard | DebugPersonality


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


@dataclass(frozen=True, slots=True)
class ChooseDebugSeat(DecisionRequest):
    """The seat must choose which player a debug Personality enters play under. The candidates are
    the seats at the table, by ``PlayerId`` name. Nothing is on the table until it is answered.

    Attributes
    ----------
    card_id : str
        The id the Personality takes when it enters play.
    printed : PersonalityPrint
        What the Personality is.
    """

    card_id: str
    printed: PersonalityPrint

    def prompt(self, partial: DecisionResponse = DecisionResponse()) -> str:
        return f"Choose who gets {self.printed.name}"

    def accepts(self, response: DecisionResponse) -> bool:
        return len(response.choices) == 1 and response.choices[0] in self.candidates


def apply_debug(game: GameState, step: DebugStep) -> None:
    """Apply a developer's step to the game, outside any action or decision.

    Raise ``RuntimeError`` while a decision is pending, since a card or Gold appearing under an
    open question would leave the question about a board it was not asked on. Raise ``ValueError``
    for a card id already on the table, a Dynasty card for a seat with no Province card to
    displace, or a Personality step whose print is not a Personality.
    """
    if game.pending is not None:
        raise RuntimeError("a debug step cannot land while a decision is pending")
    match step:
        case DebugGold(seat=seat, amount=amount):
            game.gold[seat] = game.gold.get(seat, 0) + amount
        case DebugCard(seat=seat, card_id=card_id, printed=printed):
            _add_card(game, seat, card_id, printed)
        case DebugPersonality(seat=seat, card_id=card_id, printed=printed):
            _ask_who_gets(game, seat, card_id, printed)


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


def apply_debug_seat(game: GameState, request: ChooseDebugSeat, response: DecisionResponse) -> None:
    """Put the Personality into play under the chosen seat, face up and unplaced, so the client
    clusters it into that seat's home row. Nothing is announced: it did not enter play by any
    action, so no trait or reaction fires."""
    owner = PlayerId[response.choices[0]]
    card = L5RCard(id=request.card_id, printed=request.printed, owner=owner)
    game.table.cards_by_id[card.id] = card
    ops.move_card(game.table, card, BATTLEFIELD, position=UNPLACED_BOARD_POS)


def _ask_who_gets(game: GameState, seat: PlayerId, card_id: str, printed: CardPrint) -> None:
    if card_id in game.table.cards_by_id:
        raise ValueError(f"a card with id {card_id!r} is already on the table")
    if not isinstance(printed, PersonalityPrint):
        raise ValueError(f"{printed.name} is not a Personality")
    candidates = tuple(player.name for player in game.table.seats)
    game.pending = ChooseDebugSeat(seat, candidates, card_id, printed)


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
