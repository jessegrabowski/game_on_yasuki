from collections.abc import Callable, Iterator
from dataclasses import dataclass

from yasuki_core import ruleset
from yasuki_core.engine.players import PlayerId
from yasuki_core.engine.rules.attachments import attachments_of, granted_stat
from yasuki_core.engine.rules.modifiers import (
    Duration,
    KeywordGrant,
    Modifier,
    OngoingEffect,
    Stat,
)
from yasuki_core.engine.rules.state import GameState
from yasuki_core.game_pieces import keywords
from yasuki_core.game_pieces.cards import L5RCard
from yasuki_core.game_pieces.counters import counter_from_key
from yasuki_core.game_pieces.prints import HoldingPrint, SenseiPrint, StrongholdPrint


@dataclass(frozen=True, slots=True)
class PlayerState:
    """A read-only view of one seat — the vocabulary a card effect reasons over: the seat's
    stronghold, the cards it controls in play, and its current gold and honor."""

    seat: PlayerId
    stronghold: L5RCard | None
    in_play: tuple[L5RCard, ...]
    gold: int
    honor: int
    went_second: bool

    @property
    def holdings(self) -> tuple[L5RCard, ...]:
        """The Holdings the seat controls in play."""
        return tuple(card for card in self.in_play if isinstance(card.printed, HoldingPrint))

    def controls(self, keyword: str, *, other_than: L5RCard | None = None) -> bool:
        """Whether the seat controls an in-play card carrying ``keyword``, optionally excluding one
        card so an "another"/"other" clause can skip the card asking.

        Parameters
        ----------
        keyword : str
            The keyword to look for among controlled cards.
        other_than : L5RCard, optional
            A card to exclude from the search (matched by identity). Default None.
        """
        return any(keyword in card.keywords and card is not other_than for card in self.in_play)


def player_state(game: GameState, seat: PlayerId) -> PlayerState:
    """Build the read-only :class:`PlayerState` view for ``seat`` from the live game."""
    in_play = tuple(card for card in game.table.battlefield.cards if card.owner is seat)
    stronghold = next((card for card in in_play if isinstance(card.printed, StrongholdPrint)), None)
    return PlayerState(
        seat=seat,
        stronghold=stronghold,
        in_play=in_play,
        gold=game.gold[seat],
        honor=game.table.seats[seat].honor,
        went_second=seat is not game.first_player,
    )


def opposing_states(game: GameState, seat: PlayerId) -> tuple[PlayerState, ...]:
    """The :class:`PlayerState` view for every seat other than ``seat``."""
    return tuple(player_state(game, other) for other in game.table.seats if other is not seat)


# A gold-production handler computes what a card produces in context, from the producing card, its
# controller's view, the opponents' views, and the cards being paid for.
GoldHandler = Callable[[L5RCard, PlayerState, tuple[PlayerState, ...], tuple[L5RCard, ...]], int]
GOLD_HANDLERS: dict[str, GoldHandler] = {}


def gold_handler(printed_id: str) -> Callable[[GoldHandler], GoldHandler]:
    """Register the decorated function as the gold-production handler for ``printed_id``."""

    def register(handler: GoldHandler) -> GoldHandler:
        # Assignment would let the second registration shadow the first with no trace; by the time
        # anything inspects the registry only the survivor is there.
        if printed_id in GOLD_HANDLERS:
            raise ValueError(f"{printed_id} already has a gold handler")
        GOLD_HANDLERS[printed_id] = handler
        return handler

    return register


def _on_battlefield(game: GameState, card_id: str) -> bool:
    return any(card.id == card_id for card in game.table.battlefield.cards)


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
    for modifier in game.modifiers:
        if not isinstance(modifier, Modifier) or modifier.target_id != card.id:
            continue
        if modifier.stat is not stat or not _grant_applies(game, modifier):
            continue
        yield modifier


