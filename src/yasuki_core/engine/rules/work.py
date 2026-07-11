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
    invest_amount : int
        The gold Invested while recruiting, driving the card's one-time Invest effect on entry, or 0
        when not Invested. Default 0.
    renew : bool
        Whether to refill the vacated province face-up (a granted Renew), on top of the card's own
        Renew keyword. Default False.
    """

    seat: PlayerId
    card_id: str
    invest_amount: int = 0
    renew: bool = False


@dataclass(frozen=True, slots=True)
class ResumeCascade:
    """The exact remainder of an effect-and-trigger cascade a choice paused: the effects still to
    apply, then the ``(card_id, trigger)`` pairs still to fire for ``event``, then the events still
    queued behind them. The answered choice's own effects splice in ahead of these. Ephemeral like
    the rest of the stack — its effects and triggers are value-equal and stable module-level
    functions, so it rebuilds and compares equal under replay.

    Attributes
    ----------
    effects : tuple of Effect
        The effects still to apply for the paused trigger, after the one that raised the choice.
    firing : tuple of (str, callable)
        The card id and trigger of each subscriber still to fire for ``event``.
    event : GameEvent or None
        The event those triggers are firing for, or None when the pause held only loose effects.
    queue : tuple of GameEvent
        The events still waiting behind ``event`` in the paused worklist.
    """

    effects: tuple[object, ...]
    firing: tuple[tuple[str, object], ...]
    event: GameEvent | None
    queue: tuple[GameEvent, ...]


@dataclass(frozen=True, slots=True)
class SelectAbilityTarget:
    """Raise an activated ability's target choice once its cost has been paid. Deferred so a cost
    whose own cascade pauses for a decision resolves fully before the target is chosen.

    Attributes
    ----------
    card_id : str
        The card whose ability is resolving.
    candidates : tuple of str
        The ids the ability may target, fixed before paying so the choice is never left empty.
    """

    card_id: str
    candidates: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class FinishRecruit:
    """The recruit steps that follow a card entering play — clearing its Sincerity tokens and
    applying any Invest effect. Deferred behind the ``EnteredPlay`` cascade so a trait that pauses on
    entry (a Sincerity seed choice) resolves before them.

    Attributes
    ----------
    card_id : str
        The card that entered play.
    invest_amount : int
        The gold Invested while recruiting, driving the Invest effect, or 0 when not Invested.
    """

    card_id: str
    invest_amount: int


@dataclass(frozen=True, slots=True)
class ApplyAbilityEffects:
    """Resolve an untargeted ability's effects against every card it hits, once its cost has been
    paid. The all-target counterpart of :class:`SelectAbilityTarget`, deferred for the same reason.

    Attributes
    ----------
    card_id : str
        The card whose ability is resolving.
    target_ids : tuple of str
        The cards the ability affects, fixed before paying.
    """

    card_id: str
    target_ids: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class ModestFarmStraighten:
    """Offer Modest Farm's optional sacrifice once its targeted recruit has resolved: the controller
    may destroy Modest Farm to straighten the freshly recruited card. Deferred so it runs after the
    recruit's payment and entry.

    Attributes
    ----------
    modest_farm_id : str
        The Modest Farm that may be destroyed.
    target_id : str
        The recruited card that would be straightened.
    """

    modest_farm_id: str
    target_id: str


# A unit of deferred engine work, run off GameState.stack once the current decision (if any) clears.
# The action sequence pushes its later steps here while a step pauses for a decision; the union
# grows as those steps do. Work items are ephemeral — replay rebuilds the stack by re-running.
WorkItem = (
    ResolveRecruit
    | ResumeCascade
    | SelectAbilityTarget
    | ApplyAbilityEffects
    | FinishRecruit
    | ModestFarmStraighten
)
