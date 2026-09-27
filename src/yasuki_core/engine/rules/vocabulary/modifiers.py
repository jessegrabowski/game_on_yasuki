from dataclasses import dataclass
from enum import Enum

from yasuki_core.engine.players import PlayerId
from yasuki_core.engine.rules.turn.structure import Moment
from yasuki_core.engine.table import ZoneKey


class Stat(Enum):
    """A card stat a modifier can adjust. Each member's value is the card attribute it reads, so a
    derived source can look it up with ``getattr(card, stat.value)``. More stats join as the rules
    engine grows.

    Province Strength has no effective-read function yet, because nothing asks for it until
    battle exists. Modifiers over it are recorded all the same, by a sensei's grant and by the
    counters that carry a per-count delta.
    """

    CHI = "chi"
    FOCUS = "focus"
    FORCE = "force"
    GOLD_COST = "gold_cost"
    GOLD_PRODUCTION = "gold_production"
    PERSONAL_HONOR = "personal_honor"
    PROVINCE_STRENGTH = "province_strength"
    WEAPON_LIMIT = "weapon_limit"


class Duration(Enum):
    """How long a modifier stays active.

    UNTIL_END_OF_TURN
        The default for action and ability effects, dropped when the turn ends.
    WHILE_SOURCE_IN_PLAY
        Active only while the modifier's source (a counter, an attachment, or a continuous aura) is
        on the battlefield.
    PERMANENT
        Outlives its source leaving play. Like every modifier it ends when its *target* leaves the
        table, because a card that leaves play ceases to exist.
    """

    UNTIL_END_OF_TURN = "until_end_of_turn"
    WHILE_SOURCE_IN_PLAY = "while_source_in_play"
    PERMANENT = "permanent"


# How long an ongoing record lasts: a Duration, or a Moment it lapses at the first time the flow
# reaches it, as "until the end of the phase" or "this battle" has it.
Lifetime = Duration | Moment


def describe_lifetime(lifetime: Lifetime) -> str:
    """How long a record lasts, worded for a trace."""
    return lifetime.name if isinstance(lifetime, Duration) else lifetime.describe()


@dataclass(frozen=True, slots=True)
class Modifier:
    """A continuous effect that adjusts one card's stat by a fixed amount while active. Every stat
    change (counter grant, attachment bonus, ability effect) is one of these, summed
    on demand to compute a card's effective stat.

    Attributes
    ----------
    source_id : str
        The card the modifier comes from, used to expire ``WHILE_SOURCE_IN_PLAY`` modifiers when it
        leaves play and to attribute the effect.
    target_id : str
        The card whose stat is adjusted.
    stat : Stat
        Which stat is adjusted.
    amount : int
        The bonus (positive) or penalty (negative) added to the stat.
    duration : Duration or Moment
        When the modifier stops applying.
    """

    source_id: str
    target_id: str
    stat: Stat
    amount: int
    duration: Lifetime


class Condition(Enum):
    """What a :class:`~.ConditionalModifier` asks of a card each time the stat is read.

    ATTACKING
        A Personality standing in the attacking army at the battle now being fought.
    """

    ATTACKING = "attacking"


@dataclass(frozen=True, slots=True)
class ConditionalModifier:
    """A continuous effect that adjusts a stat on every card meeting ``condition`` while active:
    "Personalities have -1F while attacking".

    It names no target. Which cards it reaches is decided on each read, so a card that enters play
    after it was created is reached too, and one that stops meeting the condition stops being
    reached, with nothing to withdraw (CR, Continuous Effects).

    Attributes
    ----------
    source_id : str
        The card the modifier comes from, used to expire a ``WHILE_SOURCE_IN_PLAY`` one when it
        leaves play and to attribute the effect.
    condition : Condition
        What a card has to satisfy, at the moment its stat is read, to be adjusted.
    stat : Stat
        Which stat is adjusted.
    amount : int
        The bonus (positive) or penalty (negative) added to the stat.
    duration : Duration or Moment
        When the modifier stops applying.
    """

    source_id: str
    condition: Condition
    stat: Stat
    amount: int
    duration: Lifetime


