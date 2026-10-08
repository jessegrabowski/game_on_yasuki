from collections.abc import Callable, Mapping
from dataclasses import dataclass, field, replace
from enum import Enum
from typing import Self

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
    UNTIL_ACTION_RESOLVES
        Lasts while the action now resolving resolves, including the cards it brings into play
        entering, and lapses as that action is announced resolved, whatever became of its source.
    """

    UNTIL_END_OF_TURN = "until_end_of_turn"
    WHILE_SOURCE_IN_PLAY = "while_source_in_play"
    PERMANENT = "permanent"
    UNTIL_ACTION_RESOLVES = "until_action_resolves"


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
    serial : int, optional
        Which record this is, numbered as records are made, so two records giving the same change
        stay two changes. Not compared, since it names the record rather than the change. Default
        0, for a modifier read off the board rather than recorded.
    """

    source_id: str
    target_id: str
    stat: Stat
    amount: int
    duration: Lifetime
    serial: int = field(default=0, compare=False)


class Condition(Enum):
    """What a :class:`~.ConditionalModifier` asks of a card each time the stat is read.

    ATTACKING
        A Personality standing in the attacking army at the battle now being fought.
    DEFENDING
        A Personality standing in the defending army at the battle now being fought.
    """

    ATTACKING = "attacking"
    DEFENDING = "defending"


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
    serial : int, optional
        Which record this is, as on a :class:`~.Modifier`. Default 0.
    """

    source_id: str
    condition: Condition
    stat: Stat
    amount: int
    duration: Lifetime
    serial: int = field(default=0, compare=False)


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
class AdditionalUse:
    """A continuous effect that lets each printed ability of one card be used one additional time
    while active: "You may use its printed abilities one additional time".

    Attributes
    ----------
    source_id : str
        The card the grant comes from.
    target_id : str
        The card whose printed abilities may be used again.
    duration : Duration or Moment
        When the grant stops applying.
    """

    source_id: str
    target_id: str
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
class EnlightenmentExclusion:
    """A continuous effect under which one card does not count towards an Enlightenment Victory,
    as "while it remains in play, it does not count towards an Enlightenment Victory" has it.

    Attributes
    ----------
    source_id : str
        The card the exclusion comes from, used to attribute the effect.
    target_id : str
        The card that does not count while the exclusion lasts.
    duration : Duration or Moment
        When the exclusion stops applying.
    """

    source_id: str
    target_id: str
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
class DuelStatOverride:
    """A continuous effect that changes which stat one Personality's duels compare (CR, Duel Stat).

    A duel compares the arc's duel stat unless a card names another, and it names it per Personality
    rather than per duel: Hida Ryusei's Berserkers duel on Force while the Personality opposing them
    duels on Chi. The stat named here replaces the arc's default for this card, and the modifiers on
    that stat still apply to it.

    Attributes
    ----------
    source_id : str
        The card the override comes from, used to expire a ``WHILE_SOURCE_IN_PLAY`` override when it
        leaves play and to attribute the effect.
    target_id : str
        The Personality whose duels compare the named stat.
    stat : Stat
        The stat its duels compare.
    duration : Duration
        When the override stops applying.
    """

    source_id: str
    target_id: str
    stat: Stat
    duration: Duration


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
class CompassionGrant:
    """A continuous effect that has ``seat`` treated as having Compassion beyond the Province count
    that gives it (ShE datasheet, Traits), as Shrine of Compassion grants it.

    Attributes
    ----------
    source_id : str
        The card the grant comes from, used to attribute and to end it.
    seat : PlayerId
        The player treated as having Compassion.
    duration : Duration or Moment
        When the grant stops applying.
    card_id : str, optional
        The card whose effects, from it or upon it, are treated as if ``seat`` has Compassion. A
        grant naming one is forgotten when that card leaves the table. Default None, for a grant
        covering every effect while it stands.
    """

    source_id: str
    seat: PlayerId
    duration: Lifetime
    card_id: str | None = None


@dataclass(frozen=True, slots=True)
class Negation:
    """A continuous effect that negates the effects matching it while active (CR, Prevention), as
    "negate the effects of actions from Strategies until the end of the phase" or "negate its
    bowing (this turn)" has it. A criterion left None matches anything.

    Every negation is read as each effect commits. One naming a source negates the effects of
    actions from matching cards, including what such an action defers or a question in it
    produces. One naming none negates every matching effect, whatever produced it. Neither reads a
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
        The card the negated effects act on, as each effect's ``subject_id`` declares it. A
        negation naming one is forgotten when that card leaves the table (CR, Card Memory Rule).
        Default None.
    once : bool, optional
        Whether the negation is spent by its first use: by the first effect it negates, as "his
        next straightening" is, or, for one naming only a source, by the first action from a
        matching card, all of whose effects it negates. Default False.
    """

    source_id: str
    duration: Lifetime
    source_kind: type | None = None
    source_title: str | None = None
    effect_kind: type | None = None
    subject_id: str | None = None
    once: bool = False

    def __post_init__(self) -> None:
        """Raise ValueError for a negation naming nothing it negates."""
        if not self.names_a_source and self.effect_kind is None and self.subject_id is None:
            raise ValueError("a negation names what it negates")

    @property
    def names_a_source(self) -> bool:
        """Whether the negation is about whose action an effect comes from."""
        return self.source_kind is not None or self.source_title is not None


class StatChanges(Enum):
    """Which of a stat's changes a :class:`~.StatChangeNegation` prevents: its bonuses, its
    penalties, or both (CR, Bonuses and Penalties)."""

    BONUSES = "bonuses"
    PENALTIES = "penalties"
    BOTH = "both"

    def covers(self, amount: int) -> bool:
        """Whether a change of ``amount`` is one of these. A change of 0 is neither (CR, Bonuses
        and Penalties 0.7)."""
        if amount > 0:
            return self is not StatChanges.PENALTIES
        if amount < 0:
            return self is not StatChanges.BONUSES
        return False


@dataclass(frozen=True, slots=True)
class RecordedChange:
    """A recorded modifier's change to one card, told apart by the record's serial."""

    card_id: str
    serial: int


@dataclass(frozen=True, slots=True)
class TextChange:
    """What one clause of a card's text gives one card, as "Commanders have +1F" is one clause of
    Lonely Battlefield's.

    Attributes
    ----------
    card_id : str
        The card given the change.
    source_id : str
        The card whose text gives it.
    clause : int
        Which of the text's clauses, counting from zero in print order.
    """

    card_id: str
    source_id: str
    clause: int


@dataclass(frozen=True, slots=True)
class AttachedChange:
    """The modifier an attached card other than an Item prints, given to the Personality it is
    attached to."""

    card_id: str
    attachment_id: str


@dataclass(frozen=True, slots=True)
class TokenChange:
    """The tokens of one kind on one card. Tokens of a kind are alike, so they are told apart by
    how many there are: a negation holding ``count`` of them negates that many."""

    card_id: str
    key: str
    count: int


# What a stat change is told apart by while it lasts. Each names the card it changes. A change that
# is no bonus or penalty, as an Item's or a Sensei's printed modifier, has none.
ChangeIdentity = RecordedChange | TextChange | AttachedChange | TokenChange


@dataclass(frozen=True, slots=True)
class StatChangeNegation:
    """A prevention of stat changes (CR, Prevention): the bonuses, the penalties or both to ``stat``
    on ``subjects`` stop applying while it lasts. A prevention of an ongoing kind of effect
    "only suppresses existing effects", so by default only the changes in ``current``, those that
    existed when it was laid, are negated. One reading "current and new" sets ``reaches_new``.

    Attributes
    ----------
    source_id : str
        The card the negation comes from.
    subjects : frozenset of str
        The cards whose changes it negates. A card that leaves the table drops out (CR, Card
        Memory Rule).
    stat : Stat
        The stat whose changes it negates.
    changes : StatChanges
        Which changes it negates.
    duration : Duration or Moment
        When it stops applying.
    current : frozenset of RecordedChange, TextChange, AttachedChange or TokenChange, optional
        The changes on ``subjects`` when it was laid, less those that have since ended. Default
        empty.
    reaches_new : bool, optional
        Whether it negates changes arriving after it too. Default False.
    """

    source_id: str
    subjects: frozenset[str]
    stat: Stat
    changes: StatChanges
    duration: Lifetime
    current: frozenset[ChangeIdentity] = frozenset()
    reaches_new: bool = False

    def negated(self, stat: Stat, amount: int, identity: ChangeIdentity | None) -> int:
        """How much of a change of ``amount`` to ``stat``, known as ``identity``, this negates on
        one of its subjects: all of it, none of it, or for tokens, the part the tokens it holds
        give."""
        if identity is None or stat is not self.stat or not self.changes.covers(amount):
            return 0
        if self.reaches_new:
            return amount
        if not isinstance(identity, TokenChange):
            return amount if identity in self.current else 0
        per_token = amount // identity.count
        return per_token * min(self._tokens_held(identity.card_id, identity.key), identity.count)

    def _tokens_held(self, card_id: str, key: str) -> int:
        return next(
            (
                change.count
                for change in self.current
                if isinstance(change, TokenChange)
                and change.card_id == card_id
                and change.key == key
            ),
            0,
        )

    def narrowed(self, on_table: set[str], counters: Callable[[str], Mapping[str, int]]) -> Self:
        """This negation less what has ended: the subjects and changes of cards off the table, and
        the tokens since removed, so one added later is a new change (CR, Card Memory Rule and
        Tokens). ``counters`` maps a card on the table to the tokens it holds."""
        subjects = self.subjects & on_table
        current = frozenset(
            remaining
            for change in self.current
            if change.card_id in on_table
            and (remaining := _remaining(change, counters(change.card_id))) is not None
        )
        if subjects == self.subjects and current == self.current:
            return self
        return replace(self, subjects=subjects, current=current)


def _remaining(change: ChangeIdentity, counters: Mapping[str, int]) -> ChangeIdentity | None:
    """``change`` as far as it still stands on a card holding ``counters``: a token change cut to
    the tokens left, or None once none are."""
    if not isinstance(change, TokenChange):
        return change
    left = min(change.count, counters.get(change.key, 0))
    return None if left == 0 else replace(change, count=left)


# A recorded ongoing effect, whichever kind. The CR files a keyword change, a stat's floor and a
# Province's strength beside a stat change. Each is ongoing and lasts to the end of the turn
# unless the card says otherwise. So they are recorded in one list and expire together (CR,
# Duration of Effects). A record naming a card is forgotten when it leaves the table. One naming a
# condition, a Province slot, a player or what an effect matches is not, because none of those is a
# card that can leave it.
Ongoing = (
    Modifier
    | ConditionalModifier
    | AbilityGrant
    | AdditionalUse
    | SeatAbilityGrant
    | DuelStatOverride
    | KeywordGrant
    | EnlightenmentExclusion
    | Minimum
    | ProvinceModifier
    | LobbyModifier
    | CompassionGrant
    | Negation
    | StatChangeNegation
)
