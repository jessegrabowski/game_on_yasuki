from collections.abc import Callable
from dataclasses import dataclass
from enum import Enum
from types import UnionType

from yasuki_core.engine.rules.abilities.costs import Cost, no_cost
from yasuki_core.engine.rules.vocabulary.actions import ActionTiming, BattleDesignator
from yasuki_core.engine.rules.effects import Effect
from yasuki_core.engine.rules.state import GameState
from yasuki_core.game_pieces.cards import L5RCard


class CardLocation(str, Enum):
    """Where a card must be for its behavior to be offered. Distinct from ``ZoneRole``, which
    cannot name the battlefield, since that is a field of its own on the table, not a keyed zone."""

    BATTLEFIELD = "battlefield"
    PROVINCE = "province"
    HAND = "hand"


@dataclass(frozen=True, slots=True)
class Interruption:
    """What an Interrupt makes of the effect it interrupts.

    Attributes
    ----------
    replacement : Effect
        The effect that resolves in place of the interrupted one, the same one when the Interrupt
        leaves it alone.
    effects : tuple of Effect, optional
        What else the Interrupt does, resolved as the Strategy's own effects before the
        replacement returns. Default none.
    """

    replacement: Effect
    effects: tuple[Effect, ...] = ()


@dataclass(frozen=True, slots=True)
class Interrupt[T: Effect]:
    """An Interrupt a card prints, offered while an effect it answers waits to resolve: from hand
    for a Strategy, which is then played, or from play for a Personality or attachment, whose card
    pays ``cost`` and is otherwise left where its own text leaves it.

    Not an :class:`~.Ability`: it has no target and no effects of its own, since what it does is
    decided against the effect it interrupts, and no round offers it. The Interrupt step offers it
    instead.

    Attributes
    ----------
    label : str
        What a client shows for the card.
    answers : type
        The effect type the Interrupt may be taken against, or a union of them: one naming
        ``Fear`` is offered while a Fear effect waits to resolve, one naming ``Bow | Move`` while
        either does.
    interrupt : callable
        Maps ``(game, source_card, effect)`` to the :class:`~.Interruption` it makes of the pending
        effect: what replaces it and what else happens. With ``targets`` set, the chosen target is
        passed as a fourth argument.
    targets : callable, optional
        Maps ``(game, source_card, effect)`` to the ids of the cards the Interrupt may target, for
        a card that reads "Interrupt: Target your X". The step asks for the target once the card is
        chosen, and does not offer a card that could target nothing. Default None, untargeted.
    applies : callable, optional
        Maps ``(game, source_card, effect)`` to whether this Interrupt may answer that particular
        effect, for a card whose text narrows it beyond the type, as "your other Personality's
        bowing" does. Default answers every effect of the type.
    located_at : tuple of CardLocation, optional
        Where the card has to be for the Interrupt to be offered. A Strategy's is taken from hand
        and the card is played; a Personality's or attachment's is taken from play, under the
        gates an activated ability in play answers to, and the card is not discarded for it.
        Default the hand alone.
    cost : callable, optional
        Maps ``(game, source_card)`` to the effects paid to take an Interrupt from play, resolved
        before the Interrupt's own. A Strategy from hand pays its Gold Cost instead. Default
        ``no_cost``.
    answers_every : bool, optional
        Whether the Interrupt answers every effect of the action it could, at once, as "negate
        the action's effects" does, instead of one the seat picks. ``interrupt`` is then asked of
        each effect as it comes up to resolve, and its own ``effects`` resolve once. Default False.
    """

    label: str
    answers: type[T] | UnionType
    interrupt: Callable[..., Interruption]
    applies: Callable[[GameState, L5RCard, T], bool] = lambda game, source, effect: True
    located_at: tuple[CardLocation, ...] = (CardLocation.HAND,)
    cost: Cost = no_cost
    targets: Callable[[GameState, L5RCard, T], tuple[str, ...]] | None = None
    answers_every: bool = False