@dataclass(frozen=True, slots=True)
class AbilityGrant:
    """A continuous effect that gives one card an activated ability while active: "she has,
    'Battle: Ranged 3'".

    The ability itself is code, registered under the granting card's printed id, and is built
    from ``context`` each time the card's abilities are read, so a grant that depends on what the
    action chose carries that choice here.

    Attributes
    ----------
    source_id : str
        The card the grant comes from, whose registered factory builds the ability, and which
        expires a ``WHILE_SOURCE_IN_PLAY`` grant by leaving play.
    target_id : str
        The card that has the ability while the grant lasts.
    context : tuple of str
        What the granting action settled, handed to the factory: the ids the ability's own
        condition or targets read.
    duration : Duration or Moment
        When the grant stops applying.
    """

    source_id: str
    target_id: str
    context: tuple[str, ...]
    duration: Lifetime


@dataclass(frozen=True, slots=True)
class SeatAbilityGrant:
    """A continuous effect that gives every card one player owns an activated ability while
    active: "the next time you use the rulebook Kharmic ability, you may use it on a non-Kharmic
    card".

    The ability is code, as an :class:`~.AbilityGrant`'s is, built from ``context`` each time a
    card's abilities are read. It rests on the player because the cards it reaches are whichever
    the player holds when it is used, drawn after the grant or not. Ownership is the test, so a
    card the player controls but does not own is not reached.

    Attributes
    ----------
    source_id : str
        The card the grant comes from, whose registered factory builds the ability, and which
        expires a ``WHILE_SOURCE_IN_PLAY`` grant by leaving play.
    seat : PlayerId
        The player whose owned cards have the ability while the grant lasts.
    context : tuple of str
        What the granting action settled, handed to the factory.
    duration : Duration or Moment
        When the grant stops applying.
    """

    source_id: str
    seat: PlayerId
    context: tuple[str, ...]
    duration: Lifetime


@dataclass(frozen=True, slots=True)
class KeywordGrant:
    """A continuous effect that gives one card a keyword while active.

    Attributes
    ----------
    source_id : str
        The card the grant comes from, used to expire a ``WHILE_SOURCE_IN_PLAY`` grant when it
        leaves play and to attribute the effect.
    target_id : str
        The card that carries the keyword while the grant lasts.
    keyword : str
        The keyword gained, spelled as the card database spells it.
    duration : Duration or Moment
        When the grant stops applying.
    """

    source_id: str
    target_id: str
    keyword: str
    duration: Lifetime


@dataclass(frozen=True, slots=True)
class Minimum:
    """A continuous effect that floors one card's stat while active: "a target Personality has a
    minimum Chi of 1" (CR, Minimums and Maximums).

    A minimum is applied on top of the bonuses and penalties rather than among them: the stat totals
    first, and only then is raised to meet the floor (CR, Calculating Stats). Where several apply to
    the same stat, the most restrictive wins. Every stat already floors at zero, so one of these
    raises a floor that is always there rather than introducing one.

    Attributes
    ----------
    source_id : str
        The card the minimum comes from, used to expire a ``WHILE_SOURCE_IN_PLAY`` minimum when it
        leaves play and to attribute the effect.
    target_id : str
        The card whose stat is floored.
    stat : Stat
        Which stat the floor applies to.
    value : int
        The lowest the stat may read while this is active.
    duration : Duration or Moment
        When the minimum stops applying.
    """

    source_id: str
    target_id: str
    stat: Stat
    value: int
    duration: Lifetime


@dataclass(frozen=True, slots=True)
class ProvinceModifier:
    """A continuous effect that adjusts one Province's strength while active.

    A Province is a slot rather than a card, so it cannot be the target of a :class:`~.Modifier`. A
    card that strengthens one for the turn records this instead.

    Attributes
    ----------
    source_id : str
        The card the modifier comes from, used to expire a ``WHILE_SOURCE_IN_PLAY`` one when it
        leaves play and to attribute the effect.
    province : ZoneKey
        The Province slot whose strength is adjusted.
    amount : int
        The bonus (positive) or penalty (negative) added to the strength.
    duration : Duration or Moment
        When the modifier stops applying.
    """

    source_id: str
    province: ZoneKey
    amount: int
    duration: Lifetime


