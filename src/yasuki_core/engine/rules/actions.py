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
    """

    card_id: str


@dataclass(frozen=True, slots=True)
class DynastyDiscard:
    """Discard a face-up card from one of your provinces (Repeatable Dynasty), refilling it.

    Attributes
    ----------
    card_id : str
        The face-up province card to discard.
    """

    card_id: str


# The free actions a seat may take on its turn; grows as the rules vocabulary does.
Action = Pass | Recruit | DynastyDiscard
