from typing import TYPE_CHECKING, Protocol


if TYPE_CHECKING:
    from yasuki_core.engine.rules.state import GameState


class WorkItem(Protocol):
    """A unit of deferred engine work, held on ``GameState.stack`` and run once the current decision
    clears. Each item lives beside the procedure that pushes it and continues that procedure in
    :meth:`resume`, which may itself end in a question."""

    def resume(self, game: "GameState") -> None:
        """Continue the procedure this item was pushed by."""
        ...
