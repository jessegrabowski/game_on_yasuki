from numpy.random import Generator
from dataclasses import dataclass
from enum import Enum
from typing import ClassVar

from yasuki_core.engine.players import PlayerId
from yasuki_core.game_pieces.counters import Counter
from yasuki_core.engine.table import (
    AttachTarget,
    BoardPos,
    DeckKey,
    MoveDest,
    ZoneKey,
)
from yasuki_core.game_pieces.prints import CardPrint


class IntentOp(str, Enum):
    MOVE_CARD = "MOVE_CARD"
    MOVE_DECK_TOP = "MOVE_DECK_TOP"
    SET_CARD_POS = "SET_CARD_POS"
    SET_CARD_POSITIONS = "SET_CARD_POSITIONS"
    REORDER_HAND = "REORDER_HAND"
    REORDER_PILE = "REORDER_PILE"
    RAISE = "RAISE"
    BOW = "BOW"
    UNBOW = "UNBOW"
    FLIP = "FLIP"
    FLIP_FACE = "FLIP_FACE"
    INVERT = "INVERT"
    SHOW = "SHOW"
    UNSHOW = "UNSHOW"
    PEEK = "PEEK"
    UNPEEK = "UNPEEK"
    DRAW = "DRAW"
    SHUFFLE = "SHUFFLE"
    FLIP_DECK_TOP = "FLIP_DECK_TOP"
    SEARCH_DECK = "SEARCH_DECK"
    FILL_PROVINCE = "FILL_PROVINCE"
    DESTROY_PROVINCE = "DESTROY_PROVINCE"
    DISCARD_PROVINCE = "DISCARD_PROVINCE"
    CREATE_PROVINCE = "CREATE_PROVINCE"
    SET_HONOR = "SET_HONOR"
    SET_NOTE = "SET_NOTE"
    ADJUST_COUNTER = "ADJUST_COUNTER"
    GIVE_CONTROL = "GIVE_CONTROL"
    SPAWN_CARD = "SPAWN_CARD"
    REMOVE_CARD = "REMOVE_CARD"
    ATTACH = "ATTACH"
    DETACH = "DETACH"
    FLIP_COIN = "FLIP_COIN"
    ROLL_DICE = "ROLL_DICE"


@dataclass(frozen=True, slots=True)
class MoveCard:
    """Move one card to a zone, deck, or the shared battlefield.

    The universal mover behind hand↔battlefield↔zone↔deck transfers. ``position`` is set only when
    ``to`` is the battlefield, giving the card its table coordinates. ``to_bottom`` applies only to
    a deck destination: True slides the card under the deck instead of onto its top. ``index`` applies
    only to a hand destination: the slot the card lands in, clamped into range; None appends it.
    ``face_down`` applies only to a battlefield destination: True lays the card face down as it lands
    and privately peeks it back to the acting seat, so its owner still reads their own card (focusing
    in a duel) while the opponent sees only a back.
    """

    card_id: str
    to: MoveDest
    position: BoardPos | None = None
    to_bottom: bool = False
    index: int | None = None
    face_down: bool = False
    op: ClassVar[IntentOp] = IntentOp.MOVE_CARD


@dataclass(frozen=True, slots=True)
class MoveDeckTop:
    """Pop a deck's top card and move it to a zone, deck, or the shared battlefield.

    The deck-sourced counterpart to ``MoveCard`` — for dragging a deck's top card onto the table.
    ``position`` is honored only for a battlefield destination. Owner-gated on the deck.
    """

    deck: DeckKey
    to: MoveDest
    position: BoardPos | None = None
    op: ClassVar[IntentOp] = IntentOp.MOVE_DECK_TOP


@dataclass(frozen=True, slots=True)
class SetCardPos:
    """Reposition one card freely on the shared battlefield."""

    card_id: str
    x: float
    y: float
    op: ClassVar[IntentOp] = IntentOp.SET_CARD_POS


@dataclass(frozen=True, slots=True)
class SetCardPositions:
    """Reposition several battlefield cards in one message, the wire form of a group drag. Each
    member is gated independently, so cards the seat does not own or that have left the battlefield
    are skipped rather than failing the whole move."""

    moves: tuple[tuple[str, float, float], ...]
    op: ClassVar[IntentOp] = IntentOp.SET_CARD_POSITIONS


