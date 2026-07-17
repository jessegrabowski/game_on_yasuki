import random
from dataclasses import dataclass
from enum import Enum
from typing import ClassVar

from yasuki_core.engine.players import PlayerId
from yasuki_core.engine.zones import ProvinceZone
from yasuki_core.game_pieces.cards import L5RCard
from yasuki_core.game_pieces.constants import Side
from yasuki_core.game_pieces.counters import Counter
from yasuki_core.engine import ops
from yasuki_core.engine.table import (
    BATTLEFIELD,
    UNPLACED_BOARD_POS,
    AttachTarget,
    BoardPos,
    DeckKey,
    MoveDest,
    TableState,
    ZoneKey,
    ZoneRole,
    owns_card,
    owns_deck,
    owns_zone,
    zone_accepts,
    zone_owned_by_card,
)


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
    """Put a new public, face-up card on the shared battlefield (tokens, copies, sandbox pieces).

    The card id is assigned by the caller and recorded, so a replay reproduces the same card. The
    card is unowned (public), so either seat may then move or remove it.
    """

    card_id: str
    name: str
    side: Side
    image: str | None
    position: BoardPos
    op: ClassVar[IntentOp] = IntentOp.SPAWN_CARD


@dataclass(frozen=True, slots=True)
class RemoveCard:
    """Take a card off the table entirely, wherever it sits."""

    card_id: str
    op: ClassVar[IntentOp] = IntentOp.REMOVE_CARD


@dataclass(frozen=True, slots=True)
class Attach:
    """Attach a battlefield card to another card or to a province, so it rides behind the parent.

    ``to`` is either the parent card id — the child (a follower, item, or spell) sits behind that
    battlefield card, shifted so its title still reads — or a province ``ZoneKey``, for a
    fortification or region hung on a province. Owner-gated on the child alone: you may attach any
    card you control to any target. The child keeps its own board position; the vertical shift that
    stacks it behind the parent is a rendering concern, not stored here. Re-attaching to the same
    target, a self-attach, or one that would form a cycle produces no event.
    """

    card_id: str
    to: AttachTarget
    op: ClassVar[IntentOp] = IntentOp.ATTACH


@dataclass(frozen=True, slots=True)
class Detach:
    """Break a card's own attachment to its parent in place, leaving anything hung off it attached.
    Owner-gated. A card that is not attached produces no event."""

    card_id: str
    op: ClassVar[IntentOp] = IntentOp.DETACH


@dataclass(frozen=True, slots=True)
class FlipCoin:
    """Flip a fair coin, its result reproducible from the explicit ``seed``. A read-only table event:
    it changes no piece, only announcing heads or tails to both seats."""

    seed: int
    op: ClassVar[IntentOp] = IntentOp.FLIP_COIN


@dataclass(frozen=True, slots=True)
class RollDice:
    """Roll one ``sides``-sided die, its face reproducible from the explicit ``seed``. Like
    ``FlipCoin`` a read-only table event: it changes no piece, only announcing the rolled face to
    both seats. ``sides`` must be at least 2."""

    seed: int
    sides: int = 6
    op: ClassVar[IntentOp] = IntentOp.ROLL_DICE

    def __post_init__(self):
        if self.sides < 2:
            raise ValueError("RollDice requires at least 2 sides")


def coin_flip_outcome(seed: int) -> str:
    """Return the reproducible coin result, ``"Heads"`` or ``"Tails"``, for a flip's ``seed``. Pure
    in the seed so the handler, the game-log line, and a replay all agree."""
    return "Heads" if random.Random(seed).getrandbits(1) else "Tails"


def dice_roll_outcome(seed: int, sides: int) -> int:
    """Return the reproducible die face, an int in ``1..sides``, for a roll's ``seed`` and
    ``sides``. Pure in its arguments, mirroring ``coin_flip_outcome``."""
    return random.Random(seed).randint(1, sides)


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


