from dataclasses import dataclass
from enum import Enum


class BattleDesignator(Enum):
    """A designator qualifying how a battle action escapes the Rule of Presence or the Rules of
    Location (ShE datasheet).

    ABSENT
        Playable without presence at the current battlefield.
    HOME
        Usable from a card at home rather than at the current battlefield. It does not lift the
        Rule of Presence, which the datasheet says in as many words: the two are independent, and a
        card needs ``ABSENT`` as well to be used by a seat with no presence.
    REMOTE
        Usable from a card at home or at another battlefield, a wider ``HOME``.
    """

    ABSENT = "absent"
    HOME = "home"
    REMOTE = "remote"


class ActionTiming(Enum):
    """When an action may be taken, and by whom: the designator printed ahead of an ability's text.

    Each names an Action Round and a first actor:

    - ``OPEN``: the Action Phase, by any player
    - ``LIMITED``: the Action Phase, only by the active player
    - ``DYNASTY``: the Dynasty phase, only by the active player
    - ``ATTACK``: the Attack Phase's Declaration Segment, only by the active player
    - ``ENGAGE``: a battle's Engage Segment, by any player, the Defender acting first
    - ``BATTLE``: a battle's Combat Segment, by any player, the Defender acting first
    - ``INTERRUPT``: the Interrupt step of another action, by any player
    - ``RESPONSE``: the Response step of another action, by any player [ShE]

    Repeatability is a separate axis: a designator says *when*, and whether an ability on a card
    in play may be used again this turn is ``repeatable`` on its registration under an arc whose
    ruleset makes abilities once per turn (CR, Using Abilities 0.3).
    """

    OPEN = "open"
    LIMITED = "limited"
    DYNASTY = "dynasty"
    ATTACK = "attack"
    ENGAGE = "engage"
    BATTLE = "battle"
    INTERRUPT = "interrupt"
    RESPONSE = "response"


@dataclass(frozen=True, slots=True)
class Pass:
    """Take no action, ending the current phase."""


@dataclass(frozen=True, slots=True)
class PlayStrategy:
    """Play a Strategy from hand for its Gold Cost, resolve its ability, and discard it. Under
    Discipline it is played from its owner's discard pile instead, for its Gold Cost and its
    Discipline, and removed from the game afterward (CR, Discipline).

    Offered in whichever Action Round the card's own ability names, not a fixed one. Carries no
    entry in ``ACTION_TIMINGS``. Its target is chosen through the decision the ability raises.

    Attributes
    ----------
    card_id : str
        The Strategy being played.
    ability_key : str, optional
        Names the ability among the several the card prints, so the one announced is the one
        that resolves. Default None, the card's only ability.
    disciplined : bool, optional
        Whether it is played from the discard pile under Discipline. Default False, from hand.
    """

    card_id: str
    ability_key: str | None = None
    disciplined: bool = False


@dataclass(frozen=True, slots=True)
class Equip:
    """Attach a Follower, Item or Spell from hand to a Personality you control, paying its Gold
    Cost.

    The Personality is chosen through the decision the action raises rather than named here, the way
    an activated ability picks its target.

    Attributes
    ----------
    card_id : str
        The attachment in hand.
    invest : bool
        Whether to pay the card's Invest cost on top of its Gold Cost. Invest belongs to a card
        entering play rather than to the action that brought it, so Equip offers it exactly as
        a Recruit does. Default False.
    discount : int
        The Gold this Equip charges less, for the Personalities whose texts grant that much on this
        card, which are then the only ones it may join: paying the lower price obliges the target
        (CR, Targeting Paradoxes). Default 0, the full price, which may join any Personality that
        would accept the card.
    """

    card_id: str
    invest: bool = False
    discount: int = 0


@dataclass(frozen=True, slots=True)
class ActivateAbility:
    """Activate the activated ability on an in-play card, bowing it as the cost. The ability's
    target is chosen through the decision the action raises.

    Attributes
    ----------
    card_id : str
        The card whose ability is used.
    ability_key : str, optional
        Names the ability among the several the card prints, so the one announced is the one
        that resolves. Default None, the card's only ability.
    """

    card_id: str
    ability_key: str | None = None


@dataclass(frozen=True, slots=True)
class PlayInterrupt:
    """Take one of a card's Interrupts against the action now held at the Interrupt step: its own
    as a Strategy from hand, played and paid for, or from a card in play, which pays the
    Interrupt's own cost, or one a keyword on the card confers, which pays its own cost. Which of
    the action's effects it answers, its target and its payment follow as decisions.

    Attributes
    ----------
    card_id : str
        The card whose Interrupt is taken.
    interrupt_key : str, optional
        The Interrupt taken, for one a keyword confers. Default None, the one the card prints.
    disciplined : bool, optional
        Whether a Strategy's own Interrupt is played from its discard pile under Discipline (CR,
        Discipline). Default False.
    """

    card_id: str
    interrupt_key: str | None = None
    disciplined: bool = False


@dataclass(frozen=True, slots=True)
class DeclareAttack:
    """Declare an attack in the Attack Phase, creating a battlefield at each of the Defender's
    Provinces (CR, Declare an Attack).

    An action the seat takes, not a decision the engine raises: the active player *"may now
    optionally create"* an attack. Passing the Attack Phase is how a seat declines.
    """


# The free actions a seat may take on its turn; grows as the rules vocabulary does.
Action = Pass | PlayStrategy | Equip | ActivateAbility | DeclareAttack | PlayInterrupt

# The designator each rulebook action is taken under. Pass is absent because it is the alternative
# to taking an action rather than one, and ActivateAbility because it reads its designator off the
# card. The same action is Open on one Holding and Dynasty on another.
ACTION_TIMINGS: dict[type, ActionTiming] = {
    # Repeatable Open, not Dynasty (CR, Equip). It is taken in the Action phase like Kharmic.
    Equip: ActionTiming.OPEN,
    DeclareAttack: ActionTiming.ATTACK,
    PlayInterrupt: ActionTiming.INTERRUPT,
}
