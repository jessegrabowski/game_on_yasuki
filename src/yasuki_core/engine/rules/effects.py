from abc import ABC, abstractmethod
from dataclasses import dataclass, replace

from yasuki_core.engine import ops
from yasuki_core.engine.players import Cause, PlayerId
from yasuki_core.engine.rules.attachments import unit_of
from yasuki_core.engine.rules.decisions import ChooseAmount, ChooseCards, Confirm, DecisionRequest
from yasuki_core.game_pieces.cards import L5RCard
from yasuki_core.engine.rules.events import (
    CardDiscarded,
    CounterGained,
    Destroyed,
    EnteredPlay,
    GameEvent,
    Revealed,
    Straightened,
)
from yasuki_core.engine.rules.modifiers import Duration, Modifier, Stat
from yasuki_core.engine.rules.state import GameState
from yasuki_core.engine.rules.work import ApplyEffects
from yasuki_core.engine.table import BATTLEFIELD, UNPLACED_BOARD_POS, DeckKey, ZoneKey, ZoneRole
from yasuki_core.game_pieces.constants import Side
from yasuki_core.game_pieces.counters import Counter


def _pile(card: L5RCard, *, banished: bool = False) -> ZoneKey:
    """The pile ``card`` belongs in when it leaves play: its owner's, on the card's own side, and its
    banish rather than its discard when ``banished``.

    Anything not on the Dynasty side is filed with the Fate cards, which is where a Stronghold or a
    Sensei goes for want of a pile of its own. Shared so a Dynasty card cannot reach a Fate pile
    through one path and not another.
    """
    if card.side is Side.DYNASTY:
        role = ZoneRole.DYNASTY_BANISH if banished else ZoneRole.DYNASTY_DISCARD
    else:
        role = ZoneRole.FATE_BANISH if banished else ZoneRole.FATE_DISCARD
    return ZoneKey(card.owner, role)


class Effect(ABC):
    """One change to game state, described as data.

    Triggers and activated abilities return lists of effects rather than mutating the board, and the
    cascade commits each through :meth:`perform`.
    """

    __slots__ = ()

    @abstractmethod
    def perform(self, game: GameState) -> list[GameEvent]:
        """Commit this effect and return the events it raises, for the cascade to drain."""

    def is_payable(self, game: GameState) -> bool:
        """Whether an ability can pay this effect as a cost. Most effects carry no precondition
        and always can."""
        return True

    @abstractmethod
    def describe(self) -> str:
        """One short line naming what this effect does, for a cascade trace. Abstract so a new
        effect cannot ship unreadable: the generated ``repr`` inlines whole nested dataclasses."""


class InterruptingEffect(Effect, ABC):
    """An effect that pauses the cascade to put a question to a seat.

    The walker records :meth:`request` as the pending decision and stashes the rest of the cascade,
    resuming once the seat answers. It never calls :meth:`perform` on one.
    """

    __slots__ = ()

    @abstractmethod
    def request(self, game: GameState) -> DecisionRequest:
        """The decision to put to the seat."""

    def perform(self, game: GameState) -> list[GameEvent]:
        """Never reached: the walker records :meth:`request` and pauses instead of committing."""
        raise RuntimeError(
            f"{type(self).__name__} pauses the cascade; it is never applied directly"
        )


@dataclass(frozen=True, slots=True)
class AdjustCounter(Effect):
    """Add ``delta`` to a counter on a card (floored at zero by the card). A grant is a positive
    delta, a removal negative. The rules-side twin of the sandbox ``AdjustCounter`` intent, applied
    through :meth:`Effect.perform` rather than ``apply_intent``."""

    card_id: str
    counter: Counter
    delta: int

    def describe(self) -> str:
        return f"{self.delta:+d} {self.counter.name} on {self.card_id}"

    def is_payable(self, game: GameState) -> bool:
        """A removal needs the card to hold enough of the counter; a grant always applies."""
        if self.delta >= 0:
            return True
        card = game.table.cards_by_id.get(self.card_id)
        return card is not None and card.counters.get(self.counter.key, 0) >= -self.delta

    def perform(self, game: GameState) -> list[GameEvent]:
        card = game.table.cards_by_id.get(self.card_id)
        if card is None:
            return []
        before = card.counters.get(self.counter.key, 0)
        card.adjust_counter(self.counter.key, self.delta)
        gained = card.counters.get(self.counter.key, 0) - before
        if gained > 0:
            return [CounterGained(self.card_id, self.counter, gained)]
        return []