def _move_card(state: TableState, seat: PlayerId, intent: MoveCard) -> list[Event]:
    card = state.cards_by_id.get(intent.card_id)
    if card is None or not owns_card(state, seat, intent.card_id):
        return []
    dest = intent.to

    if dest == BATTLEFIELD:
        ops.move_card(state, card, BATTLEFIELD, position=intent.position)
        if intent.face_down:
            # A card laid face down is a back to everyone, its owner included; peeking it back keeps
            # the player able to read their own focused card while the opponent sees only a back.
            card.turn_face_down()
            card.add_peeker(seat)
        state.seq += 1
        pos = state.positions[card.id]
        return [
            Event(
                state.seq,
                seat,
                MoveCard(card.id, BATTLEFIELD, pos, face_down=intent.face_down),
                (card.id,),
            )
        ]

    if isinstance(dest, DeckKey):
        if not owns_deck(state, seat, dest) or dest.side is not card.side:
            return []
        ops.move_card(state, card, dest, to_bottom=intent.to_bottom)
        state.seq += 1
        return [
            Event(state.seq, seat, MoveCard(card.id, dest, to_bottom=intent.to_bottom), (card.id,))
        ]

    zone = state.zones.get(dest)
    if (
        zone is None
        or not owns_zone(state, seat, dest)
        or not zone_owned_by_card(zone, card)
        or not zone_accepts(zone, card)
    ):
        return []
    # Dropping a card onto the zone it already occupies changes nothing, so it produces no event.
    if not ops.move_card(state, card, dest, index=intent.index):
        return []
    state.seq += 1
    return [Event(state.seq, seat, MoveCard(card.id, dest), (card.id,))]


def _move_deck_top(state: TableState, seat: PlayerId, intent: MoveDeckTop) -> list[Event]:
    # Source the deck's top card, then route it exactly like a MoveCard — the deck owner alone may
    # do this, and the card carries the owner's id so the delegated ownership gate passes.
    if not owns_deck(state, seat, intent.deck):
        return []
    cards = state.decks[intent.deck].cards
    if not cards:
        return []
    return _move_card(state, seat, MoveCard(cards[-1].id, intent.to, intent.position))


def _set_card_pos(state: TableState, seat: PlayerId, intent: SetCardPos) -> list[Event]:
    card = state.cards_by_id.get(intent.card_id)
    if card is None or not owns_card(state, seat, intent.card_id):
        return []
    if not any(held is card for held in state.battlefield.cards):
        return []
    if not ops.set_position(state, card, intent.x, intent.y):
        return []
    state.seq += 1
    return [Event(state.seq, seat, intent, (card.id,))]


def _set_card_positions(state: TableState, seat: PlayerId, intent: SetCardPositions) -> list[Event]:
    changed = []
    for card_id, x, y in intent.moves:
        card = state.cards_by_id.get(card_id)
        if card is None or not owns_card(state, seat, card_id):
            continue
        if not any(held is card for held in state.battlefield.cards):
            continue
        if ops.set_position(state, card, x, y):
            changed.append(card.id)
    if not changed:
        return []
    state.seq += 1
    return [Event(state.seq, seat, intent, tuple(changed))]


def _reorder_hand(state: TableState, seat: PlayerId, intent: ReorderHand) -> list[Event]:
    if not ops.reorder_in_hand(state, seat, intent.card_id, intent.index):
        return []
    state.seq += 1
    return [Event(state.seq, seat, intent, (intent.card_id,))]


def _reorder_pile(state: TableState, seat: PlayerId, intent: ReorderPile) -> list[Event]:
    if getattr(intent.pile, "owner", None) != seat:
        return []
    if not ops.reorder_in_pile(state, intent.pile, intent.card_id, intent.index):
        return []
    state.seq += 1
    return [Event(state.seq, seat, intent, (intent.card_id,))]


def _raise(state: TableState, seat: PlayerId, intent: Raise) -> list[Event]:
    card = state.cards_by_id.get(intent.card_id)
    if card is None or not owns_card(state, seat, intent.card_id):
        return []
    cards = state.battlefield.cards
    if not cards or cards[-1] is card or not any(held is card for held in cards):
        return []
    ops.bring_to_top(state, card)
    state.seq += 1
    return [Event(state.seq, seat, intent, (card.id,))]


def _set_note(state: TableState, seat: PlayerId, intent: SetNote) -> list[Event]:
    card = state.cards_by_id.get(intent.card_id)
    if card is None or not card.face_up:
        return []
    note = (intent.note or "").strip() or None
    if note == card.note:
        return []
    card.set_note(note)
    state.seq += 1
    return [Event(state.seq, seat, intent, (card.id,))]


def _adjust_counter(state: TableState, seat: PlayerId, intent: AdjustCounter) -> list[Event]:
    card = state.cards_by_id.get(intent.card_id)
    if card is None or not card.face_up:
        return []
    key = intent.counter.key
    before = card.counters.get(key, 0)
    # adjust_counter floors at zero; a floored no-op emits nothing.
    after = max(0, before + intent.delta)
    if after == before:
        return []
    card.adjust_counter(key, intent.delta)
    state.seq += 1
    return [Event(state.seq, seat, intent, (card.id,))]


