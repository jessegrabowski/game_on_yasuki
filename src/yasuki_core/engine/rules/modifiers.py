from dataclasses import dataclass
from enum import Enum

from yasuki_core.engine.players import PlayerId
from yasuki_core.engine.table import ZoneKey


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


@dataclass(frozen=True, slots=True)
class KeywordGrant:
    """A continuous effect that gives one card a keyword while active.

    Attributes
    ----------
    source_id : str
        The card the grant comes from — used to expire a ``WHILE_SOURCE_IN_PLAY`` grant when it
        leaves play and to attribute the effect.
    target_id : str
        The card that carries the keyword while the grant lasts.
    keyword : str
        The keyword gained, spelled as the card database spells it.
    duration : Duration
        When the grant stops applying.
    """

    source_id: str
    target_id: str
    keyword: str
    duration: Duration


@dataclass(frozen=True, slots=True)
class Minimum:
    """A continuous effect that floors one card's stat while active — "a target Personality has a
    minimum Chi of 1" (CR, Minimums and Maximums).

    A minimum is applied on top of the bonuses and penalties rather than among them: the stat totals
    first, and only then is raised to meet the floor (CR, Calculating Stats). Where several apply to
    the same stat, the most restrictive wins. Every stat already floors at zero, so one of these
    raises a floor that is always there rather than introducing one.

    Attributes
    ----------
    source_id : str
        The card the minimum comes from — used to expire a ``WHILE_SOURCE_IN_PLAY`` minimum when it
        leaves play and to attribute the effect.
    target_id : str
        The card whose stat is floored.
    stat : Stat
        Which stat the floor applies to.
    value : int
        The lowest the stat may read while this is active.
    duration : Duration
        When the minimum stops applying.
    """

    source_id: str
    target_id: str
    stat: Stat
    value: int
    duration: Duration


@dataclass(frozen=True, slots=True)
class ProvinceModifier:
    """A continuous effect that adjusts one Province's strength while active.

    A Province is a slot rather than a card, so it cannot be the target of a :class:`Modifier`; a
    card that strengthens one for the turn records this instead.

    Attributes
    ----------
    source_id : str
        The card the modifier comes from — used to expire a ``WHILE_SOURCE_IN_PLAY`` one when it
        leaves play and to attribute the effect.
    province : ZoneKey
        The Province slot whose strength is adjusted.
    amount : int
        The bonus (positive) or penalty (negative) added to the strength.
    duration : Duration
        When the modifier stops applying.
    """

    source_id: str
    province: ZoneKey
    amount: int
    duration: Duration


@dataclass(frozen=True, slots=True)
class LobbyModifier:
    """A continuous effect that adjusts one player's Lobby Bonus while active.

    A Lobby Bonus or Penalty rests on a player rather than on a card, so it cannot be a
    :class:`Modifier`. Every amount a Lobby action checks about that player reads higher or lower by
    it, whoever is taking the action; where the amount is Family Honor the adjustment is neither an
    Honor gain nor an Honor loss (ShE datasheet, Lobby Bonuses and Penalties).

    Attributes
    ----------
    source_id : str
        The card the bonus comes from — used to expire a ``WHILE_SOURCE_IN_PLAY`` one when it leaves
        play and to attribute the effect.
    seat : PlayerId
        The player whose Lobby amounts are adjusted.
    amount : int
        The Bonus (positive) or Penalty (negative).
    duration : Duration
        When the adjustment stops applying.
    """

    source_id: str
    seat: PlayerId
    amount: int
    duration: Duration


# A recorded ongoing effect, whichever kind. The CR files a keyword change, a stat's floor and a
# Province's strength beside a stat change — each is ongoing, and each lasts to the end of the turn
# unless the card says otherwise — so they are recorded in one list and expire together (CR,
# Duration of Effects). The three that name a card are forgotten when it leaves the table; the two
# that name a Province slot and a player are not, because neither ever leaves it.
OngoingEffect = Modifier | KeywordGrant | Minimum | ProvinceModifier | LobbyModifier