def _grant_applies(game: GameState, recorded: OngoingEffect) -> bool:
    """Whether a recorded ongoing effect is in force — a ``WHILE_SOURCE_IN_PLAY`` one only while
    the card it came from is still on the battlefield."""
    return recorded.duration is not Duration.WHILE_SOURCE_IN_PLAY or _on_battlefield(
        game, recorded.source_id
    )


def granted_keywords(game: GameState, card: L5RCard) -> Iterator[str]:
    """Every keyword another card's recorded grant gives ``card`` right now."""
    for grant in game.modifiers:
        if isinstance(grant, KeywordGrant) and grant.target_id == card.id:
            if _grant_applies(game, grant):
                yield grant.keyword


def effective_stat(game: GameState, card: L5RCard, stat: Stat) -> int:
    """``card``'s ``stat`` right now: its printed value plus every active modifier on it, floored at
    zero.

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
    return max(0, base + sum(modifier.amount for modifier in active_modifiers(game, card, stat)))


def effective_force(game: GameState, card: L5RCard) -> int:
    """``card``'s Force right now, counters and granted modifiers included."""
    return effective_stat(game, card, Stat.FORCE)


def effective_chi(game: GameState, card: L5RCard) -> int:
    """``card``'s Chi right now, counters and granted modifiers included. Zero is a meaningful
    answer for a Personality rather than merely a floor: the Chi Death Rule destroys one whose Chi
    is ever zero."""
    return effective_stat(game, card, Stat.CHI)


def effective_personal_honor(game: GameState, card: L5RCard) -> int:
    """``card``'s Personal Honor right now — what Proclaiming him gains, and what an effect reading
    his honor sees. The +1PH and +2PH counters carry their delta here."""
    return effective_stat(game, card, Stat.PERSONAL_HONOR)


def effective_weapon_limit(game: GameState, card: L5RCard) -> int:
    """How many Weapon Items may be attached to ``card`` (CR, Weapon). One by default, two for a
    Kensai, and whatever a card's own modifiers make it."""
    return effective_stat(game, card, Stat.WEAPON_LIMIT)


def effective_gold_cost(game: GameState, card: L5RCard) -> int:
    """What ``card`` costs before the seat's own discounts and surcharges: its printed gold cost plus
    every active Gold Cost modifier on it, floored at zero. A card printing no gold cost has none to
    modify, so it stays at zero (CR, Absent Stats).

    Parameters
    ----------
    game : GameState
        The live game the modifiers are read from.
    card : L5RCard
        The card being priced.

    Returns
    -------
    cost : int
        The modified gold cost.
    """
    return effective_stat(game, card, Stat.GOLD_COST)


def effective_gold_production(
    game: GameState, card: L5RCard, targets: tuple[L5RCard, ...] = ()
) -> int:
    """The gold ``card`` produces right now: its registered handler's result against the live views,
    or its printed ``gold_production`` when no handler is registered, plus every active Gold
    Production modifier on it (wealth counters, ability grants), floored at zero. A card with no
    Gold Production stat produces 0 and receives no modifiers (the stat is absent).

    Parameters
    ----------
    game : GameState
        The live game the views project from.
    card : L5RCard
        The producing card.
    targets : tuple of L5RCard, optional
        The cards being paid for, for a handler whose yield depends on what it pays for. Default
        empty.
    """
    handler = GOLD_HANDLERS.get(card.printed_id)
    if handler is None:
        if not hasattr(card, "gold_production"):
            return 0  # an absent stat cannot receive modifiers (CR, Absent Stats)
        base = card.gold_production
    else:
        base = handler(
            card, player_state(game, card.owner), opposing_states(game, card.owner), targets
        )
    total = base + sum(
        modifier.amount for modifier in active_modifiers(game, card, Stat.GOLD_PRODUCTION)
    )
    return max(0, total)


# A recruit-discount handler computes the gold reduction on recruiting a card, from the card being
# recruited and its controller's and opponents' views. It reduces the card's own cost — the "enters
# play for N less Gold" holdings, gated on a readable condition.
DiscountHandler = Callable[[L5RCard, PlayerState, tuple[PlayerState, ...]], int]
RECRUIT_DISCOUNTS: dict[str, DiscountHandler] = {}


