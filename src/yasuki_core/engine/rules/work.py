from dataclasses import dataclass

from yasuki_core.engine.players import PlayerId


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


# A unit of deferred engine work, run off GameState.stack once the current decision (if any) clears.
# The action sequence pushes its later steps here while a step pauses for a decision; the union
# grows as those steps do. Work items are ephemeral — replay rebuilds the stack by re-running.
WorkItem = ResolveRecruit