@dataclass(frozen=True, slots=True)
class DrawCard(Effect):
    """``seat`` draws a card from its fate deck."""

    seat: PlayerId

    def describe(self) -> str:
        return f"{self.seat.name} draws a card"

    def perform(self, game: GameState) -> list[GameEvent]:
        ops.draw_to_hand(game.table, self.seat)
        return []


@dataclass(frozen=True, slots=True)
class Show(Effect):
    """Reveal ``card_id`` to the other seats. Narrower than turning it face up: its owner is telling
    the table what it is, and they go on knowing once it is hidden again."""

    card_id: str

    def describe(self) -> str:
        return f"show {self.card_id}"

    def perform(self, game: GameState) -> list[GameEvent]:
        card = game.table.cards_by_id.get(self.card_id)
        if card is not None:
            card.show()
        return []


@dataclass(frozen=True, slots=True)
class MoveToHand(Effect):
    """Put ``card_id`` into ``seat``'s hand from wherever it is. A card that no longer exists is a
    no-op."""

    card_id: str
    seat: PlayerId

    def describe(self) -> str:
        return f"{self.card_id} to {self.seat.name}'s hand"

    def perform(self, game: GameState) -> list[GameEvent]:
        card = game.table.cards_by_id.get(self.card_id)
        if card is not None:
            ops.move_card(game.table, card, ZoneKey(self.seat, ZoneRole.HAND))
        return []


def _remove_unit(game: GameState, card: L5RCard, *, banished: bool = False) -> tuple[L5RCard, ...]:
    """Send ``card`` and everything attached to him out of play — to their discards, or to their
    banishes when ``banished`` — returning the unit that left so the caller can announce each
    departure in its own words (CR, Unit).

    A created card among them has no pile of either kind and is taken off the table instead, which
    the move itself sees to (CR, Create). It still announces its departure, because a card reacting
    to a Follower being destroyed does not care where the Follower came from.
    """
    unit = unit_of(game, card)
    for member in unit:
        ops.move_card(game.table, member, _pile(member, banished=banished))
    return unit


@dataclass(frozen=True, slots=True)
class Destroy(Effect):
    """Destroy a card, sending it to its owner's discard by side. A Personality takes his unit with
    him: everything attached leaves play the same way he does (CR, Unit), each announcing its own
    destruction and naming the same cause.

    Attributes
    ----------
    card_id : str
        The card to destroy.
    cause : PlayerId or Rulebook
        Who or what destroyed it — the seat whose card did, or the rule that demanded it.
    """

    card_id: str
    cause: Cause

    def describe(self) -> str:
        return f"destroy {self.card_id}"

    def perform(self, game: GameState) -> list[GameEvent]:
        card = game.table.cards_by_id.get(self.card_id)
        if card is None:
            return []
        return [Destroyed(member.id, self.cause) for member in _remove_unit(game, card)]


@dataclass(frozen=True, slots=True)
class Discard(Effect):
    """Put a card in its owner's discard pile by side, announcing the discard.

    Attributes
    ----------
    card_id : str
        The card to discard.
    cause : PlayerId or Rulebook
        Who or what discarded it — the seat whose action did, which a discard reaction reads to tell
        its own doing from its opponent's, or the rule that demanded it.
    """

    card_id: str
    cause: Cause

    def describe(self) -> str:
        return f"{self.cause.name} discards {self.card_id}"

    def perform(self, game: GameState) -> list[GameEvent]:
        card = game.table.cards_by_id.get(self.card_id)
        if card is None:
            return []
        unit = _remove_unit(game, card)
        return [CardDiscarded(member.id, member.side, self.cause) for member in unit]


@dataclass(frozen=True, slots=True)
class Banish(Effect):
    """Take a card out of the game, to its owner's banish pile by side.

    Banishing is not a destruction and not a discard: nothing reacts to it and the card is out of
    reach of anything that recurs from a discard pile. A Personality takes his unit with him, as he
    does however he leaves (CR, Unit), and a created card leaves the table entirely — banishing one
    and destroying one come to the same thing, since neither pile can hold it.

    Attributes
    ----------
    card_id : str
        The card to banish. A card already gone is a no-op, which is what a delayed banish finds
        when something else got there first.
    """

    card_id: str

    def describe(self) -> str:
        return f"banish {self.card_id}"

    def perform(self, game: GameState) -> list[GameEvent]:
        card = game.table.cards_by_id.get(self.card_id)
        if card is None:
            return []
        _remove_unit(game, card, banished=True)
        return []


