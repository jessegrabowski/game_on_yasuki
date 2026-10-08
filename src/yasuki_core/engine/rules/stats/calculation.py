from collections.abc import Iterator, Sequence
from dataclasses import replace

from yasuki_core.engine.players import PlayerId
from yasuki_core.engine.rules.units.membership import attachments_of
from yasuki_core.engine.rules.stats.keyword_grants import effective_keywords
from yasuki_core.engine.rules.vocabulary.modifiers import (
    AttachedChange,
    ChangeIdentity,
    ConditionalModifier,
    Duration,
    Minimum,
    Modifier,
    RecordedChange,
    Stat,
    StatChangeNegation,
    TextChange,
    TokenChange,
)
from yasuki_core.engine.rules.stats.conditions import condition_holds
from yasuki_core.engine.rules.stats.ongoing_grants import grant_applies
from yasuki_core.engine.rules.stats.stat_grants import granted_stats, stat_granters
from yasuki_core.engine.rules.state import GameState
from yasuki_core.engine.rules.vocabulary import keywords
from yasuki_core.game_pieces.cards import L5RCard
from yasuki_core.game_pieces.constants import AttachmentType
from yasuki_core.game_pieces.counters import counter_from_key
from yasuki_core.game_pieces.prints import AttachmentPrint, SenseiPrint, StrongholdPrint


# What a Sensei grants the Stronghold rather than folding into its printed stats (CR, Sensei: the
# modifiers "are continually applied to the Stronghold's stats" and are "treated like any other
# modifier"). Starting Family Honor is absent: it is a seat scalar read once at setup, not a card
# stat anything reads again.
_SENSEI_GRANTED_STATS = (Stat.GOLD_PRODUCTION, Stat.PROVINCE_STRENGTH)

_ALL_STATS = tuple(Stat)
# The stats an attachment other than a Follower prints as modifiers to its Personality.
_LENT_STATS = (Stat.FORCE, Stat.CHI)


def _senseis_of(game: GameState, seat: PlayerId) -> Iterator[L5RCard]:
    """The Senseis ``seat`` has in play. A Sensei bows and acts on its own (CR, Sensei), so it is a
    modifier source beside the Stronghold rather than part of it."""
    return (
        card
        for card in game.table.battlefield.cards
        if isinstance(card.printed, SenseiPrint) and card.owner is seat
    )


def active_modifiers(
    game: GameState,
    card: L5RCard,
    stat: Stat,
    *,
    granters: Sequence[L5RCard] | None = None,
) -> Iterator[Modifier]:
    """Every modifier adjusting ``card``'s ``stat`` right now: one from each counter it holds,
    granting its per-count stat while in play, one from each card attached to it for the modifier
    that card prints, one from each card in play whose text gives it a stat, one from each Sensei
    its seat controls when ``card`` is a Stronghold, the recorded modifiers targeting it, and the
    recorded conditional modifiers whose condition ``card`` meets at this read, a
    ``WHILE_SOURCE_IN_PLAY`` one of either only while its source is on the battlefield.

    Everything but the recorded modifiers is read off the board, so a derived grant lasts exactly as
    long as the card granting it stays in play, whenever that card arrived.

    Parameters
    ----------
    granters : sequence of L5RCard, optional
        The board's :func:`~.stat_granters`, for a caller reading many cards against one board.
        Default None, read off the board here.
    """
    return _modifiers(game, card, (stat,), granters=granters)


def is_modified(
    game: GameState, card: L5RCard, *, granters: Sequence[L5RCard] | None = None
) -> bool:
    """Whether any :func:`active_modifiers` reaches ``card``, over any stat.

    Parameters
    ----------
    granters : sequence of L5RCard, optional
        The board's :func:`~.stat_granters`, for a caller asking of many cards against one board.
        Default None, read off the board here.
    """
    return next(_modifiers(game, card, _ALL_STATS, granters=granters), None) is not None


