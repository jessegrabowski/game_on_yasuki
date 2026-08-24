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
    invest_amount : int or None
        The gold Invested while recruiting, driving the card's one-time Invest effect on entry, or
        None when the recruit took no Invest. A free Invest is an amount of zero, not None. Default
        None.
    renew : bool
        Whether to refill the vacated province face-up (a granted Renew), on top of the card's own
        Renew keyword. Default False.
    proclaim : bool
        Whether the recruit is Proclaimed, claiming the seat's once-per-turn Proclaim and adding the
        Personality's Personal Honor to its Family Honor after entry. Default False.
    """

    seat: PlayerId
    card_id: str
    invest_amount: int | None = None
    renew: bool = False
    proclaim: bool = False


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
    """The recruit steps that follow a card entering play — clearing its Sincerity tokens, resolving
    a Proclaim's honor gain, and applying any Invest effect. Deferred behind the ``EnteredPlay``
    cascade so a trait that pauses on entry (a Sincerity seed choice) resolves before them.

    Attributes
    ----------
    card_id : str
        The card that entered play.
    invest_amount : int or None
        The gold Invested while recruiting, driving the Invest effect, or None when the recruit took
        no Invest. A free Invest is an amount of zero, not None.
    proclaim : bool
        Whether the recruit was Proclaimed, so entry claims the once-per-turn Proclaim and adds the
        Personality's Personal Honor to its seat's Family Honor. Default False.
    """

    card_id: str
    invest_amount: int | None
    proclaim: bool = False


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
class ResolveEquip:
    """Finish an Equip once its cost is paid: move the attachment from its owner's hand onto the
    battlefield and attach it to the target Personality.

    Attributes
    ----------
    card_id : str
        The attachment leaving hand for play.
    target_id : str
        The Personality it attaches to.
    invest_amount : int or None
        The Invest cost paid, applied once the card is in play, or None when the Equip took no
        Invest. Default None.
    """

    card_id: str
    target_id: str
    invest_amount: int | None = None


@dataclass(frozen=True, slots=True)
class ApplyEffects:
    """Resolve ``effects`` once the current step finishes. The generic deferral: an effect that must
    wait for what precedes it to resolve fully — including any cascade it raises — is queued here
    rather than placed inline, where it would run ahead of the events already in flight.

    Attributes
    ----------
    effects : tuple of Effect
        The effects to resolve, in order.
    """

    effects: tuple[object, ...]


@dataclass(frozen=True, slots=True)
class ContinuePayment:
    """Carry on covering a gold cost until the seat's pool reaches it.

    Owns the solvency question the request cannot answer alone: an answer names producers to bow,
    and only once they have produced is it known whether the cost is met. Re-raises the payment for
    whatever is still owed, spends when the pool covers it, and is what lets a producer's own trait
    fire between one bow and the next.

    Attributes
    ----------
    seat : PlayerId
        The seat being charged.
    amount : int
        The cost to cover, unchanged as the pool fills toward it.
    label : str
        What the payment is for, shown in the prompt.
    target_id : str
        The card being paid for, since a producer's yield can depend on what it pays for. Empty for
        a rulebook cost that prices no card.
    """

    seat: PlayerId
    amount: int
    label: str
    target_id: str = ""


# A unit of deferred engine work, run off GameState.stack once the current decision (if any) clears.
# The action sequence pushes its later steps here while a step pauses for a decision; the union
# grows as those steps do. Work items are ephemeral — replay rebuilds the stack by re-running.
WorkItem = (
    ContinuePayment
    | ResolveRecruit
    | ResolveEquip
    | ResumeCascade
    | SelectAbilityTarget
    | ApplyAbilityEffects
    | ApplyEffects
    | FinishRecruit
)