@dataclass(frozen=True, slots=True)
class DestroyProvince(Effect):
    """Destroy ``seat``'s Province ``zone``: its contents go to the discard face-up and the Province
    itself leaves the board. A Province already gone is a no-op.

    Attributes
    ----------
    seat : PlayerId
        The seat destroying it, whose discard takes any card with no pile of its own.
    zone : ZoneKey
        The Province to destroy.
    """

    seat: PlayerId
    zone: ZoneKey

    def describe(self) -> str:
        return f"destroy {self.seat.name}'s province {self.zone.idx}"

    def perform(self, game: GameState) -> list[GameEvent]:
        if self.zone not in game.table.zones:
            return []
        moved = ops.destroy_province(game.table, self.seat, self.zone)
        cards = game.table.cards_by_id
        return [CardDiscarded(card_id, cards[card_id].side, self.seat) for card_id in moved]


@dataclass(frozen=True, slots=True)
class PlaceInProvince(Effect):
    """Put a card into a Province face-up. A no-op when the card is gone or the Province is full."""

    card_id: str
    zone: ZoneKey

    def describe(self) -> str:
        return f"place {self.card_id} in {self.zone.owner.name} province {self.zone.idx}"

    def perform(self, game: GameState) -> list[GameEvent]:
        card = game.table.cards_by_id.get(self.card_id)
        province = game.table.zones.get(self.zone)
        if card is None or province is None or not province.has_capacity():
            return []
        ops.move_card(game.table, card, self.zone)
        card.turn_face_up()
        return []


@dataclass(frozen=True, slots=True)
class ShuffleDeck(Effect):
    """Shuffle a deck, drawing from the game's own stream so a replay shuffles the same way."""

    deck: DeckKey

    def describe(self) -> str:
        return f"shuffle {self.deck.owner.name}'s {self.deck.side.name.lower()} deck"

    def perform(self, game: GameState) -> list[GameEvent]:
        game.table.decks[self.deck].shuffle(game.rng)
        return []


@dataclass(frozen=True, slots=True)
class GrantModifier(Effect):
    """Record a continuous stat modifier: the ``source`` card grants ``target`` a change of
    ``amount`` to ``stat`` for ``duration``. The single created-effect entry point; a card's
    counters and attachments grant their bonuses without one (they are derived on read)."""

    source_id: str
    target_id: str
    stat: Stat
    amount: int
    duration: Duration

    def describe(self) -> str:
        return (
            f"{self.source_id} grants {self.target_id} {self.amount:+d} "
            f"{self.stat.name} ({self.duration.name})"
        )

    def perform(self, game: GameState) -> list[GameEvent]:
        game.modifiers.append(
            Modifier(self.source_id, self.target_id, self.stat, self.amount, self.duration)
        )
        return []


@dataclass(frozen=True, slots=True)
class AttachCard(Effect):
    """Attach a card to a Personality, from wherever it is.

    The other half of the Equip distinction: a card that says "attach" reaches the same board as the
    Equip action without its cost, its timing or its legality (CR, Equip). A card already in play
    moves units; one elsewhere arrives on the battlefield first.

    Attributes
    ----------
    card_id : str
        The card to attach.
    target_id : str
        The Personality it attaches to.
    """

    card_id: str
    target_id: str

    def describe(self) -> str:
        return f"attach {self.card_id} to {self.target_id}"

    def perform(self, game: GameState) -> list[GameEvent]:
        card = game.table.cards_by_id.get(self.card_id)
        personality = game.table.cards_by_id.get(self.target_id)
        if card is None or personality is None:
            return []
        entering = not any(held is card for held in game.table.battlefield.cards)
        hand = game.table.zones[ZoneKey(card.owner, ZoneRole.HAND)]
        from_hand = any(held is card for held in hand.cards)
        if entering:
            ops.move_card(game.table, card, BATTLEFIELD, position=UNPLACED_BOARD_POS)
        ops.attach_to_personality(game.table, card, personality)
        return [EnteredPlay(self.card_id, from_hand=from_hand)] if entering else []


