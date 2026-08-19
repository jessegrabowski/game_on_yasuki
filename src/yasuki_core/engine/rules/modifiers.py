from dataclasses import dataclass
from enum import Enum


class Stat(Enum):
    """A card stat a modifier can adjust. Each member's value is the card attribute it reads, so a
    derived source can look it up with ``getattr(card, stat.value)``. More stats join as the rules
    engine grows.

    Province Strength has no effective-read function yet, because nothing asks for it until battle
    exists. Modifiers over it are recorded all the same, by a sensei's grant and by the counters that
    carry a per-count delta.
    """

    CHI = "chi"
    FORCE = "force"
    GOLD_COST = "gold_cost"
    GOLD_PRODUCTION = "gold_production"
    PERSONAL_HONOR = "personal_honor"
    PROVINCE_STRENGTH = "province_strength"
    WEAPON_LIMIT = "weapon_limit"


class Duration(Enum):
    """How long a modifier stays active.

    UNTIL_END_OF_TURN
        The default for action and ability effects; dropped when the turn ends.
    WHILE_SOURCE_IN_PLAY
        Active only while the modifier's source is on the battlefield — counters, attachments, and
        continuous auras.
    PERMANENT
        Outlives its source leaving play. Like every modifier it ends when its *target* leaves the
        table, because a card that leaves play ceases to exist.
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