def recruit_discount(printed_id: str) -> Callable[[DiscountHandler], DiscountHandler]:
    """Register the decorated function as the recruit-discount handler for ``printed_id``."""

    def register(handler: DiscountHandler) -> DiscountHandler:
        if printed_id in RECRUIT_DISCOUNTS:
            raise ValueError(f"{printed_id} already has a recruit discount")
        RECRUIT_DISCOUNTS[printed_id] = handler
        return handler

    return register


def effective_recruit_discount(game: GameState, card: L5RCard) -> int:
    """The gold ``card`` costs less to recruit from its own conditional cost-reduction ability, or 0
    when it has none."""
    handler = RECRUIT_DISCOUNTS.get(card.printed_id)
    if handler is None:
        return 0
    return handler(card, player_state(game, card.owner), opposing_states(game, card.owner))


# The same shape one step along: a reduction on a card's Invest rather than on its Gold Cost, for
# the "Invest :g2:, or :g0: if ..." a card prints.
INVEST_DISCOUNTS: dict[str, DiscountHandler] = {}


def invest_discount(printed_id: str) -> Callable[[DiscountHandler], DiscountHandler]:
    """Register the decorated function as the Invest-discount handler for ``printed_id``."""

    def register(handler: DiscountHandler) -> DiscountHandler:
        if printed_id in INVEST_DISCOUNTS:
            raise ValueError(f"{printed_id} already has an invest discount")
        INVEST_DISCOUNTS[printed_id] = handler
        return handler

    return register


def effective_invest_discount(game: GameState, card: L5RCard) -> int:
    """The gold ``card``'s Invest costs less from its own conditional reduction, or 0 with none."""
    handler = INVEST_DISCOUNTS.get(card.printed_id)
    if handler is None:
        return 0
    return handler(card, player_state(game, card.owner), opposing_states(game, card.owner))


# A keyword handler names the keywords a card carries beyond the printed ones, from the card and its
# controller's and opponents' views — the "this card has X" clauses gated on a readable condition.
KeywordHandler = Callable[[L5RCard, PlayerState, tuple[PlayerState, ...]], tuple[str, ...]]
KEYWORD_GRANTS: dict[str, KeywordHandler] = {}


def keyword_grant(printed_id: str) -> Callable[[KeywordHandler], KeywordHandler]:
    """Register the decorated function as the keyword-grant handler for ``printed_id``."""

    def register(handler: KeywordHandler) -> KeywordHandler:
        if printed_id in KEYWORD_GRANTS:
            raise ValueError(f"{printed_id} already has a keyword grant")
        KEYWORD_GRANTS[printed_id] = handler
        return handler

    return register


def effective_keywords(game: GameState, card: L5RCard) -> frozenset[str]:
    """``card``'s printed keywords, plus any its own ability grants under current conditions, plus
    any another card's ongoing effect has given it."""
    carried = frozenset(card.keywords).union(granted_keywords(game, card))
    handler = KEYWORD_GRANTS.get(card.printed_id)
    if handler is None:
        return carried
    granted = handler(card, player_state(game, card.owner), opposing_states(game, card.owner))
    return carried.union(granted)


def is_clan(me: PlayerState, clan: str) -> bool:
    """Whether ``me`` is playing ``clan``, read from the stronghold.

    Compared as Clan Alignments rather than as strings: a stronghold printed "Lion Clan" answers to
    Lion, and the arc's equal alignments answer to each other (a Naga stronghold is an Akasha
    player). A clan that is no alignment in this arc matches nothing, including itself. A stronghold
    printing several clans plays them all.
    """
    if me.stronghold is None:
        return False
    alignment = ruleset.ACTIVE.alignment(clan)
    if alignment is None:
        return False
    printed = me.stronghold.clans or ((me.stronghold.clan,) if me.stronghold.clan else ())
    return any(ruleset.ACTIVE.alignment(name) == alignment for name in printed)