@dataclass(frozen=True, slots=True)
class CreateToken(Effect):
    """Create a card that was never in a deck — the "create a 1F Ashigaru Follower", the "create a
    Personality with Force equal to the target's Chi" — and put it into play.

    What it is comes from the token template the deck load resolved, so the created card carries the
    stats, keywords and art the printed text describes rather than a stat line spelled out at the
    creation site. A created card is not a copy of anything: it enters play fresh, and leaving play
    removes it from the game rather than filling a discard pile.

    Attributes
    ----------
    token_id : str
        The template to stamp it from, by token card id.
    owner : PlayerId
        The seat that will control it.
    creator_id : str
        The card creating it, which the created card is remembered by. A card that speaks about what
        it made later — "if this Holding is ever unbowed, banish the Personality" — reads the
        relation rather than hunting the board for something that looks right.
    attach_to : str or None
        The Personality it arrives attached to, or None to arrive on its own. A card that names a
        target Personality creates nothing when that Personality has left play in the meantime.
    stats : tuple of (Stat, int)
        Stats the creating card fixes, which the template prints as variable — Mishime Sensei's Oni
        has "Force equal to the target's Chi", and the token print carries a ``*`` there. Each pair
        replaces that stat on the print the created card presents, so the card genuinely has the
        number rather than carrying a modifier over a printed zero. Default none, for a template
        whose whole stat line is printed.
    clan : str or None
        The clan the created card carries, for the "with your Clan Alignment" a card grants its
        creation. None leaves the template's own printed clan alone, which is what an unaligned
        controller has to give. Default None.
    banish_at_turn_end : bool
        Whether the created card is banished before the turn ends. A creation the card lends the
        player for a turn ("banish it unless you destroyed the target") is recorded as it is made,
        because by the time the turn ends there is nothing left to decide. Default False.
    """

    token_id: str
    owner: PlayerId
    creator_id: str
    attach_to: str | None = None
    stats: tuple[tuple[Stat, int], ...] = ()
    clan: str | None = None
    banish_at_turn_end: bool = False

    def describe(self) -> str:
        fixed = [self.clan] if self.clan else []
        fixed += [f"{stat.name} {value}" for stat, value in self.stats]
        where = "" if self.attach_to is None else f" on {self.attach_to}"
        given = f" with {', '.join(fixed)}" if fixed else ""
        return f"{self.owner.name} creates {self.token_id}{where}{given}"

    def perform(self, game: GameState) -> list[GameEvent]:
        personality = None
        if self.attach_to is not None:
            personality = game.table.cards_by_id.get(self.attach_to)
            if personality is None:
                return []
        # A KeyError here is a deck that reached the table without its token templates, not a card
        # doing something unusual — the load resolves every token the deck's cards can create.
        printed = game.table.creatable_tokens[self.token_id]
        if self.stats:
            printed = replace(printed, **{stat.value: value for stat, value in self.stats})
        if self.clan is not None:
            # Both fields: a reader of a card's clans takes the list when it has one, so leaving it
            # behind would keep the template aligned to whatever it was printed as.
            printed = replace(printed, clan=self.clan, clans=(self.clan,))
        card = ops.spawn_token(
            game.table, game.mint_token_id(), printed, UNPLACED_BOARD_POS, self.owner
        )
        game.created_by[card.id] = self.creator_id
        if self.banish_at_turn_end:
            game.banish_at_turn_end.append(card.id)
        if personality is not None:
            ops.attach_to_personality(game.table, card, personality)
        return [EnteredPlay(card.id, from_hand=False)]


@dataclass(frozen=True, slots=True)
class PayGold(InterruptingEffect):
    """Pay gold, bowing producers to raise what the seat's pool does not already cover.

    The cost a card charges in Gold, as opposed to the Gold a Recruit charges for the card itself:
    both raise the same payment, and this one carries no card being paid for. It pauses the cascade
    for the seat to pick which producers to bow, so it resolves before whatever an ability's text
    sequences behind it.

    Attributes
    ----------
    seat : PlayerId
        The seat being charged.
    amount : int
        The gold to raise.
    label : str
        What the payment is for, shown in the prompt.
    """

    seat: PlayerId
    amount: int
    label: str

    def describe(self) -> str:
        return f"{self.seat.name} pays {self.amount} gold for {self.label}"

    # Imported where they are used: pricing a payment reads the production-boost registry, whose
    # module imports this one.
    def is_payable(self, game: GameState) -> bool:
        from yasuki_core.engine.rules.payments import can_raise

        return can_raise(game, self.seat, self.amount)

    def request(self, game: GameState) -> DecisionRequest:
        from yasuki_core.engine.rules.payments import payment_request

        return payment_request(game, self.seat, self.amount, self.label)


