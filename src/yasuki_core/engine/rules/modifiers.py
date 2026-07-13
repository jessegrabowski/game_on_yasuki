from dataclasses import dataclass
from enum import Enum


class Stat(Enum):
    """A card stat a modifier can adjust. Each member's value is the card attribute it reads, so a
    derived source can look it up with ``getattr(card, stat.value)``. Only Gold Production is
    computed at runtime today; more stats join as the rules engine grows."""

    GOLD_PRODUCTION = "gold_production"


class Duration(Enum):
    """How long a modifier stays active.

    UNTIL_END_OF_TURN
        The default for action and ability effects; dropped when the turn ends.
    WHILE_SOURCE_IN_PLAY
        Active only while the modifier's source is on the battlefield — counters, attachments, and
        continuous auras.
    PERMANENT
        Lasts the rest of the game regardless of its source.
    """

    UNTIL_END_OF_TURN = "until_end_of_turn"
    WHILE_SOURCE_IN_PLAY = "while_source_in_play"
    PERMANENT = "permanent"


@dataclass(frozen=True, slots=True)
class Modifier:
    """A continuous effect that adjusts one card's stat by a fixed amount while active. Every stat
    change — a counter's grant, an attachment's bonus, an ability's effect — is one of these, summed
    on demand to compute a card's effective stat.

    Attributes
    ----------
    source_id : str
        The card the modifier comes from — used to expire ``WHILE_SOURCE_IN_PLAY`` modifiers when it
        leaves play and to attribute the effect.
    target_id : str
        The card whose stat is adjusted.
    stat : Stat
        Which stat is adjusted.
    amount : int
        The bonus (positive) or penalty (negative) added to the stat.
    duration : Duration
        When the modifier stops applying.
    """

    source_id: str
    target_id: str
    stat: Stat
    amount: int
    duration: Duration
