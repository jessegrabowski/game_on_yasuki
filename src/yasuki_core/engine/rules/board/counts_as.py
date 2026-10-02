from collections.abc import Callable
from dataclasses import dataclass
from enum import Enum
from typing import Self

from yasuki_core.engine.registrar import HandlerRegistry
from yasuki_core.engine.rules.state import GameState
from yasuki_core.game_pieces.cards import L5RCard
from yasuki_core.game_pieces.prints import CardPrint


class AskedBy(Enum):
    """What kind of thing asks a card's type, which a printed "counts as ... for actions" or "for
    actions and traits" limits. A rule is the rulebook asking, with no card's text behind it."""

    ACTION = "action"
    TRAIT = "trait"
    RULE = "rule"


@dataclass(frozen=True)
class Asking:
    """Who asks what type a card is: an action or trait printed on ``card``, or the rulebook.

    Build one with :meth:`action`, :meth:`trait` or ``RULEBOOK``. Raise ValueError for a card
    with a rule or a missing card with an action or trait.
    """

    by: AskedBy
    card: L5RCard | None

    def __post_init__(self) -> None:
        if (self.card is None) is not (self.by is AskedBy.RULE):
            card_id = None if self.card is None else self.card.id
            raise ValueError(f"{self.by.value} asking with card {card_id}")

    @classmethod
    def action(cls, card: L5RCard) -> Self:
        return cls(AskedBy.ACTION, card)

    @classmethod
    def trait(cls, card: L5RCard) -> Self:
        return cls(AskedBy.TRAIT, card)


RULEBOOK = Asking(AskedBy.RULE, None)


@dataclass(frozen=True)
class CountsAs:
    """A card's own text making it count as another card type.

    A keyword the card counts as having, such as "counts as a Fortification", is a keyword grant
    and not this.

    Parameters
    ----------
    kind : type of CardPrint
        The print class the card counts as, such as ``RingPrint``. The card counts as that class
        only, not the ones it derives from: a Holding counting as a Ring is not a Fate card.
    asked_by : frozenset of AskedBy
        The askers the printed qualifier admits: "for actions" admits only ``AskedBy.ACTION``.
    condition : callable
        Called as ``condition(game, card, asking)``. Whether the card counts where it stands and
        for whoever asks, such as :func:`while_in_play`.
    """

    kind: type[CardPrint]
    asked_by: frozenset[AskedBy]
    condition: Callable[[GameState, L5RCard, Asking], bool]


# Read only through ``counts_as``, so the representation behind it can change without touching a
# card.
COUNTS_AS: HandlerRegistry[CountsAs] = HandlerRegistry("counts as", "already counts as a type")
register_counts_as = COUNTS_AS.make_register()


def while_in_play(game: GameState, card: L5RCard, asking: Asking) -> bool:
    return any(held is card for held in game.table.battlefield.cards)


def anywhere(game: GameState, card: L5RCard, asking: Asking) -> bool:
    """A continuous trait affecting only its own card holds out of play too (CR, Continuous
    Traits)."""
    return True


def counts_as(game: GameState, card: L5RCard, kind: type[CardPrint], asking: Asking) -> bool:
    """Whether ``asking`` sees ``card`` as a ``kind``: printed as one, or registered as counting
    as one for ``asking`` and meeting its condition."""
    if isinstance(card.printed, kind):
        return True
    grant = COUNTS_AS.get(card.printed_id)
    return (
        grant is not None
        and grant.kind is kind
        and asking.by in grant.asked_by
        and grant.condition(game, card, asking)
    )
