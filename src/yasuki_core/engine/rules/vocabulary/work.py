from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol

from yasuki_core.engine.rules.vocabulary.modifiers import Negation


if TYPE_CHECKING:
    from yasuki_core.engine.rules.effects import Effect
    from yasuki_core.engine.rules.state import GameState


class WorkItem(Protocol):
    """A unit of deferred engine work, held on ``GameState.stack`` and run once the current decision
    clears. Each item lives beside the procedure that pushes it and continues that procedure in
    :meth:`resume`, which may itself end in a question."""

    def resume(self, game: "GameState") -> None:
        """Continue the procedure this item was pushed by."""
        ...


class Modification(Protocol):
    """What an Interrupt makes of one of the action's effects, held on ``GameState.modifications``
    from the Interrupt step until that effect comes up to resolve (CR, Interrupt Actions: an
    Interrupt "may modify the effects of the action it interrupts", and what it does "is delayed
    until those effects occur")."""

    def answers(self, effect: "Effect") -> bool:
        """Whether ``effect``, as the action first handed it to step E, is the one this modifies."""
        ...

    def apply(self, game: "GameState", effect: "Effect") -> "Effect":
        """The effect that resolves in place of ``effect``, which may already carry an earlier
        modification of the same original."""
        ...


@dataclass(frozen=True, slots=True)
class Targeting:
    """The targets an action chose in step C, which step E checks are still legal before carrying
    out the effects that require them (CR, Action Sequence).

    Attributes
    ----------
    card_id : str
        The card whose ability the action is.
    ability_key : str or None
        Names the ability among the several the card prints, or None for its only one.
    picked : tuple of tuple of str
        The cards each "target" phrase took, in print order.
    """

    card_id: str
    ability_key: str | None
    picked: tuple[tuple[str, ...], ...]


@dataclass(frozen=True, slots=True)
class Provenance:
    """Where the effects a cascade holds came from, which decides what may reach them. The cascade
    carries it across every pause and deferral, so an effect a question or a delay holds back
    resolves as what it was.

    Attributes
    ----------
    interruptible : bool, optional
        Whether the effects are an action's own, the only ones an Interrupt may modify (ShE
        datasheet, Interrupt). Default False.
    triggered : bool, optional
        Whether the effects are a trigger's, so a decision among them is the trigger's question and
        cannot be backed out of. Default False.
    paying : bool, optional
        Whether the effects are a cost's payments, which are no effects (CR, Effects), so no
        negation reaches them. Default False.
    acting : str, optional
        The card whose action produced the effects, which a negation naming a source is matched
        against. Default None, for a trait's, the rulebook's, a delayed effect's or a cost's.
    negations : tuple of Negation, optional
        The ``once`` negations naming only a source that the action spent as it handed its effects
        over, which negate every effect of that action and no other. Default none.
    lapsed : frozenset of str, optional
        The cards the action targeted that were no longer legal targets as its resolution began.
        The action's effects stop at the first that acts on one, and nothing after it happens (CR,
        Action Sequence step E). Default none.
    """

    interruptible: bool = False
    triggered: bool = False
    paying: bool = False
    acting: str | None = None
    negations: tuple[Negation, ...] = ()
    lapsed: frozenset[str] = frozenset()
