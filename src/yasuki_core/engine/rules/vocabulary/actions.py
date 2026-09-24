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
class Recruit:
    """Bring a face-up card from a province into play, paying its gold cost.

    Attributes
    ----------
    card_id : str
        The province card to recruit.
    invest : bool
        Whether to also pay the card's Invest cost for its one-time enter-play effect, the
        kicker-style second purchase option. Default False.
    proclaim : bool
        Whether to Proclaim the recruit (once per turn, own-clan Personalities only), adding the
        Personality's Personal Honor to the seat's Family Honor after it enters play. Default False.
    """

    card_id: str
    invest: bool = False
    proclaim: bool = False


@dataclass(frozen=True, slots=True)
class DynastyDiscard:
    """Discard a face-up card from one of your provinces (Repeatable Dynasty), refilling it.

    Attributes
    ----------
    card_id : str
        The face-up province card to discard.
    """

    card_id: str


@dataclass(frozen=True, slots=True)
class Legacy:
    """Take the Legacy rulebook ability (Dynasty, once per turn): banish a card from hand to search
    your dynasty deck and provinces for a Legacy card and place it face-up in a province. Failing
    to find one loses the game. The banished card and the placement province are chosen through the
    decisions the action raises, so the action itself carries no target."""


@dataclass(frozen=True, slots=True)
class Inheritance:
    """Take the Inheritance rulebook ability (Dynasty, once per game, only if you did not go first):
    turn your Stronghold over to give a Holding you control +3 Gold Production for the turn. The
    Holding is chosen through the decision the action raises. [ShE]"""


@dataclass(frozen=True, slots=True)
class PlayStrategy:
    """Play a Strategy from hand for its Gold Cost, resolve its ability, and discard it.

    Offered in whichever Action Round the card's own ability names, not a fixed one. Carries no
    entry in ``ACTION_TIMINGS``. Its target is chosen through the decision the ability raises.

    Attributes
    ----------
    card_id : str
        The Strategy in hand.
    ability_key : str, optional
        Names the ability among the several the card prints, so the one announced is the one
        that resolves. Default None, the card's only ability.
    """

    card_id: str
    ability_key: str | None = None


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
        Recruit does. Default False.
    """

    card_id: str
    invest: bool = False


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
class Cycle:
    """Take the Cycle rulebook ability (Limited, your first turn only): put one or more face-up
    Province cards on the bottom of your dynasty deck, then refill and reveal your Provinces. Which
    cards, and the order they go under in, are chosen through the decision the action raises."""


@dataclass(frozen=True, slots=True)
class Lobby:
    """Take the Lobby rulebook ability: on your turn, with higher Family Honor than each other
    player, bow a Personality to take the Imperial Favor. Which Personality bows is chosen through
    the decision the action raises, so the action itself carries no target. [ShE]"""


@dataclass(frozen=True, slots=True)
class UseFavorAbility:
    """Take one of the rulebook abilities the Imperial Favor pays for.

    Which abilities exist, and what each is designated, comes from the arc's ruleset rather than
    from here: the pre-Gold rulebook granted four and the ShE datasheet grants two.

    Attributes
    ----------
    key : str
        Names the ability among the arc's, matching a ``FavorAbility.key``.
    """

    key: str


@dataclass(frozen=True, slots=True)
class PlayInterrupt:
    """Take the Interrupt a card prints against the action now held at the Interrupt step: a
    Strategy from hand, played and paid for, or a card in play, which pays the Interrupt's own
    cost. Which of the action's effects it answers, its target and its payment follow as
    decisions.

    Attributes
    ----------
    card_id : str
        The card whose Interrupt is taken.
    """

    card_id: str


@dataclass(frozen=True, slots=True)
class DiscardToInterrupt:
    """Take a rulebook Interrupt the ShE datasheet grants, discarding a card carrying its keyword
    to adjust one of the held action's effects. The adjustment follows as a decision.

    Attributes
    ----------
    card_id : str
        The card discarded for it.
    key : str
        The rulebook Interrupt taken, ``"courage"`` or ``"honor"``.
    """

    card_id: str
    key: str


@dataclass(frozen=True, slots=True)
class DeclareAttack:
    """Declare an attack in the Attack Phase, creating a battlefield at each of the Defender's
    Provinces (CR, Declare an Attack).

    An action the seat takes, not a decision the engine raises: the active player *"may now
    optionally create"* an attack. Passing the Attack Phase is how a seat declines.
    """


# The free actions a seat may take on its turn; grows as the rules vocabulary does.
Action = (
    Pass
    | Recruit
    | PlayStrategy
    | Equip
    | DynastyDiscard
    | Legacy
    | ActivateAbility
    | Cycle
    | Inheritance
    | Lobby
    | UseFavorAbility
    | DeclareAttack
    | PlayInterrupt
    | DiscardToInterrupt
)

# The designator each rulebook action is taken under. Pass is absent because it is the alternative
# to taking an action rather than one, and ActivateAbility because it reads its designator off the
# card. The same action is Open on one Holding and Dynasty on another. Lobby and UseFavorAbility
# are absent because they read their designators off the arc's ruleset: the Twenty Festivals CR
# makes Lobby Limited where the ShE datasheet makes it Open, and which Favor abilities exist at all
# differs by arc.
ACTION_TIMINGS: dict[type, ActionTiming] = {
    Cycle: ActionTiming.LIMITED,
    Recruit: ActionTiming.DYNASTY,
    # Repeatable Open, not Dynasty (CR, Equip). It is taken in the Action phase like Kharmic.
    Equip: ActionTiming.OPEN,
    DynastyDiscard: ActionTiming.DYNASTY,
    Legacy: ActionTiming.DYNASTY,
    Inheritance: ActionTiming.DYNASTY,
    DeclareAttack: ActionTiming.ATTACK,
    PlayInterrupt: ActionTiming.INTERRUPT,
    DiscardToInterrupt: ActionTiming.INTERRUPT,
}
