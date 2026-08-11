from collections.abc import Callable, Iterator
from dataclasses import dataclass

from yasuki_core.engine.players import PlayerId
from yasuki_core.engine.rules.modifiers import Duration, Modifier, Stat
from yasuki_core.engine.rules.state import GameState
from yasuki_core.game_pieces.cards import L5RCard
from yasuki_core.game_pieces.counters import ALL_COUNTERS
from yasuki_core.game_pieces.prints import HoldingPrint, StrongholdPrint


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


def active_modifiers(game: GameState, card: L5RCard, stat: Stat) -> Iterator[Modifier]:
    """Every modifier adjusting ``card``'s ``stat`` right now: one derived from each counter it holds
    (each counter is a source that grants its per-count stat while in play), plus the recorded
    modifiers targeting it — a ``WHILE_SOURCE_IN_PLAY`` one only while its source is on the
    battlefield."""
    # A counter's source is the card itself, in play by construction here (this is only reached for
    # an in-play card), so no source-in-play check is needed for the derived modifiers.
    for counter in ALL_COUNTERS:
        per_count = getattr(counter, stat.value, 0)
        count = card.counters.get(counter.key, 0)
        if per_count and count:
            yield Modifier(card.id, card.id, stat, per_count * count, Duration.WHILE_SOURCE_IN_PLAY)
    for modifier in game.modifiers:
        if modifier.target_id != card.id or modifier.stat is not stat:
            continue
        if modifier.duration is Duration.WHILE_SOURCE_IN_PLAY and not _on_battlefield(
            game, modifier.source_id
        ):
            continue
        yield modifier


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
    """``card``'s printed keywords plus any its own ability grants under current conditions.

    A card with no owner — one not yet dealt to a seat — carries only its printed keywords, since a
    grant reads the controller's position to decide.
    """
    handler = KEYWORD_GRANTS.get(card.printed_id)
    if handler is None or card.owner is None:
        return frozenset(card.keywords)
    granted = handler(card, player_state(game, card.owner), opposing_states(game, card.owner))
    return frozenset(card.keywords).union(granted)


def is_clan(me: PlayerState, clan: str) -> bool:
    """Whether ``me`` is playing ``clan``, read from the stronghold."""
    return me.stronghold is not None and me.stronghold.clan == clan