@dataclass(frozen=True, slots=True)
class AskAmount(InterruptingEffect):
    """Pause for the seat to say how much Gold it spends on a variable cost, then hand the amount to
    a resolver.

    The ``:X:`` in a cost block: the amount is settled during the Pay Costs step and everything the
    action does is shaped by it, so the resolver both charges it and reads it (CR, Action Sequence;
    Good Faith).

    Attributes
    ----------
    seat : PlayerId
        The seat choosing and paying.
    amounts : tuple of int
        The amounts on offer, which the caller has already narrowed to what the seat can raise and
        what would leave the action something legal to do.
    question : str
        What the amount is for, as the seat reads it.
    resolver : str
        The registered choice resolver the chosen amount is handed to.
    source_id : str
        The card charging the cost.
    """

    seat: PlayerId
    amounts: tuple[int, ...]
    question: str
    resolver: str
    source_id: str

    def describe(self) -> str:
        return f"{self.seat.name} is asked: {self.question}"

    def is_payable(self, game: GameState) -> bool:
        """Nothing to choose from is nothing to pay."""
        return bool(self.amounts)

    def request(self, game: GameState) -> DecisionRequest:
        return ChooseAmount(
            seat=self.seat,
            candidates=tuple(str(amount) for amount in self.amounts),
            question=self.question,
            resolver=self.resolver,
            source_id=self.source_id,
        )


@dataclass(frozen=True, slots=True)
class Bow(Effect):
    """Bow a card."""

    card_id: str

    def describe(self) -> str:
        return f"bow {self.card_id}"

    def is_payable(self, game: GameState) -> bool:
        """An already-bowed card cannot bow again."""
        card = game.table.cards_by_id.get(self.card_id)
        return card is not None and not card.bowed

    def perform(self, game: GameState) -> list[GameEvent]:
        card = game.table.cards_by_id.get(self.card_id)
        if card is not None:
            card.bow()
        return []


@dataclass(frozen=True, slots=True)
class Straighten(Effect):
    """Straighten (unbow) a card. Announces the change, which a card that watches for its own
    straightening reads; one already standing announces nothing."""

    card_id: str

    def describe(self) -> str:
        return f"straighten {self.card_id}"

    def perform(self, game: GameState) -> list[GameEvent]:
        card = game.table.cards_by_id.get(self.card_id)
        if card is None or not card.bowed:
            return []
        card.unbow()
        return [Straightened(self.card_id)]


@dataclass(frozen=True, slots=True)
class BanishTopFate(Effect):
    """Banish the top card of ``seat``'s Fate deck; a no-op if the deck is empty."""

    seat: PlayerId

    def describe(self) -> str:
        return f"banish the top of {self.seat.name}'s fate deck"

    def is_payable(self, game: GameState) -> bool:
        """An empty Fate deck has nothing to banish."""
        return bool(game.table.decks[DeckKey(self.seat, Side.FATE)].cards)

    def perform(self, game: GameState) -> list[GameEvent]:
        deck = game.table.decks[DeckKey(self.seat, Side.FATE)]
        if deck.cards:
            ops.move_card(game.table, deck.cards[-1], ZoneKey(self.seat, ZoneRole.FATE_BANISH))
        return []


