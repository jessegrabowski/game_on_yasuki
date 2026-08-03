from abc import ABC, abstractmethod
from dataclasses import dataclass

from yasuki_core.engine import ops
from yasuki_core.engine.players import PlayerId
from yasuki_core.engine.rules.events import CounterGained, Destroyed, GameEvent
from yasuki_core.engine.rules.modifiers import Duration, Modifier, Stat
from yasuki_core.engine.rules.state import GameState
from yasuki_core.engine.table import DeckKey, ZoneKey, ZoneRole
from yasuki_core.game_pieces.constants import Side
from yasuki_core.game_pieces.counters import Counter


class Effect(ABC):
    """One change to game state, described as data.

    Triggers and activated abilities return lists of effects rather than mutating the board, and the
    cascade commits each through :meth:`perform`. An effect that cannot be added without implementing
    its own behavior cannot be added and then forgotten about at the commit site.
    """

    __slots__ = ()

    @abstractmethod
    def perform(self, game: GameState) -> list[GameEvent]:
        """Commit this effect and return the events it raises, for the cascade to drain."""

    def can_apply(self, game: GameState) -> bool:
        """Whether this effect would do anything against the current state. Only effects with a
        precondition an ability must satisfy before paying it override this."""
        return True


@dataclass(frozen=True, slots=True)
class AdjustCounter(Effect):
    """Add ``delta`` to a counter on a card (floored at zero by the card). A grant is a positive
    delta, a removal negative. The rules-side twin of the sandbox ``AdjustCounter`` intent, applied
    through :meth:`Effect.perform` rather than ``apply_intent``."""

    card_id: str
    counter: Counter
    delta: int

    def can_apply(self, game: GameState) -> bool:
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

    def perform(self, game: GameState) -> list[GameEvent]:
        ops.draw_to_hand(game.table, self.seat)
        return []


@dataclass(frozen=True, slots=True)
class Destroy(Effect):
    """Destroy a card, sending it to its owner's discard by side."""

    card_id: str

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

    def perform(self, game: GameState) -> list[GameEvent]:
        game.modifiers.append(
            Modifier(self.source_id, self.target_id, self.stat, self.amount, self.duration)
        )
        return []


@dataclass(frozen=True, slots=True)
class Bow(Effect):
    """Bow a card."""

    card_id: str

    def can_apply(self, game: GameState) -> bool:
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

    def perform(self, game: GameState) -> list[GameEvent]:
        card = game.table.cards_by_id.get(self.card_id)
        if card is not None:
            card.unbow()
        return []


@dataclass(frozen=True, slots=True)
class BanishTopFate(Effect):
    """Banish the top card of ``seat``'s Fate deck; a no-op if the deck is empty."""

    seat: PlayerId

    def can_apply(self, game: GameState) -> bool:
        """An empty Fate deck has nothing to banish."""
        return bool(game.table.decks[DeckKey(self.seat, Side.FATE)].cards)

    def perform(self, game: GameState) -> list[GameEvent]:
        deck = game.table.decks[DeckKey(self.seat, Side.FATE)]
        if deck.cards:
            ops.move_card(game.table, deck.cards[-1], ZoneKey(self.seat, ZoneRole.FATE_BANISH))
        return []


@dataclass(frozen=True, slots=True)
class GainGold(Effect):
    """Add ``amount`` gold to ``seat``'s pool: gold produced outside a payment (a card that produces
    gold on entry), transient and cleared at the end of the phase."""

    seat: PlayerId
    amount: int

    def perform(self, game: GameState) -> list[GameEvent]:
        game.add_gold(self.seat, self.amount)
        return []


@dataclass(frozen=True, slots=True)
class IgnoreHonorRequirements(Effect):
    """Grant ``seat`` the standing waiver of every Personality's Honor Requirement when
    recruiting."""

    seat: PlayerId

    def perform(self, game: GameState) -> list[GameEvent]:
        ops.set_ignore_honor_requirements(game.table, self.seat, True)
        return []


@dataclass(frozen=True, slots=True)
class Choose(Effect):
    """Pause the cascade so ``seat`` picks between ``minimum`` and ``maximum`` of ``candidates``;
    the chosen ids feed the registered ``resolver``, whose effects apply on resume. The one
    interruption point in the effect vocabulary: every other effect commits at once, so a trigger
    returns a Choose as its sole effect.

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
    source_id : str
        The card whose trigger raised the choice, passed to the resolver.
    """

    seat: PlayerId
    candidates: tuple[str, ...]
    minimum: int
    maximum: int
    resolver: str
    source_id: str

    def perform(self, game: GameState) -> list[GameEvent]:
        raise RuntimeError("a Choose pauses the trigger cascade; it is never applied directly")
