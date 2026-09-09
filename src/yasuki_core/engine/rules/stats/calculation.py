from collections.abc import Iterator

from yasuki_core.engine.players import PlayerId
from yasuki_core.engine.rules.units.membership import attachments_of
from yasuki_core.engine.rules.stats.attachment_grants import granted_stat
from yasuki_core.engine.rules.stats.keyword_grants import effective_keywords
from yasuki_core.engine.rules.modifiers import Duration, Minimum, Modifier, Stat
from yasuki_core.engine.rules.stats.ongoing_grants import grant_applies
from yasuki_core.engine.rules.state import GameState
from yasuki_core.game_pieces import keywords
from yasuki_core.game_pieces.cards import L5RCard
from yasuki_core.game_pieces.counters import counter_from_key
from yasuki_core.game_pieces.prints import SenseiPrint, StrongholdPrint


# What a Sensei grants the Stronghold rather than folding into its printed stats (CR, Sensei: the
# modifiers "are continually applied to the Stronghold's stats" and are "treated like any other
# modifier"). Starting Family Honor is absent: it is a seat scalar read once at setup, not a card
# stat anything reads again.
_SENSEI_GRANTED_STATS = (Stat.GOLD_PRODUCTION, Stat.PROVINCE_STRENGTH)


def _senseis_of(game: GameState, seat: PlayerId) -> Iterator[L5RCard]:
    """The Senseis ``seat`` has in play. A Sensei bows and acts on its own (CR, Sensei), so it is a
    modifier source beside the Stronghold rather than part of it."""
    return (
        card
        for card in game.table.battlefield.cards
        if isinstance(card.printed, SenseiPrint) and card.owner is seat
    )


def active_modifiers(game: GameState, card: L5RCard, stat: Stat) -> Iterator[Modifier]:
    """Every modifier adjusting ``card``'s ``stat`` right now: one from each counter it holds, which
    grants its per-count stat while in play; one from each card attached to it, for the modifier that
    card prints plus whatever its own text grants; one from each Sensei its seat controls, when
    ``card`` is a Stronghold; and the recorded modifiers targeting it, a ``WHILE_SOURCE_IN_PLAY`` one
    only while its source is on the battlefield.

    Everything but the recorded modifiers is read off the board, so a derived grant lasts exactly as
    long as the card granting it stays in play, whenever that card arrived."""
    # A counter's source is the card itself, in play by construction here (this is only reached for
    # an in-play card), so no source-in-play check is needed for the derived modifiers.
    for key, count in card.counters.items():
        per_count = getattr(counter_from_key(key), stat.value, 0)
        if per_count and count:
            yield Modifier(card.id, card.id, stat, per_count * count, Duration.WHILE_SOURCE_IN_PLAY)
    printed_modifier = f"{stat.value}_modifier"
    for attached in attachments_of(game, card):
        amount = getattr(attached, printed_modifier, 0) + granted_stat(game, attached, card, stat)
        if amount:
            yield Modifier(attached.id, card.id, stat, amount, Duration.WHILE_SOURCE_IN_PLAY)
    # Kensai raises the limit rather than exempting him from it: Two-Handed still binds a
    # Kensai, and that rule is checked separately.
    if stat is Stat.WEAPON_LIMIT and keywords.KENSAI in effective_keywords(game, card):
        yield Modifier(card.id, card.id, stat, 1, Duration.WHILE_SOURCE_IN_PLAY)
    if stat in _SENSEI_GRANTED_STATS and isinstance(card.printed, StrongholdPrint):
        for sensei in _senseis_of(game, card.owner):
            delta = getattr(sensei, stat.value)
            if delta:
                yield Modifier(sensei.id, card.id, stat, delta, Duration.WHILE_SOURCE_IN_PLAY)
    for modifier in game.ongoing:
        if not isinstance(modifier, Modifier) or modifier.target_id != card.id:
            continue
        if modifier.stat is not stat or not grant_applies(game, modifier):
            continue
        yield modifier


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


def effective_stat(game: GameState, card: L5RCard, stat: Stat) -> int:
    """``card``'s ``stat`` right now: its printed value plus every active modifier on it, floored at
    zero or at whatever higher minimum a card has given it.

    The order is the CR's (Calculating Stats): modifiers sum first and the minimum applies to the
    total, so a 2F card penalised -3F and then given +2F reads 1 rather than 2. A stat absent from
    the card type, and one printed as a dash, both read zero and take no modifiers at all (CR,
    Absent Stats).

    Parameters
    ----------
    game : GameState
        The live game the modifiers are read from.
    card : L5RCard
        The card being read.
    stat : Stat
        Which stat to total.

    Returns
    -------
    value : int
        The modified stat.
    """
    base = getattr(card, stat.value, None)
    if base is None:
        return 0
    total = base + sum(modifier.amount for modifier in active_modifiers(game, card, stat))
    return max(stat_minimum(game, card, stat), total)
