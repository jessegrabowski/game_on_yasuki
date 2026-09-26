from dataclasses import dataclass

from collections.abc import Callable

from yasuki_core.engine.players import PlayerId
from yasuki_core.engine.rules import triggers
from yasuki_core.engine.rules.vocabulary.game_events import Bowed, ProducedGold, ProducingGold
from yasuki_core.engine.rules.vocabulary.modifiers import Stat
from yasuki_core.engine.registrar import HandlerRegistry
from yasuki_core.engine.rules.state import GameState
from yasuki_core.engine.rules.stats.calculation import active_modifiers
from yasuki_core.game_pieces.cards import L5RCard


# A gold-production handler computes what a card produces in context, from the producing card, the
# game, the seat it produces for, and the cards being paid for.
GoldHandler = Callable[[L5RCard, GameState, PlayerId, tuple[L5RCard, ...]], int]
GOLD_HANDLERS: HandlerRegistry[GoldHandler] = HandlerRegistry(
    "gold handlers", "already has a gold handler"
)
gold_handler = GOLD_HANDLERS.make_decorator()


def reads_its_targets(card: L5RCard) -> bool:
    """Whether ``card``'s yield can depend on what it is paying for, which only a registered handler
    is given the chance to read."""
    return card.printed_id in GOLD_HANDLERS


def effective_gold_production(
    game: GameState, card: L5RCard, targets: tuple[L5RCard, ...] = ()
) -> int:
    """The gold ``card`` produces right now: its registered handler's result against the live views,
    or its printed ``gold_production`` when no handler is registered, plus every active Gold
    Production modifier on it (wealth counters, ability grants), floored at zero. A card with no
    Gold Production stat produces 0 and receives no modifiers (the stat is absent).

    Parameters
    ----------
    game : GameState
        The live game the views project from.
    card : L5RCard
        The producing card.
    targets : tuple of L5RCard, optional
        The cards being paid for, for a handler whose yield depends on what it pays for. Default
        empty.

    Returns
    -------
    produced : int
        The gold the card yields now.
    """
    handler = GOLD_HANDLERS.get(card.printed_id)
    if handler is None:
        if not hasattr(card, "gold_production"):
            return 0  # an absent stat cannot receive modifiers (CR, Absent Stats)
        base = card.gold_production
    else:
        base = handler(card, game, card.owner, targets)
    total = base + sum(
        modifier.amount for modifier in active_modifiers(game, card, Stat.GOLD_PRODUCTION)
    )
    return max(0, total)


@dataclass(frozen=True, slots=True)
class CompleteProduction:
    """Read a producer's yield and bow it, once the window it opened has closed.

    Deferred rather than run inline because a trait firing in that window may pause for a decision,
    and the yield has to be read after whatever the seat answers. Only safe because a payment answer
    names one producer: two would open two windows before either was answered.

    Attributes
    ----------
    card_id : str
        The producer to bow.
    target_ids : tuple of str
        The cards being paid for, since a producer's yield can depend on what it pays for. Empty for
        a cost that prices no card.
    """

    card_id: str
    target_ids: tuple[str, ...] = ()

    def resume(self, game: GameState) -> None:
        complete_production(game, self.card_id, self.target_ids)


def produce_gold(game: GameState, card_id: str, target_ids: tuple[str, ...] = ()) -> None:
    """Open the producer's window, then bow it and add its yield to its owner's pool (KD6).

    Gold is only produced while paying a cost (rules-skeleton section 7), so a payment drives
    this. The yield is read after the window rather than quoted up front, because a trait
    firing there can raise it, and announced through ``ProducedGold`` afterwards, because a
    price payable once the card has bowed cannot resolve while the yield is still unread.

    The read is deferred onto the stack rather than run inline so that a window trait may
    pause for a decision: the yield is then taken on the far side of whatever the seat answers.
    """
    card = game.table.cards_by_id[card_id]
    game.stack.append(CompleteProduction(card_id, target_ids))
    triggers.fire(game, ProducingGold(card_id, card.owner))


def complete_production(game: GameState, card_id: str, target_ids: tuple[str, ...]) -> None:
    """Bow the producer for whatever it is worth now, and announce what it made."""
    card = game.table.cards_by_id[card_id]
    targets = tuple(game.table.cards_by_id[tid] for tid in target_ids)
    amount = effective_gold_production(game, card, targets=targets)
    card.bow()
    game.add_gold(card.owner, amount)
    triggers.fire_all(game, [Bowed(card_id), ProducedGold(card_id, card.owner, amount)])