@dataclass(frozen=True, slots=True)
class ReorderHand:
    """Move a card already in the acting seat's own hand to a new slot. The index is clamped into
    range, and a move that leaves the order unchanged produces no event."""

    card_id: str
    index: int
    op: ClassVar[IntentOp] = IntentOp.REORDER_HAND


@dataclass(frozen=True, slots=True)
class ReorderPile:
    """Move a card within the acting seat's own deck or discard pile to a new slot. ``index`` is the
    target position in the top-first order the owner sees (the deck's next-drawn card, or the discard's
    top, is index 0). The index is clamped; a no-op move produces no event. Owner-gated."""

    pile: "DeckKey | ZoneKey"
    card_id: str
    index: int
    op: ClassVar[IntentOp] = IntentOp.REORDER_PILE


@dataclass(frozen=True, slots=True)
class Raise:
    """Bring one battlefield card to the top of the stacking order without moving it. Owner-gated."""

    card_id: str
    op: ClassVar[IntentOp] = IntentOp.RAISE


@dataclass(frozen=True, slots=True)
class SetNote:
    """Set or clear a free-text annotation on a face-up card; an empty note removes it. Either player
    may note any card whose face is public — the note is a shared marker, not an owned action."""

    card_id: str
    note: str | None
    op: ClassVar[IntentOp] = IntentOp.SET_NOTE


@dataclass(frozen=True, slots=True)
class AdjustCounter:
    """Add ``delta`` to a ``counter`` on a face-up card, flooring at zero. Either player may adjust
    any public card's counters — effects legitimately token an opponent's cards, so like a note
    this is a shared physical act, not an owned one."""

    card_id: str
    counter: Counter
    delta: int
    op: ClassVar[IntentOp] = IntentOp.ADJUST_COUNTER


@dataclass(frozen=True, slots=True)
class GiveControl:
    """Hand control of a face-up battlefield card to the opponent: the card's owner becomes the other
    seat. Owner-gated — only a card you control may be given away, and only from the shared battlefield,
    where a card's owner is free to differ from its zone."""

    card_id: str
    op: ClassVar[IntentOp] = IntentOp.GIVE_CONTROL


@dataclass(frozen=True, slots=True)
class CardFlagIntent:
    """Base for flag operations that target one or more cards, applied atomically as a batch."""

    card_ids: tuple[str, ...]
    op: ClassVar[IntentOp]

    def __post_init__(self):
        if not isinstance(self.card_ids, tuple):
            object.__setattr__(self, "card_ids", tuple(self.card_ids))


@dataclass(frozen=True, slots=True)
class Bow(CardFlagIntent):
    op: ClassVar[IntentOp] = IntentOp.BOW


@dataclass(frozen=True, slots=True)
class Unbow(CardFlagIntent):
    op: ClassVar[IntentOp] = IntentOp.UNBOW


@dataclass(frozen=True, slots=True)
class Flip(CardFlagIntent):
    op: ClassVar[IntentOp] = IntentOp.FLIP


@dataclass(frozen=True, slots=True)
class FlipFace(CardFlagIntent):
    """Turn a double-faced card to its other face; a no-op for single-faced cards."""

    op: ClassVar[IntentOp] = IntentOp.FLIP_FACE


@dataclass(frozen=True, slots=True)
class Invert(CardFlagIntent):
    op: ClassVar[IntentOp] = IntentOp.INVERT


@dataclass(frozen=True, slots=True)
class Show:
    """Show one of your own cards to your opponent. Owner-gated. A face-down card stays a back to its
    owner while the opponent gains sight of it; a hand card the owner already reads becomes public to
    both seats."""

    card_id: str
    op: ClassVar[IntentOp] = IntentOp.SHOW


@dataclass(frozen=True, slots=True)
class Unshow:
    """Stop showing one of your own cards to your opponent. Owner-gated."""

    card_id: str
    op: ClassVar[IntentOp] = IntentOp.UNSHOW