def _give_control(state: TableState, seat: PlayerId, intent: GiveControl) -> list[Event]:
    card = state.cards_by_id.get(intent.card_id)
    # Only the controller may give a face-up card away, matching the client gate: a public (owner-less)
    # card has no controller to transfer, so it is refused as well.
    if card is None or not card.face_up or card.owner != seat:
        return []
    # Only a card on the shared battlefield may change hands; reassigning one held in an owned zone
    # (hand, deck, province) would break the zone/owner invariant the table validates.
    if not any(held is card for held in state.battlefield.cards):
        return []
    opponent = next((other for other in state.seats if other != seat), None)
    if opponent is None:
        return []
    card.set_owner(opponent)
    state.seq += 1
    return [Event(state.seq, seat, intent, (card.id,))]


def _bow_card(card: L5RCard) -> bool:
    if card.bowed:
        return False
    card.bow()
    return True


def _unbow_card(card: L5RCard) -> bool:
    if not card.bowed:
        return False
    card.unbow()
    return True


def _flip_card(card: L5RCard) -> bool:
    # Turning the card over consumes any private peek: flipping it face up makes it public, and
    # flipping it back down must yield a genuine back, not one its former peekers still read.
    card.flip()
    card.clear_peekers()
    return True


def _flip_face_card(card: L5RCard) -> bool:
    if card.back_card_id is None:
        return False
    card.flip_face()
    return True


def _invert_card(card: L5RCard) -> bool:
    if card.inverted:
        card.uninvert()
    else:
        card.invert()
    return True


_FLAG_MUTATORS = {
    IntentOp.BOW: _bow_card,
    IntentOp.UNBOW: _unbow_card,
    IntentOp.FLIP: _flip_card,
    IntentOp.FLIP_FACE: _flip_face_card,
    IntentOp.INVERT: _invert_card,
}


def _apply_flag(state: TableState, seat: PlayerId, intent: CardFlagIntent) -> list[Event]:
    # Atomic: reject the whole batch unless every target is known and owned.
    cards = []
    for card_id in intent.card_ids:
        if not owns_card(state, seat, card_id):
            return []
        cards.append(state.cards_by_id[card_id])
    mutate = _FLAG_MUTATORS[intent.op]
    changed = tuple(card.id for card in cards if mutate(card))
    if not changed:
        return []
    state.seq += 1
    return [Event(state.seq, seat, intent, changed)]


def _show(state: TableState, seat: PlayerId, intent: Show) -> list[Event]:
    card = state.cards_by_id.get(intent.card_id)
    if card is None or not owns_card(state, seat, intent.card_id) or card.shown:
        return []
    card.show()
    state.seq += 1
    return [Event(state.seq, seat, intent, (card.id,))]


def _unshow(state: TableState, seat: PlayerId, intent: Unshow) -> list[Event]:
    card = state.cards_by_id.get(intent.card_id)
    if card is None or not owns_card(state, seat, intent.card_id) or not card.shown:
        return []
    card.unshow()
    state.seq += 1
    return [Event(state.seq, seat, intent, (card.id,))]


def _peek(state: TableState, seat: PlayerId, intent: Peek) -> list[Event]:
    # Owner-gated: you may privately peek only your own (or an owner-less public) hidden card. Seeing a
    # card the opponent holds requires them to Show it; you cannot reach across and look yourself.
    card = state.cards_by_id.get(intent.card_id)
    if card is None or not owns_card(state, seat, intent.card_id) or seat in card.peekers:
        return []
    card.add_peeker(seat)
    state.seq += 1
    return [Event(state.seq, seat, intent, (card.id,))]


def _unpeek(state: TableState, seat: PlayerId, intent: Unpeek) -> list[Event]:
    card = state.cards_by_id.get(intent.card_id)
    if card is None or seat not in card.peekers:
        return []
    card.remove_peeker(seat)
    state.seq += 1
    return [Event(state.seq, seat, intent, (card.id,))]


