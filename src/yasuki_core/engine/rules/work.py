from dataclasses import dataclass

from yasuki_core.engine.players import PlayerId
from yasuki_core.engine.rules.events import GameEvent


@dataclass(frozen=True, slots=True)
class ResolveRecruit:
    """Finish a Recruit once its cost is paid: bring the card from its province into play (bowed for
    a Holding) and refill the vacated province.

    Attributes
    ----------
    seat : PlayerId
        The recruiting seat.
    card_id : str
        The card leaving its province for play.
    """

    seat: PlayerId
    card_id: str


@dataclass(frozen=True, slots=True)
class ResumeCascade:
    """A trigger cascade a choice paused mid-event: the ``(card_id, trigger)`` pairs still to fire
    for ``event``, then the events still queued behind them, run once the choice's own effects
    resolve. Ephemeral like the rest of the stack — its triggers are stable module-level functions,
    so it rebuilds and compares equal under replay.

    Attributes
    ----------
    remaining : tuple of (str, callable)
        The card id and trigger of each subscriber still to fire for ``event``.
    event : GameEvent
        The event whose remaining triggers these are.
    queue : tuple of GameEvent
        The events still waiting behind ``event`` in the paused worklist.
    """

    remaining: tuple[tuple[str, object], ...]
    event: GameEvent
    queue: tuple[GameEvent, ...]


# A unit of deferred engine work, run off GameState.stack once the current decision (if any) clears.
# The action sequence pushes its later steps here while a step pauses for a decision; the union
# grows as those steps do. Work items are ephemeral — replay rebuilds the stack by re-running.
WorkItem = ResolveRecruit | ResumeCascade