@dataclass(frozen=True, slots=True)
class Peek:
    """Privately peek at one of your own face-down cards (or an owner-less public one). Owner-gated:
    you cannot peek a card the opponent holds — they reveal those to you with Show."""

    card_id: str
    op: ClassVar[IntentOp] = IntentOp.PEEK


@dataclass(frozen=True, slots=True)
class Unpeek:
    """Stop peeking at one card, removing the acting seat from its peekers. Not owner-gated."""

    card_id: str
    op: ClassVar[IntentOp] = IntentOp.UNPEEK


@dataclass(frozen=True, slots=True)
class Draw:
    """Draw the top card of a deck; routing (hand/province/battlefield) is decided on apply."""

    deck: DeckKey
    op: ClassVar[IntentOp] = IntentOp.DRAW


@dataclass(frozen=True, slots=True)
class Shuffle:
    """Shuffle a deck with an explicit seed so the new order is reproducible."""

    deck: DeckKey
    seed: int
    op: ClassVar[IntentOp] = IntentOp.SHUFFLE


@dataclass(frozen=True, slots=True)
class FlipDeckTop:
    """Flip a deck's top card face up or down in place, revealing it without drawing."""

    deck: DeckKey
    op: ClassVar[IntentOp] = IntentOp.FLIP_DECK_TOP


@dataclass(frozen=True, slots=True)
class SearchDeck:
    """Request a deck's ordered contents; the owner alone receives them. ``limit`` bounds the look to
    the top N cards (None searches the whole deck). Pulling a card is a follow-up ``MoveCard``."""

    deck: DeckKey
    limit: int | None = None
    op: ClassVar[IntentOp] = IntentOp.SEARCH_DECK


@dataclass(frozen=True, slots=True)
class FillProvince:
    """Draw a dynasty card face-down into an empty province."""

    zone: ZoneKey
    op: ClassVar[IntentOp] = IntentOp.FILL_PROVINCE


@dataclass(frozen=True, slots=True)
class DestroyProvince:
    """Discard the province's contents face-up and remove the province zone."""

    zone: ZoneKey
    op: ClassVar[IntentOp] = IntentOp.DESTROY_PROVINCE


@dataclass(frozen=True, slots=True)
class DiscardProvince:
    """Move the province's top card to the dynasty discard, face-up."""

    zone: ZoneKey
    op: ClassVar[IntentOp] = IntentOp.DISCARD_PROVINCE


@dataclass(frozen=True, slots=True)
class CreateProvince:
    """Add a fresh province zone for the acting seat."""

    op: ClassVar[IntentOp] = IntentOp.CREATE_PROVINCE


@dataclass(frozen=True, slots=True)
class SetHonor:
    """Adjust the acting seat's honor, either by a relative ``delta`` or to an absolute ``value``.

    Exactly one of ``delta`` or ``value`` must be given.
    """

    delta: int | None = None
    value: int | None = None
    op: ClassVar[IntentOp] = IntentOp.SET_HONOR

    def __post_init__(self):
        if (self.delta is None) == (self.value is None):
            raise ValueError("SetHonor requires exactly one of delta or value")


@dataclass(frozen=True, slots=True)
class SpawnCard:
    """Put a new public, face-up token on the shared battlefield, copied from a source card.

    The card id is assigned by the caller and recorded, so a replay reproduces the same card. The
    source is exactly one of: ``token_id`` (a creatable-token print on the table), ``source_card_id``
    (a visible in-play card, whose presented face is copied), or ``printed`` (a print the web layer
    pre-resolved, e.g. a database search result). The spawned card is owned by the acting seat: face up and visible to both,
    but only its creator may move or remove it (control can later be handed over with GiveControl).

    ``zone`` lands the card in one of the acting seat's own zones instead of the battlefield, where
    a card has no board position. A card in a hand is otherwise visible only to its owner, so
    ``shown`` marks one that every seat may identify where it sits.
    """

    card_id: str
    position: BoardPos | None = None
    token_id: str | None = None
    source_card_id: str | None = None
    printed: CardPrint | None = None
    zone: ZoneKey | None = None
    shown: bool = False
    op: ClassVar[IntentOp] = IntentOp.SPAWN_CARD


@dataclass(frozen=True, slots=True)
class RemoveCard:
    """Take a card off the table entirely, wherever it sits."""

    card_id: str
    op: ClassVar[IntentOp] = IntentOp.REMOVE_CARD