def _modifiers(
    game: GameState,
    card: L5RCard,
    stats: tuple[Stat, ...],
    *,
    granters: Sequence[L5RCard] | None,
) -> Iterator[Modifier]:
    """The :func:`active_modifiers` of each of ``stats``, reading the board once for all of them,
    less what a :class:`~.StatChangeNegation` on ``card`` negates. For one stat, in the order that
    function lists them."""
    recorded: list[Modifier | ConditionalModifier] = []
    negations: list[StatChangeNegation] = []
    for held in game.ongoing:
        if isinstance(held, Modifier | ConditionalModifier):
            recorded.append(held)
        elif (
            isinstance(held, StatChangeNegation)
            and card.id in held.subjects
            and grant_applies(game, held)
        ):
            negations.append(held)
    changes = _changes(game, card, stats, recorded, granters=granters)
    if not negations:
        yield from (modifier for _, modifier in changes)
        return
    for identity, modifier in changes:
        amount = modifier.amount
        negated = max(negation.negated(modifier.stat, amount, identity) for negation in negations)
        if negated == 0:
            yield modifier
        elif negated != amount:
            yield replace(modifier, amount=amount - negated)


def stat_changes(
    game: GameState, card: L5RCard, stat: Stat, *, granters: Sequence[L5RCard] | None = None
) -> frozenset[ChangeIdentity]:
    """The changes to ``card``'s ``stat`` in force right now that are bonuses or penalties, by
    identity: what a negation of current changes captures as it is laid.

    Parameters
    ----------
    granters : sequence of L5RCard, optional
        The board's :func:`~.stat_granters`, for a caller asking of many cards against one board.
        Default None, read off the board here.
    """
    recorded = [held for held in game.ongoing if isinstance(held, Modifier | ConditionalModifier)]
    return frozenset(
        identity
        for identity, modifier in _changes(game, card, (stat,), recorded, granters=granters)
        if identity is not None and modifier.amount
    )


def _changes(
    game: GameState,
    card: L5RCard,
    stats: tuple[Stat, ...],
    recorded: Sequence[Modifier | ConditionalModifier],
    *,
    granters: Sequence[L5RCard] | None,
) -> Iterator[tuple[ChangeIdentity | None, Modifier]]:
    """Every modifier adjusting ``card``'s ``stats``, each with its identity as a bonus or penalty,
    or None for one that is neither: an Item's printed modifier (CR, Bonuses and Penalties 0.1), a
    Sensei's (0.2), and the second Weapon a Kensai holds, which raises a limit. ``recorded`` is the
    game's recorded modifiers, read once by the caller."""
    granters = stat_granters(game) if granters is None else granters
    # A counter's source is the card itself, in play by construction here (this is only reached for
    # an in-play card), so no source-in-play check is needed for the derived modifiers.
    for key, count in card.counters.items():
        counter = counter_from_key(key) if count else None
        for stat in stats:
            per_count = getattr(counter, stat.value, 0) if counter is not None else 0
            if per_count:
                tokens = Modifier(
                    card.id, card.id, stat, per_count * count, Duration.WHILE_SOURCE_IN_PLAY
                )
                yield TokenChange(card.id, key, count), tokens
    for attached in attachments_of(game, card):
        is_item = attached.attachment_type is AttachmentType.ITEM
        for stat in stats:
            amount = _lent(game, attached, stat, granters)
            if amount:
                identity = None if is_item else AttachedChange(card.id, attached.id)
                printed = Modifier(
                    attached.id, card.id, stat, amount, Duration.WHILE_SOURCE_IN_PLAY
                )
                yield identity, printed
    for stat in stats:
        for granting, clause, amount in granted_stats(game, card, stat, granters=granters):
            granted = Modifier(granting.id, card.id, stat, amount, Duration.WHILE_SOURCE_IN_PLAY)
            yield TextChange(card.id, granting.id, clause), granted
    # Kensai raises the limit rather than exempting him from it: Two-Handed still binds a
    # Kensai, and that rule is checked separately.
    if Stat.WEAPON_LIMIT in stats and keywords.KENSAI in effective_keywords(game, card):
        yield None, Modifier(card.id, card.id, Stat.WEAPON_LIMIT, 1, Duration.WHILE_SOURCE_IN_PLAY)
    sensei_stats = [stat for stat in stats if stat in _SENSEI_GRANTED_STATS]
    if sensei_stats and isinstance(card.printed, StrongholdPrint):
        for sensei in _senseis_of(game, card.owner):
            for stat in sensei_stats:
                delta = getattr(sensei, stat.value)
                if delta:
                    yield (
                        None,
                        Modifier(sensei.id, card.id, stat, delta, Duration.WHILE_SOURCE_IN_PLAY),
                    )
    for held in recorded:
        stat = held.stat
        if stat not in stats or not grant_applies(game, held):
            continue
        if isinstance(held, Modifier):
            if held.target_id == card.id:
                yield RecordedChange(card.id, held.serial), held
        elif condition_holds(game, card, held.condition):
            conditional = Modifier(held.source_id, card.id, stat, held.amount, held.duration)
            yield RecordedChange(card.id, held.serial), conditional