@dataclass(frozen=True, slots=True)
class MoveToDeck(Effect):
    """Move a card into a deck at a stated depth, counting from whichever end names it.

    Give exactly one of ``from_top`` and ``from_bottom``. Depths are zero-based: ``from_top=0`` is
    the top card, ``from_bottom=0`` the bottom. A depth past the far end clamps to that end, so a
    deck of two asked for ``from_top=9`` takes the card at the bottom rather than raising. A card
    that no longer exists is a no-op.

    Attributes
    ----------
    card_id : str
        The card to move.
    deck : DeckKey
        The deck it lands in.
    from_top : int, optional
        Depth measured from the top of the deck. Default None.
    from_bottom : int, optional
        Depth measured from the bottom of the deck. Default None.
    """

    card_id: str
    deck: DeckKey
    from_top: int | None = None
    from_bottom: int | None = None

    def __post_init__(self) -> None:
        """Raise ValueError unless exactly one non-negative depth names an end."""
        if (self.from_top is None) == (self.from_bottom is None):
            raise ValueError("MoveToDeck takes exactly one of from_top or from_bottom")
        depth = self.from_top if self.from_top is not None else self.from_bottom
        if depth < 0:
            raise ValueError(f"MoveToDeck depth cannot be negative, got {depth}")

    def describe(self) -> str:
        end, depth = (
            ("top", self.from_top) if self.from_top is not None else ("bottom", self.from_bottom)
        )
        side = self.deck.side.name.lower()
        return f"move {self.card_id} into {self.deck.owner.name}'s {side} deck, {depth} from {end}"

    def perform(self, game: GameState) -> list[GameEvent]:
        card = game.table.cards_by_id.get(self.card_id)
        if card is None:
            return []
        # The card leaves wherever it is before it lands, so a card already in this deck must not
        # count itself when its depth is measured.
        cards = game.table.decks[self.deck].cards
        landing_size = len(cards) - (1 if any(held is card for held in cards) else 0)
        index = self.from_bottom if self.from_bottom is not None else landing_size - self.from_top
        ops.move_card(game.table, card, self.deck, deck_index=index)
        return []


@dataclass(frozen=True, slots=True)
class GainGold(Effect):
    """Add ``amount`` gold to ``seat``'s pool: gold produced outside a payment (a card that produces
    gold on entry), transient and cleared at the end of the phase."""

    seat: PlayerId
    amount: int

    def describe(self) -> str:
        return f"{self.seat.name} gains {self.amount} gold"

    def perform(self, game: GameState) -> list[GameEvent]:
        game.add_gold(self.seat, self.amount)
        return []


@dataclass(frozen=True, slots=True)
class GainHonor(Effect):
    """Move ``seat``'s Family Honor by ``amount``. Negative loses honor; the two directions are one
    effect because the rules treat them as one dial."""

    seat: PlayerId
    amount: int

    def describe(self) -> str:
        verb = "gains" if self.amount >= 0 else "loses"
        return f"{self.seat.name} {verb} {abs(self.amount)} honor"

    def perform(self, game: GameState) -> list[GameEvent]:
        ops.set_honor(game.table, self.seat, delta=self.amount)
        return []


@dataclass(frozen=True, slots=True)
class IgnoreHonorRequirements(Effect):
    """Grant ``seat`` the standing waiver of every Personality's Honor Requirement when
    recruiting."""

    seat: PlayerId

    def describe(self) -> str:
        return f"{self.seat.name} ignores honor requirements"

    def perform(self, game: GameState) -> list[GameEvent]:
        ops.set_ignore_honor_requirements(game.table, self.seat, True)
        return []


@dataclass(frozen=True, slots=True)
class RecruitCard(InterruptingEffect):
    """Bring a card into play from its controller's province, out of the normal recruit sequence.

    Pauses for the payment its controller must cover, exactly as a Recruit action does. With
    ``renew`` the vacated province refills face-up on top of whatever the card's own Renew keyword
    grants.
    """

    card_id: str
    renew: bool = False

    def describe(self) -> str:
        renewed = ", renewing the province" if self.renew else ""
        return f"recruit {self.card_id} out of sequence{renewed}"

    def request(self, game: GameState) -> DecisionRequest:
        # flow imports triggers, which imports this module, so the announce entry point is reached
        # lazily rather than moving the module boundary.
        from yasuki_core.engine.rules.flow import announce_recruit

        card = game.table.cards_by_id[self.card_id]
        return announce_recruit(game, card, card.owner, invest_amount=None, renew=self.renew)


@dataclass(frozen=True, slots=True)
class RefillProvince(Effect):
    """Refill a Province that a card has left, if it is still short.

    The conditional is the rule, not a guard: a Province is refilled "unless something else has
    refilled it", so a reaction that filled the gap first leaves this a no-op. Deferred behind the
    reactions to the card leaving, which is where the rules place it.

    Attributes
    ----------
    zone : ZoneKey
        The Province to refill.
    face_up : bool, optional
        Whether the card arrives face-up, as a Renew refill does. Default False.
    """

    zone: ZoneKey
    face_up: bool = False

    def describe(self) -> str:
        face = " face-up" if self.face_up else ""
        return f"refill {self.zone.owner.name} province {self.zone.idx}{face}"

    def perform(self, game: GameState) -> list[GameEvent]:
        province = game.table.zones.get(self.zone)
        if province is None or not province.has_capacity():
            return []
        ops.fill_province(game.table, self.zone.owner, province, face_up=self.face_up)
        return []