@dataclass(frozen=True, slots=True)
class LobbyModifier:
    """A continuous effect that adjusts one player's Lobby Bonus while active.

    A Lobby Bonus or Penalty rests on a player rather than on a card, so it cannot be a
    :class:`~.Modifier`. Every amount a Lobby action checks about that player reads higher or lower
    by it, whoever is taking the action. Where the amount is Family Honor the adjustment is neither
    an Honor gain nor an Honor loss (ShE datasheet, Lobby Bonuses and Penalties).

    Attributes
    ----------
    source_id : str
        The card the bonus comes from, used to expire a ``WHILE_SOURCE_IN_PLAY`` one when it leaves
        play and to attribute the effect.
    seat : PlayerId
        The player whose Lobby amounts are adjusted.
    amount : int
        The Bonus (positive) or Penalty (negative).
    duration : Duration or Moment
        When the adjustment stops applying.
    """

    source_id: str
    seat: PlayerId
    amount: int
    duration: Lifetime


@dataclass(frozen=True, slots=True)
class Negation:
    """A continuous effect that negates the effects matching it while active (CR, Prevention), as
    "negate the effects of actions from Strategies until the end of the phase" or "negate its
    bowing (this turn)" has it. A criterion left None matches anything.

    One naming a source negates the effects of actions from matching cards, and is read where such
    an action hands over its effects, since only there is it known whose action they are. One
    naming none negates every matching effect as it commits, whatever produced it. Neither reads a
    cost, which is no effect (CR, Effects).

    Attributes
    ----------
    source_id : str
        The card the negation comes from, used to expire a ``WHILE_SOURCE_IN_PLAY`` one when it
        leaves play and to attribute the effect.
    duration : Duration or Moment
        When the negation stops applying.
    source_kind : type, optional
        The print class, such as ``ActionPrint`` for a Strategy, of the card whose actions' effects
        are negated. Default None.
    source_title : str, optional
        The title of that card. Default None.
    effect_kind : type, optional
        The effect class negated, such as ``Bow`` for "bowing". Default None.
    subject_id : str, optional
        The card the negated effects act on, read off their ``card_id``. A negation naming one is
        forgotten when that card leaves the table (CR, Card Memory Rule). Default None.
    once : bool, optional
        Whether the negation is spent by the first effect it negates, as "his next straightening"
        is. Only one naming no source may be spent this way. Default False.
    """

    source_id: str
    duration: Lifetime
    source_kind: type | None = None
    source_title: str | None = None
    effect_kind: type | None = None
    subject_id: str | None = None
    once: bool = False

    def __post_init__(self) -> None:
        """Raise ValueError for a negation naming nothing it negates, or one naming a source that
        is spent by its first use."""
        if not self.names_a_source and self.effect_kind is None and self.subject_id is None:
            raise ValueError("a negation names what it negates")
        if self.names_a_source and self.once:
            raise ValueError("only a negation naming no source is spent by its first use")

    @property
    def names_a_source(self) -> bool:
        """Whether the negation is about whose action an effect comes from."""
        return self.source_kind is not None or self.source_title is not None


# A recorded ongoing effect, whichever kind. The CR files a keyword change, a stat's floor and a
# Province's strength beside a stat change. Each is ongoing and lasts to the end of the turn
# unless the card says otherwise. So they are recorded in one list and expire together (CR,
# Duration of Effects). The four that name a card are forgotten when it leaves the table; the
# five that name a condition, a Province slot, a player or what an effect matches are not, because
# none of those is a card that can leave it.
Ongoing = (
    Modifier
    | ConditionalModifier
    | AbilityGrant
    | SeatAbilityGrant
    | KeywordGrant
    | Minimum
    | ProvinceModifier
    | LobbyModifier
    | Negation
)
