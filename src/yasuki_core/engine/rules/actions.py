from dataclasses import dataclass


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
        Whether to also pay the card's Invest cost for its one-time enter-play effect — the
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
    your dynasty deck and provinces for a Legacy card and place it face-up in a province; failing
    to find one loses the game. The banished card and the placement province are chosen through the
    decisions the action raises, so the action itself carries no target."""


@dataclass(frozen=True, slots=True)
class ActivateAbility:
    """Activate the activated ability on an in-play card, bowing it as the cost. The ability's target
    is chosen through the decision the action raises.

    Attributes
    ----------
    card_id : str
        The card whose ability is used.
    """

    card_id: str


# The free actions a seat may take on its turn; grows as the rules vocabulary does.
Action = Pass | Recruit | DynastyDiscard | Legacy | ActivateAbility