def _draw(state: TableState, seat: PlayerId, intent: Draw) -> list[Event]:
    if not owns_deck(state, seat, intent.deck):
        return []
    if intent.deck.side is Side.FATE:
        card = ops.draw_to_hand(state, seat)
        if card is None:
            return []
        dest: MoveDest = ZoneKey(seat, ZoneRole.HAND)
        position = None
    else:
        card = state.decks[intent.deck].draw_one()
        if card is None:
            return []
        dest = BATTLEFIELD
        position = None
        for key, zone in state.zones.items():
            if key.owner == seat and key.role is ZoneRole.PROVINCE and zone.has_capacity():
                card.turn_face_down()
                zone.add(card)
                dest = key
                break
        if dest == BATTLEFIELD:
            card.turn_face_down()
            state.battlefield.add(card)
            position = UNPLACED_BOARD_POS
            state.positions[card.id] = position
    state.seq += 1
    return [Event(state.seq, seat, MoveCard(card.id, dest, position), (card.id,))]


def _shuffle(state: TableState, seat: PlayerId, intent: Shuffle) -> list[Event]:
    if not owns_deck(state, seat, intent.deck):
        return []
    state.decks[intent.deck].shuffle(seed=intent.seed)
    state.seq += 1
    return [Event(state.seq, seat, intent)]


def _flip_deck_top(state: TableState, seat: PlayerId, intent: FlipDeckTop) -> list[Event]:
    if not owns_deck(state, seat, intent.deck):
        return []
    cards = state.decks[intent.deck].cards
    if not cards:
        return []
    top = cards[-1]
    top.flip()
    state.seq += 1
    return [Event(state.seq, seat, intent, (top.id,))]


def _search_deck(state: TableState, seat: PlayerId, intent: SearchDeck) -> list[Event]:
    # Read-only: the accepted event signals the web layer to ship the ordered deck to its owner
    # alone; state and seq are untouched. A non-owner is rejected here and receives nothing.
    if not owns_deck(state, seat, intent.deck):
        return []
    return [Event(state.seq, seat, intent)]


def _fill_province(state: TableState, seat: PlayerId, intent: FillProvince) -> list[Event]:
    zone = state.zones.get(intent.zone)
    if (
        zone is None
        or not isinstance(zone, ProvinceZone)
        or not owns_zone(state, seat, intent.zone)
    ):
        return []
    if not zone.has_capacity():
        return []
    card = ops.fill_province(state, seat, zone)
    if card is None:
        return []
    state.seq += 1
    return [Event(state.seq, seat, MoveCard(card.id, intent.zone), (card.id,))]


def _destroy_province(state: TableState, seat: PlayerId, intent: DestroyProvince) -> list[Event]:
    zone = state.zones.get(intent.zone)
    if (
        zone is None
        or not isinstance(zone, ProvinceZone)
        or not owns_zone(state, seat, intent.zone)
    ):
        return []
    moved = ops.destroy_province(state, seat, intent.zone)
    state.seq += 1
    return [Event(state.seq, seat, intent, tuple(moved))]


def _discard_province(state: TableState, seat: PlayerId, intent: DiscardProvince) -> list[Event]:
    zone = state.zones.get(intent.zone)
    if (
        zone is None
        or not isinstance(zone, ProvinceZone)
        or not owns_zone(state, seat, intent.zone)
    ):
        return []
    card = ops.discard_province(state, seat, zone)
    if card is None:
        return []
    state.seq += 1
    return [Event(state.seq, seat, intent, (card.id,))]


def _create_province(state: TableState, seat: PlayerId, intent: CreateProvince) -> list[Event]:
    ops.create_province(state, seat)
    state.seq += 1
    return [Event(state.seq, seat, intent)]


def _set_honor(state: TableState, seat: PlayerId, intent: SetHonor) -> list[Event]:
    if not ops.set_honor(state, seat, delta=intent.delta, value=intent.value):
        return []
    state.seq += 1
    return [Event(state.seq, seat, intent)]


def _spawn_card(state: TableState, seat: PlayerId, intent: SpawnCard) -> list[Event]:
    if intent.card_id in state.cards_by_id:
        return []
    card = ops.spawn_token(
        state, intent.card_id, intent.name, intent.side, intent.image, intent.position
    )
    state.seq += 1
    return [Event(state.seq, seat, intent, (card.id,))]


def _remove_card(state: TableState, seat: PlayerId, intent: RemoveCard) -> list[Event]:
    if not owns_card(state, seat, intent.card_id):
        return []
    card = state.cards_by_id[intent.card_id]
    # Only spawned tokens may leave the table outright; a real card from a deck or zone is never
    # destroyable — it must be moved to a discard or banish instead.
    if not card.is_token:
        return []
    ops.remove_card(state, card)
    state.seq += 1
    return [Event(state.seq, seat, intent, (intent.card_id,))]


def _on_battlefield(state: TableState, card: L5RCard) -> bool:
    return any(held is card for held in state.battlefield.cards)