@dataclass(frozen=True, slots=True)
class Attach:
    """Stack a battlefield card behind another card or a province, so it renders behind the parent.

    Presentation only, and deliberately unconstrained: the manual surface has no rules
    interpretation, so any card you control may be stacked behind any target, and doing so puts
    nothing in a unit. ``to`` is a parent card id or a province ``ZoneKey``. The child keeps its own
    board position; the vertical shift that stacks it behind the parent is a rendering concern, not
    stored here. Re-stacking on the same target, a self-attach, or one that would form a cycle
    produces no event.
    """

    card_id: str
    to: AttachTarget
    op: ClassVar[IntentOp] = IntentOp.ATTACH


@dataclass(frozen=True, slots=True)
class Detach:
    """Unstack a card from the parent it renders behind, leaving anything stacked on it in place.
    Owner-gated. A card that is not stacked produces no event."""

    card_id: str
    op: ClassVar[IntentOp] = IntentOp.DETACH


COIN_FACES = ("Heads", "Tails")


@dataclass(frozen=True, slots=True)
class FlipCoin:
    """Announce an already-flipped fair coin, ``result`` being the face it landed on. A read-only
    table event: it changes no piece. Build it with :func:`~.flip_coin` so the face is drawn rather
    than chosen."""

    result: str
    op: ClassVar[IntentOp] = IntentOp.FLIP_COIN

    def __post_init__(self):
        if self.result not in COIN_FACES:
            raise ValueError(f"FlipCoin result must be one of {COIN_FACES}")


@dataclass(frozen=True, slots=True)
class RollDice:
    """Announce an already-rolled ``sides``-sided die. Like :class:`~.FlipCoin` a read-only table
    event: it changes no piece. ``sides`` must be at least 2 and ``face`` must land within them.
    Build it with :func:`~.roll_dice` so the face is drawn rather than chosen."""

    face: int
    sides: int = 6
    op: ClassVar[IntentOp] = IntentOp.ROLL_DICE

    def __post_init__(self):
        if self.sides < 2:
            raise ValueError("RollDice requires at least 2 sides")
        if not 1 <= self.face <= self.sides:
            raise ValueError(f"RollDice face {self.face} is not on a d{self.sides}")


def flip_coin(rng: Generator) -> FlipCoin:
    """Flip a fair coin from ``rng`` and return the intent announcing it."""
    return FlipCoin(COIN_FACES[rng.integers(2)])


def roll_dice(rng: Generator, sides: int = 6) -> RollDice:
    """Roll one ``sides``-sided die from ``rng`` and return the intent announcing it."""
    return RollDice(int(rng.integers(1, sides + 1)), sides)


Intent = (
    MoveCard
    | MoveDeckTop
    | SetCardPos
    | SetCardPositions
    | ReorderHand
    | ReorderPile
    | Raise
    | SetNote
    | AdjustCounter
    | GiveControl
    | Bow
    | Unbow
    | Flip
    | FlipFace
    | Invert
    | Show
    | Unshow
    | Peek
    | Unpeek
    | Draw
    | Shuffle
    | FlipDeckTop
    | SearchDeck
    | FillProvince
    | DestroyProvince
    | DiscardProvince
    | CreateProvince
    | SetHonor
    | SpawnCard
    | RemoveCard
    | Attach
    | Detach
    | FlipCoin
    | RollDice
)


@dataclass(frozen=True, slots=True)
class Event:
    """A canonical record of one accepted mutation, for logging, redaction, and replay.

    Attributes
    ----------
    seq : int
        The table's version after the mutation; equals the prior ``seq`` for accepted read-only
        intents (``SEARCH_DECK``) that produce an event without changing state.
    seat : PlayerId
        The seat that acted.
    intent : Intent
        The fully resolved operation that occurred. For draws and province fills this is the
        ``MoveCard`` the server decided, not the originating ``Draw``/``FillProvince``.
    cards : tuple of str
        Ids of the cards whose state materially changed; the changed subset for batched flag ops.
    """

    seq: int
    seat: PlayerId
    intent: Intent
    cards: tuple[str, ...] = ()