def _lends(card: L5RCard, stat: Stat) -> bool:
    """Whether ``card`` is an attachment other than a Follower and ``stat`` one it prints only as a
    modifier to its Personality."""
    return (
        stat in _LENT_STATS
        and isinstance(card.printed, AttachmentPrint)
        and card.attachment_type is not AttachmentType.FOLLOWER
    )


def _lent(game: GameState, attached: L5RCard, stat: Stat, granters: Sequence[L5RCard]) -> int:
    """What ``attached`` gives its Personality for ``stat``: a Follower's printed modifier, or any
    other attachment's own stat with the changes it carries, its tokens among them (CR, Token)."""
    if not _lends(attached, stat):
        return getattr(attached, f"{stat.value}_modifier", 0)
    return unbounded_stat(game, attached, stat, granters=granters)


def printed_stat(card: L5RCard, stat: Stat) -> int | None:
    """``card``'s printed ``stat``, or None where it prints none. An attachment other than a
    Follower prints its Force and Chi as the modifiers it gives its Personality, so those are its
    Force and Chi."""
    if _lends(card, stat):
        return getattr(card, f"{stat.value}_modifier")
    return getattr(card, stat.value, None)


def stat_minimum(game: GameState, card: L5RCard, stat: Stat) -> int:
    """The lowest ``card``'s ``stat`` may read: zero, or the most restrictive minimum a card has
    given it (CR, Minimums and Maximums)."""
    return max(
        (
            recorded.value
            for recorded in game.ongoing
            if isinstance(recorded, Minimum)
            and recorded.target_id == card.id
            and recorded.stat is stat
            and grant_applies(game, recorded)
        ),
        default=0,
    )


def stat_maximum(game: GameState, card: L5RCard, stat: Stat) -> int | None:
    """The highest ``card``'s ``stat`` may read, or None where nothing caps it. The rulebook's one
    maximum is a dishonorable Personality's Personal Honor of 0 (CR, Honorable and Dishonorable)."""
    if stat is Stat.PERSONAL_HONOR and card.dishonorable:
        return 0
    return None


def unbounded_stat(
    game: GameState,
    card: L5RCard,
    stat: Stat,
    *,
    granters: Sequence[L5RCard] | None = None,
) -> int:
    """``card``'s ``stat`` as its printed value plus every active modifier, before any minimum or
    maximum applies. Setting a stat measures from this (CR, Setting Stats to Values). An absent or
    dash stat reads zero.

    Parameters
    ----------
    granters : sequence of L5RCard, optional
        The board's :func:`~.stat_granters`, for a caller reading many cards against one board.
        Default None, read off the board here.
    """
    base = printed_stat(card, stat)
    if base is None:
        return 0
    modifiers = active_modifiers(game, card, stat, granters=granters)
    return base + sum(modifier.amount for modifier in modifiers)


def effective_stat(
    game: GameState,
    card: L5RCard,
    stat: Stat,
    *,
    granters: Sequence[L5RCard] | None = None,
) -> int:
    """``card``'s ``stat`` right now: its printed value plus every active modifier on it, floored at
    zero or at whatever higher minimum a card has given it, and capped at whatever maximum applies.

    The order is the CR's (Calculating Stats): modifiers sum first and the minimum and maximum apply
    to the total, so a 2F card penalised -3F and then given +2F reads 1 rather than 2. A minimum
    above the maximum cancels both, leaving only the basic floor of zero (CR, Minimums and
    Maximums). A stat absent from the card type, and one printed as a dash, both read zero and take
    no modifiers at all (CR, Absent Stats).

    Parameters
    ----------
    game : GameState
        The live game the modifiers are read from.
    card : L5RCard
        The card being read.
    stat : Stat
        Which stat to total.
    granters : sequence of L5RCard, optional
        The board's :func:`~.stat_granters`, for a caller reading many cards against one board.
        Default None, read off the board here.

    Returns
    -------
    value : int
        The modified stat.
    """
    if printed_stat(card, stat) is None:
        return 0
    total = unbounded_stat(game, card, stat, granters=granters)
    floor = stat_minimum(game, card, stat)
    cap = stat_maximum(game, card, stat)
    if cap is None:
        return max(floor, total)
    if floor > cap:
        return max(0, total)
    return max(floor, min(cap, total))
