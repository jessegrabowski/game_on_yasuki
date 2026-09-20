from typing import TYPE_CHECKING, Protocol


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