@dataclass(frozen=True, slots=True)
class RevealProvinces(Effect):
    """Turn every face-down card in ``seat``'s Provinces face-up, announcing each one it turns. A
    card already face-up raises nothing, since nothing turned."""

    seat: PlayerId

    def describe(self) -> str:
        return f"reveal {self.seat.name}'s provinces"

    def perform(self, game: GameState) -> list[GameEvent]:
        return [Revealed(card_id) for card_id in ops.reveal_provinces(game.table, self.seat)]


@dataclass(frozen=True, slots=True)
class Unpayable(Effect):
    """A cost that can never be paid, so the ability holding it is never offered. Resolving one
    raises — reaching it means the legality check that should have withheld the ability did not run.

    Attributes
    ----------
    reason : str
        Why the cost cannot be met, for the cascade trace.
    """

    reason: str

    def describe(self) -> str:
        return f"unpayable: {self.reason}"

    def is_payable(self, game: GameState) -> bool:
        return False

    def perform(self, game: GameState) -> list[GameEvent]:
        raise RuntimeError(f"resolved an unpayable cost: {self.reason}")


@dataclass(frozen=True, slots=True)
class Then(Effect):
    """Defer ``effects`` until the current step has fully resolved, cascade included.

    Effects placed inline run before the events already queued behind them, so a step that must
    follow another card's reaction to what just happened belongs here instead.
    """

    effects: tuple[Effect, ...]

    def describe(self) -> str:
        return f"then: {len(self.effects)} deferred"

    def perform(self, game: GameState) -> list[GameEvent]:
        game.stack.append(ApplyEffects(self.effects))
        return []


@dataclass(frozen=True, slots=True)
class Ask(InterruptingEffect):
    """Put a yes/no question to a seat, and hand ``subjects`` to the resolver if it answers yes.

    The question names what is being asked so the seat reads it rather than inferring it from a
    board selection. Use this for an optional effect whose subject is already settled; a genuine
    pick among several cards is a :class:`Choose`.

    Attributes
    ----------
    seat : PlayerId
        The seat answering.
    question : str
        The question as the seat reads it, naming the cards it concerns.
    resolver : str
        The registered choice resolver naming what a yes does.
    subjects : tuple of str
        The card ids passed to the resolver on yes; it receives none on no.
    source_id : str, optional
        A card id handed to the resolver as its context. Default None.
    """

    seat: PlayerId
    question: str
    resolver: str
    subjects: tuple[str, ...] = ()
    source_id: str | None = None

    def describe(self) -> str:
        return f"{self.seat.name} is asked: {self.question}"

    def request(self, game: GameState) -> DecisionRequest:
        return Confirm(
            seat=self.seat,
            candidates=self.subjects,
            question=self.question,
            resolver=self.resolver,
            source_id=self.source_id,
        )


@dataclass(frozen=True, slots=True)
class Choose(InterruptingEffect):
    """Pause the cascade so ``seat`` picks between ``minimum`` and ``maximum`` of ``candidates``;
    the chosen ids feed the registered ``resolver``, whose effects apply on resume.

    Attributes
    ----------
    seat : PlayerId
        The seat that chooses.
    candidates : tuple of str
        The card ids the seat may pick among.
    minimum : int
        The fewest cards the seat may pick; zero when the choice is optional.
    maximum : int
        The most cards the seat may pick.
    resolver : str
        The registered choice resolver naming what the chosen ids do.
    source_id : str, optional
        A card id handed to the resolver as its context. Which card that is belongs to the resolver
        — often the one whose trigger raised the choice, sometimes the card being acted on. None
        when the rulebook raises the choice and there is no card to name. Default None.
    """

    seat: PlayerId
    candidates: tuple[str, ...]
    minimum: int
    maximum: int
    resolver: str
    source_id: str | None = None

    def describe(self) -> str:
        return (
            f"{self.seat.name} chooses {self.minimum}-{self.maximum} of "
            f"{len(self.candidates)} for {self.resolver}"
        )

    def request(self, game: GameState) -> DecisionRequest:
        return ChooseCards(
            seat=self.seat,
            candidates=self.candidates,
            minimum=self.minimum,
            maximum=self.maximum,
            resolver=self.resolver,
            source_id=self.source_id,
        )