def _attach(state: TableState, seat: PlayerId, intent: Attach) -> list[Event]:
    child = state.cards_by_id.get(intent.card_id)
    if (
        child is None
        or not owns_card(state, seat, intent.card_id)
        or not _on_battlefield(state, child)
    ):
        return []
    target = intent.to
    if isinstance(target, ZoneKey):
        if not isinstance(state.zones.get(target), ProvinceZone):
            return []
    else:
        parent = state.cards_by_id.get(target)
        if parent is None or not _on_battlefield(state, parent):
            return []
        # Refuse a self-attach or cycle: walking parents from the target must not reach the child.
        cursor: AttachTarget | None = target
        while isinstance(cursor, str):
            if cursor == intent.card_id:
                return []
            cursor = state.attachments.get(cursor)
    if not ops.attach(state, child, target):
        return []
    state.seq += 1
    return [Event(state.seq, seat, intent, (child.id,))]


def _detach(state: TableState, seat: PlayerId, intent: Detach) -> list[Event]:
    card = state.cards_by_id.get(intent.card_id)
    if card is None or not owns_card(state, seat, intent.card_id):
        return []
    if not ops.detach(state, card):
        return []
    state.seq += 1
    return [Event(state.seq, seat, intent, (card.id,))]


def _flip_coin(state: TableState, seat: PlayerId, intent: FlipCoin) -> list[Event]:
    # Read-only: the coin touches no piece, so state and seq are untouched. The accepted event carries
    # the seed, from which the web layer derives the same heads/tails result for both seats.
    return [Event(state.seq, seat, intent)]


def _roll_dice(state: TableState, seat: PlayerId, intent: RollDice) -> list[Event]:
    # Read-only, mirroring _flip_coin: the die changes nothing; the event's seed and sides reproduce
    # the face.
    return [Event(state.seq, seat, intent)]


_HANDLERS = {
    IntentOp.MOVE_CARD: _move_card,
    IntentOp.MOVE_DECK_TOP: _move_deck_top,
    IntentOp.SET_CARD_POS: _set_card_pos,
    IntentOp.SET_CARD_POSITIONS: _set_card_positions,
    IntentOp.REORDER_HAND: _reorder_hand,
    IntentOp.REORDER_PILE: _reorder_pile,
    IntentOp.RAISE: _raise,
    IntentOp.SET_NOTE: _set_note,
    IntentOp.ADJUST_COUNTER: _adjust_counter,
    IntentOp.GIVE_CONTROL: _give_control,
    IntentOp.BOW: _apply_flag,
    IntentOp.UNBOW: _apply_flag,
    IntentOp.FLIP: _apply_flag,
    IntentOp.FLIP_FACE: _apply_flag,
    IntentOp.INVERT: _apply_flag,
    IntentOp.SHOW: _show,
    IntentOp.UNSHOW: _unshow,
    IntentOp.PEEK: _peek,
    IntentOp.UNPEEK: _unpeek,
    IntentOp.DRAW: _draw,
    IntentOp.SHUFFLE: _shuffle,
    IntentOp.FLIP_DECK_TOP: _flip_deck_top,
    IntentOp.SEARCH_DECK: _search_deck,
    IntentOp.FILL_PROVINCE: _fill_province,
    IntentOp.DESTROY_PROVINCE: _destroy_province,
    IntentOp.DISCARD_PROVINCE: _discard_province,
    IntentOp.CREATE_PROVINCE: _create_province,
    IntentOp.SET_HONOR: _set_honor,
    IntentOp.SPAWN_CARD: _spawn_card,
    IntentOp.REMOVE_CARD: _remove_card,
    IntentOp.ATTACH: _attach,
    IntentOp.DETACH: _detach,
    IntentOp.FLIP_COIN: _flip_coin,
    IntentOp.ROLL_DICE: _roll_dice,
}


def apply_intent(state: TableState, seat: PlayerId, intent: Intent) -> list[Event]:
    """Validate and apply one intent, mutating ``state`` in place and returning the events produced.

    Pure apart from the in-place mutation: no I/O, deterministic given the state, seat, and intent
    (shuffles derive their order from the intent's explicit seed). Ownership, side, and capacity
    violations are rejected and leave the state untouched, returning an empty list; ``seq`` advances
    only when the table actually changes.

    Parameters
    ----------
    state : TableState
        The authoritative table; mutated in place on an accepted intent.
    seat : PlayerId
        The seat attempting the action.
    intent : Intent
        The operation to apply.
    """
    return _HANDLERS[intent.op](state, seat, intent)
