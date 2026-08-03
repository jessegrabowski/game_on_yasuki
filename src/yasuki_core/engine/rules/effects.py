from dataclasses import dataclass

from yasuki_core.engine.players import PlayerId
from yasuki_core.engine.rules.modifiers import Duration, Stat
from yasuki_core.game_pieces.counters import Counter


@dataclass(frozen=True, slots=True)
class AdjustCounter:
    """Effect: add ``delta`` to a counter on a card (floored at zero by the card). A grant is a
    positive delta, a removal negative. The rules-side twin of the sandbox ``AdjustCounter`` intent,
    applied through :func:`~yasuki_core.engine.rules.triggers.apply_effect` rather than
    ``apply_intent``."""

    card_id: str
    counter: Counter
    delta: int


@dataclass(frozen=True, slots=True)
class DrawCard:
    """Effect: ``seat`` draws a card from its fate deck."""

    seat: PlayerId


@dataclass(frozen=True, slots=True)
class Destroy:
    """Effect: destroy a card, sending it to its owner's discard by side."""

    card_id: str


@dataclass(frozen=True, slots=True)
class GrantModifier:
    """Effect: record a continuous stat modifier — the ``source`` card grants ``target`` a change of
    ``amount`` to ``stat`` for ``duration``. The single created-effect entry point; a card's
    counters and attachments grant their bonuses without one (they are derived on read)."""

    source_id: str
    target_id: str
    stat: Stat
    amount: int
    duration: Duration


@dataclass(frozen=True, slots=True)
class Bow:
    """Effect: bow a card."""

    card_id: str


@dataclass(frozen=True, slots=True)
class Straighten:
    """Effect: straighten (unbow) a card."""

    card_id: str


@dataclass(frozen=True, slots=True)
class BanishTopFate:
    """Effect: banish the top card of ``seat``'s Fate deck; a no-op if the deck is empty."""

    seat: PlayerId


@dataclass(frozen=True, slots=True)
class GainGold:
    """Effect: add ``amount`` gold to ``seat``'s pool — gold produced outside a payment (a card that
    produces gold on entry), transient and cleared at the end of the phase."""

    seat: PlayerId
    amount: int


@dataclass(frozen=True, slots=True)
class IgnoreHonorRequirements:
    """Effect: grant ``seat`` the standing waiver of every Personality's Honor Requirement when
    recruiting."""

    seat: PlayerId


@dataclass(frozen=True, slots=True)
class Choose:
    """Effect: pause the cascade so ``seat`` picks between ``minimum`` and ``maximum`` of
    ``candidates``; the chosen ids feed the registered ``resolver``, whose effects apply on resume.
    The one interruption point in the effect vocabulary — every other effect commits at once, so a
    trigger returns a Choose as its sole effect.

    Attributes
    ----------
    seat : PlayerId
        The seat that chooses.
    candidates : tuple of str
        The card ids the seat may pick among.
    minimum : int
        The fewest cards the seat may pick — zero when the choice is optional.
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


Effect = (
    AdjustCounter
    | DrawCard
    | Destroy
    | GrantModifier
    | Bow
    | Straighten
    | BanishTopFate
    | GainGold
    | IgnoreHonorRequirements
    | Choose
)