@dataclass(frozen=True, slots=True)
class Ability:
    """An activated ability, on a card in play or on one waiting face-up in a Province.

    Attributes
    ----------
    timings : tuple of ActionTiming
        The designators printed on the card, saying when the ability may be used and by whom. A card
        printing more than one, as in "Battle/Open", may be used in any round that permits any
        of them.
    label : str
        A short human description for the activation menu.
    cost : callable
        Maps ``(game, source_card)`` to the effects paid to activate, applied before the ability's
        own.
    targets : callable
        Maps ``(game, source_card)`` to the ids of the cards the ability may target, empty when
        none are legal, which also means the ability can't be offered.
    targeting_message : str, optional
        What the ability targets, worded as the card prints it: "your Courtier at any location".
        The target prompt reads "Target your Courtier at any location for Inexplicable Challenge".
        Default None, which prompts for a card by the card's name alone.
    effects : callable
        Maps ``(game, source_card, target_card)`` to the effects the ability emits against a
        target.
    hits_every_target : bool
        Whether the ability hits every card ``targets`` returns rather than one chosen among them,
        as an untargeted "your other Farms" grant instead of a single pick. Default False.
    located_at : tuple of CardLocation, optional
        Where the card has to be for the ability to be offered. An Event acts from the Province it
        sits face-up in, never from play. Default the battlefield alone.
    battle_designators : frozenset of BattleDesignator, optional
        The designators qualifying how the ability escapes the Rule of Presence or the Rules of
        Location during a battle. Default empty, which takes both rules as written.
    targets_any_location : bool, optional
        Whether the ability reaches a target wherever it stands, granted by the "at any location"
        a card prints, which lifts the Rules of Location off what it may be pointed at but not off
        the card it is taken from. Default False.
    key : str, optional
        Names this ability among the several its card prints, so an action can say which one it
        takes. A card printing one ability needs no key, because there is nothing to tell apart.
        Default None.
    tireless : bool, optional
        The Tireless keyword: the ability may be used even while its card is bowed (CR, Tireless).
        Default False, which leaves it to the rule that a bowed card's abilities cannot be used.
    unstoppable : bool, optional
        Whether other players may not play Interrupts to the action, the Unstoppable modifier
        printed ahead of the designator (ShE datasheet, Unstoppable). Default False.
    keywords : frozenset of str, optional
        The ability keywords printed ahead of the designator, as in "Political Battle:". They
        classify the action the ability produces and rise to the card that holds it, and the
        registration audit checks them against the printed text. Default empty.
    repeatable : bool, optional
        The Repeatable modifier: the ability may be used more than once per turn in an arc whose
        ruleset makes abilities once per turn (CR, Using Abilities 0.3). Default False. The
        registration audit checks it against the printed text.
    trait : bool, optional
        Whether this is a trait worded "after X, you may ..." rather than an action: offered in the
        Response Step, so its controller orders it among the Responses to the same action and may
        decline it, but resolved as a trait's effects, with no Interrupt step against them. A trait
        is not an action (CR, Traits), so a card reading "your action" does not see its effects.
        Default False.
    """

    timings: tuple[ActionTiming, ...]
    label: str
    cost: Cost
    targets: Callable[[GameState, L5RCard], list[str]]
    effects: Callable[[GameState, L5RCard, L5RCard], list[Effect]]
    hits_every_target: bool = False
    located_at: tuple[CardLocation, ...] = (CardLocation.BATTLEFIELD,)
    battle_designators: frozenset[BattleDesignator] = frozenset()
    targets_any_location: bool = False
    key: str | None = None
    tireless: bool = False
    keywords: frozenset[str] = frozenset()
    repeatable: bool = False
    unstoppable: bool = False
    trait: bool = False
    targeting_message: str | None = None


def once_tag(ability: Ability) -> str:
    """The once-per-turn tag an ability's use is claimed under, distinct per keyed ability."""
    return f"ability:{ability.key or ''}"


@dataclass(frozen=True, slots=True)
class InvestAbility:
    """A card's Invest ability, an optional gold cost paid while recruiting for a one-time
    enter-play effect (the kicker-style second purchase option).

    Attributes
    ----------
    amounts : tuple of int
        Every sum the Invest may be paid for, least first. A single entry is a fixed Invest.
        Several are the choice the recruiting seat makes, which a card prints either as a span
        ("Invest :g1: to :g3:") or as separate prices that buy different things ("Invest :g2: or
        :g6:").
    effect : callable
        Maps ``(game, source_card, amount_paid)`` to the effects the Invest emits once the card
        enters play. It takes the board because an Invest may search a zone for what it fetches.
    """

    amounts: tuple[int, ...]
    effect: Callable[[GameState, L5RCard, int], list[Effect]]


def itself(game: GameState, source: L5RCard) -> list[str]:
    """The target list of an ability that names no target: its own card. Paired with
    ``hits_every_target``, so the ability resolves against itself without asking the seat to pick
    the only card it could mean."""
    return [source.id]
