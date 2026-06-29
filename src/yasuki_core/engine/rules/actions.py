from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class Pass:
    """Take no action, ending the current phase."""


@dataclass(frozen=True, slots=True)
class ProduceGold:
    """Bow a gold-producing card in play to add its gold to the pool.

    Attributes
    ----------
    card_id : str
        The producing card to bow.
    amount : int
        The gold it produces (its ``gold_production`` stat), carried for display.
    """

    card_id: str
    amount: int


@dataclass(frozen=True, slots=True)
class Recruit:
    """Bring a face-up card from a province into play, paying its gold cost.

    Attributes
    ----------
    card_id : str
        The province card to recruit.
    """

    card_id: str


# The free actions a seat may take on its turn; grows as the rules vocabulary does.
Action = Pass | ProduceGold | Recruit
