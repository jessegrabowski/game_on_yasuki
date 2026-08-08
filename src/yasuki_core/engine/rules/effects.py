from abc import ABC, abstractmethod
from dataclasses import dataclass

from yasuki_core.engine import ops
from yasuki_core.engine.players import PlayerId
from yasuki_core.engine.rules.decisions import ChooseCards, DecisionRequest
from yasuki_core.engine.rules.events import CounterGained, Destroyed, GameEvent
from yasuki_core.engine.rules.modifiers import Duration, Modifier, Stat
from yasuki_core.engine.rules.state import GameState
from yasuki_core.engine.rules.work import ApplyEffects
from yasuki_core.engine.table import DeckKey, ZoneKey, ZoneRole
from yasuki_core.game_pieces.constants import Side
from yasuki_core.game_pieces.counters import Counter


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
class Destroy(Effect):
    """Destroy a card, sending it to its owner's discard by side."""

    card_id: str

    def describe(self) -> str:
        return f"destroy {self.card_id}"

    def perform(self, game: GameState) -> list[GameEvent]:
        card = game.table.cards_by_id.get(self.card_id)
        if card is None or card.owner is None:
            return []
        role = ZoneRole.DYNASTY_DISCARD if card.side is Side.DYNASTY else ZoneRole.FATE_DISCARD
        ops.move_card(game.table, card, ZoneKey(card.owner, role))
        return [Destroyed(self.card_id)]


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
    """Straighten (unbow) a card."""

    card_id: str

    def describe(self) -> str:
        return f"straighten {self.card_id}"

    def perform(self, game: GameState) -> list[GameEvent]:
        card = game.table.cards_by_id.get(self.card_id)
        if card is not None:
            card.unbow()
        return []


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

    Depths are zero-based: ``from_top=0`` is the top card, ``from_bottom=0`` the bottom. A depth
    past the far end clamps to that end, so a deck of two asked for ``from_top=9`` takes the card at
    the bottom rather than raising. A card that no longer exists is a no-op.

    Attributes
    ----------
    card_id : str
        The card to move.
    deck : DeckKey
        The deck it lands in.
    from_top : int, optional
        Depth measured from the top of the deck. Give exactly one of this and ``from_bottom``.
        Default None.
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
        end = "top" if self.from_top is not None else "bottom"
        depth = self.from_top if self.from_top is not None else self.from_bottom
        side = self.deck.side.name.lower()
        return f"move {self.card_id} into {self.deck.owner.name}'s {side} deck, {depth} from {end}"

    def perform(self, game: GameState) -> list[GameEvent]:
        card = game.table.cards_by_id.get(self.card_id)
        if card is None:
            return []
        # The card leaves wherever it is before it lands, so a card already in this deck must not
        # count itself when its depth is measured.
        cards = game.table.decks[self.deck].cards
        landing_size = len(cards) - sum(1 for held in cards if held is card)
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
        assert card.owner is not None, f"{self.card_id} has no owner to recruit it"
        return announce_recruit(game, card, card.owner, invest_amount=0, renew=self.renew)


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
