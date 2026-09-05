from collections.abc import Callable, Iterator
from dataclasses import dataclass

from yasuki_core import ruleset
from yasuki_core.engine.players import PlayerId
from yasuki_core.engine.rules.attachments import attachments_of, granted_stat
from yasuki_core.engine.rules.modifiers import (
    Duration,
    KeywordGrant,
    LobbyModifier,
    Minimum,
    Modifier,
    ProvinceModifier,
    OngoingEffect,
    Stat,
)
from yasuki_core.engine.rules.state import GameState, used_this_turn
from yasuki_core.engine.table import ZoneKey, unit_members
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


def stat_minimum(game: GameState, card: L5RCard, stat: Stat) -> int:
    """The lowest ``card``'s ``stat`` may read: zero, or the most restrictive minimum a card has
    given it (CR, Minimums and Maximums)."""
    return max(
        (
            recorded.value
            for recorded in game.modifiers
            if isinstance(recorded, Minimum)
            and recorded.target_id == card.id
            and recorded.stat is stat
            and _grant_applies(game, recorded)
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


# What a card attached to a Province gives it, beyond anything it prints. Makeshift Fortifications
# reads "This Province has +3PS"; a Fortification carries no Province Strength stat of its own, so
# the grant is text rather than a number on the print. Keyed by printed id like the other registries.
ProvinceGrant = Callable[[GameState, L5RCard, ZoneKey], int]
PROVINCE_STRENGTH_GRANTS: dict[str, ProvinceGrant] = {}


def province_strength_grant(printed_id: str) -> Callable[[ProvinceGrant], ProvinceGrant]:
    """Register the decorated function as ``printed_id``'s Province Strength grant."""

    def register(grant: ProvinceGrant) -> ProvinceGrant:
        if printed_id in PROVINCE_STRENGTH_GRANTS:
            raise ValueError(f"{printed_id} already grants Province Strength")
        PROVINCE_STRENGTH_GRANTS[printed_id] = grant
        return grant

    return register


# What a card in play gives its controller's Lobby amounts, beyond anything it prints. Shigekawa's
# Court reads "You have a +5 Lobby Bonus"; there is no stat for it, so the grant is text. Keyed by
# printed id like the other registries.
LobbyGrant = Callable[[GameState, L5RCard], int]
LOBBY_BONUSES: dict[str, LobbyGrant] = {}


def lobby_bonus_grant(printed_id: str) -> Callable[[LobbyGrant], LobbyGrant]:
    """Register the decorated function as ``printed_id``'s Lobby Bonus grant."""

    def register(grant: LobbyGrant) -> LobbyGrant:
        if printed_id in LOBBY_BONUSES:
            raise ValueError(f"{printed_id} already grants a Lobby Bonus")
        LOBBY_BONUSES[printed_id] = grant
        return grant

    return register


def lobby_bonus(game: GameState, seat: PlayerId) -> int:
    """``seat``'s Lobby Bonus right now: its Penalties are the negative part of the same sum.

    Read wherever a Lobby action checks an amount about a player, whether that player is the one
    acting or one being compared against, because the datasheet applies the adjustment to the player
    the amount is about rather than to the player taking the action (ShE datasheet, Lobby Bonuses
    and Penalties).
    """
    total = 0
    for card in game.table.battlefield.cards:
        if card.owner is not seat:
            continue
        grant = LOBBY_BONUSES.get(card.printed_id)
        if grant is not None:
            total += grant(game, card)
    total += sum(
        recorded.amount
        for recorded in game.modifiers
        if isinstance(recorded, LobbyModifier)
        and recorded.seat is seat
        and _grant_applies(game, recorded)
    )
    return total


def lobby_amount(game: GameState, seat: PlayerId, amount: int) -> int:
    """``amount``, about ``seat``, as a Lobby action reads it — its Lobby Bonus included.

    Any amount is adjusted, not only Family Honor: the rulebook Lobby checks Family Honor, but each
    Wind's own Lobby checks something else — cards in hand, the total Gold Cost of attachments
    controlled, the total Force of unbowed Followers and Personalities — and the Bonus applies to
    whichever it is (ShE datasheet, Lobby Bonuses and Penalties).

    Where the amount is Family Honor the adjustment is neither an Honor gain nor an Honor loss, so
    it is applied to the amount being compared and never written back to the seat.
    """
    return amount + lobby_bonus(game, seat)


def effective_province_strength(game: GameState, province: ZoneKey) -> int:
    """How strong ``province`` is right now, floored at zero.

    Four sources, summed: the owning seat's Stronghold prints the strength every one of its
    Provinces starts at — a stat of a Stronghold *or* of a Province (CR, Province Strength) — then
    the counters resting on this slot, then what the Fortifications attached to it grant, then the
    recorded modifiers a card has laid on it. A seat with no Stronghold in play contributes no
    printed base.
    """
    stronghold = player_state(game, province.owner).stronghold
    total = (
        effective_stat(game, stronghold, Stat.PROVINCE_STRENGTH) if stronghold is not None else 0
    )
    for name, count in game.table.province_counters.get(province, {}).items():
        total += counter_from_key(name).province_strength * count
    for card_id, holds in game.table.province_attachments.items():
        if holds != province:
            continue
        fortification = game.table.cards_by_id[card_id]
        grant = PROVINCE_STRENGTH_GRANTS.get(fortification.printed_id)
        if grant is not None:
            total += grant(game, fortification, province)
    total += sum(
        recorded.amount
        for recorded in game.modifiers
        if isinstance(recorded, ProvinceModifier)
        and recorded.province == province
        and _grant_applies(game, recorded)
    )
    return max(0, total)


def unit_gold_cost(game: GameState, personality: L5RCard) -> int:
    """A unit's total Gold Cost: the Personality's own and every card attached to him (CR, Unit).

    What a card means by "his unit's cost" — the pool a variable-cost action is priced against.
    """
    return sum(
        effective_gold_cost(game, member) for member in unit_members(game.table, personality)
    )


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


# What a card can grant its own Gold Production as it bows, computed from the card and its
# controller's and opponents' views. A delta over whatever the card is worth at the time rather than
# a total: counters and granted modifiers feed the same stat, so a flat ceiling would under-report
# the moment anything else raised the card. A handler rather than a number because a card may gate
# its grant on a condition — Slave Pits offers nothing to the player who went first — and a grant
# affordability counts but the card refuses would strand the payment it made reachable.
SelfGrantHandler = Callable[[L5RCard, PlayerState, tuple[PlayerState, ...]], int]
GOLD_SELF_GRANT: dict[str, SelfGrantHandler] = {}

# The once-per-turn tag a card claims as it grants itself. Read here to tell a grant still to come
# from one `effective_gold_production` is already carrying, and by the trait that prices it.
SELF_GRANT = "gold_self_grant"


def self_grant(printed_id: str) -> Callable[[SelfGrantHandler], SelfGrantHandler]:
    """Register the decorated function as ``printed_id``'s self-grant, for a card whose own
    conditions decide how much it offers, or whether it offers anything at all."""

    def register(handler: SelfGrantHandler) -> SelfGrantHandler:
        if printed_id in GOLD_SELF_GRANT:
            raise ValueError(f"{printed_id} already grants itself Gold Production")
        GOLD_SELF_GRANT[printed_id] = handler
        return handler

    return register


def register_self_grant(printed_id: str, amount: int) -> None:
    """Declare that ``printed_id`` may raise its own Gold Production by ``amount`` as it bows.

    What the card's window trigger grants, told to affordability separately so a purchase only the
    grant can reach is still offered. The trigger is what makes the grant happen; this is what makes
    it countable before anyone is asked. Use :func:`self_grant` for a card that offers its grant only
    under a condition.
    """
    self_grant(printed_id)(lambda card, me, opponents: amount)


def maximum_gold_production(
    game: GameState, card: L5RCard, targets: tuple[L5RCard, ...] = ()
) -> int:
    """The most ``card`` could yield if its controller took every option it offers.

    What affordability asks, so that a purchase reachable only by a card raising its own yield is
    still offered. :func:`effective_gold_production` answers the same question for right now.

    A card that has already granted itself this turn adds nothing more: the grant is inside
    :func:`effective_gold_production` by then, and counting it twice would report a ceiling the card
    cannot reach.

    Two other places measure a seat's gold and deliberately report less: ``policies._spendable`` and
    :func:`~yasuki_core.sim.metrics.potential_gold_production` both leave a self-grant out, because
    weighing whether a purchase is worth making is not the same question as whether it is legal.

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
    return effective_gold_production(game, card, targets) + untaken_self_grant(game, card)


def untaken_self_grant(game: GameState, card: L5RCard) -> int:
    """What ``card`` can still grant itself this turn, or nothing once it has or its card declines
    to offer under current conditions."""
    handler = GOLD_SELF_GRANT.get(card.printed_id)
    if handler is None or used_this_turn(game, card, SELF_GRANT):
        return 0
    return handler(card, player_state(game, card.owner), opposing_states(game, card.owner))


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
