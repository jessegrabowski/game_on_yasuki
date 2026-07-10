from collections.abc import Callable, Iterator
from dataclasses import dataclass

from yasuki_core.engine.players import PlayerId
from yasuki_core.engine.rules.modifiers import Duration, Modifier, Stat
from yasuki_core.engine.rules.state import GameState
from yasuki_core.game_pieces.cards import L5RCard
from yasuki_core.game_pieces.counters import ALL_COUNTERS, SINCERITY
from yasuki_core.game_pieces.dynasty import DynastyHolding
from yasuki_core.game_pieces.pregame import StrongholdCard


@dataclass(frozen=True, slots=True)
class PlayerState:
    """A read-only view of one seat — the vocabulary a card effect reasons over: the seat's
    stronghold, the cards it controls in play, and its current gold and honor."""

    seat: PlayerId
    stronghold: StrongholdCard | None
    in_play: tuple[L5RCard, ...]
    gold: int
    honor: int
    went_second: bool

    @property
    def holdings(self) -> tuple[DynastyHolding, ...]:
        """The Holdings the seat controls in play."""
        return tuple(card for card in self.in_play if isinstance(card, DynastyHolding))

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
    stronghold = next((card for card in in_play if isinstance(card, StrongholdCard)), None)
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


def _is_clan(me: PlayerState, clan: str) -> bool:
    return me.stronghold is not None and me.stronghold.clan == clan


# Per-card gold-production handlers, registered on import of this module. The read-sites already
# load it, so a handler is always in place by the time gold is produced.


@gold_handler("ancestral_estate")
def _ancestral_estate(
    card: L5RCard, me: PlayerState, opponents: tuple[PlayerState, ...], targets: tuple[L5RCard, ...]
) -> int:
    """+1 GP while you are the second player."""
    return card.gold_production + (1 if me.went_second else 0)


@gold_handler("dockside_market")
def _dockside_market(
    card: L5RCard, me: PlayerState, opponents: tuple[PlayerState, ...], targets: tuple[L5RCard, ...]
) -> int:
    """+1 GP for controlling any Port, and +1 GP for controlling another Market."""
    bonus = (1 if me.controls("Port") else 0) + (1 if me.controls("Market", other_than=card) else 0)
    return card.gold_production + bonus


@gold_handler("jade_works")
def _jade_works(
    card: L5RCard, me: PlayerState, opponents: tuple[PlayerState, ...], targets: tuple[L5RCard, ...]
) -> int:
    """+2 GP when paying for a Jade card."""
    bonus = 2 if any("Jade" in target.keywords for target in targets) else 0
    return card.gold_production + bonus


@gold_handler("teardrop_island")
def _teardrop_island(
    card: L5RCard, me: PlayerState, opponents: tuple[PlayerState, ...], targets: tuple[L5RCard, ...]
) -> int:
    """Produce 2 Gold, or 3 while you are a Mantis Clan player."""
    return 3 if _is_clan(me, "Mantis") else 2


@gold_handler("shrine_of_sincerity")
def _shrine_of_sincerity(
    card: L5RCard, me: PlayerState, opponents: tuple[PlayerState, ...], targets: tuple[L5RCard, ...]
) -> int:
    """+1 GP when paying for a Sincerity card that still carries Sincerity tokens."""
    bonus = (
        1
        if any(
            "Sincerity" in target.keywords and target.counters.get(SINCERITY.key, 0) > 0
            for target in targets
        )
        else 0
    )
    return card.gold_production + bonus


# Per-card recruit-discount handlers — the "enters play for N less Gold" holdings.


@recruit_discount("colonial_farm")
def _colonial_farm(card: L5RCard, me: PlayerState, opponents: tuple[PlayerState, ...]) -> int:
    """Enters play for 1 less Gold if you are a Lion Clan player."""
    return 1 if _is_clan(me, "Lion") else 0


@recruit_discount("fantastic_gardens")
def _fantastic_gardens(card: L5RCard, me: PlayerState, opponents: tuple[PlayerState, ...]) -> int:
    """Enters play for 2 less Gold if you are a Crane Clan player."""
    return 2 if _is_clan(me, "Crane") else 0


@recruit_discount("moto_traders")
def _moto_traders(card: L5RCard, me: PlayerState, opponents: tuple[PlayerState, ...]) -> int:
    """Enters play for 1 less Gold if you control another Merchant Caravan."""
    return 1 if me.controls("Merchant Caravan", other_than=card) else 0


@recruit_discount("shrine_of_courtesy")
def _shrine_of_courtesy(card: L5RCard, me: PlayerState, opponents: tuple[PlayerState, ...]) -> int:
    """Courtesy grants -3 Gold Cost while you are the second player (you did not go first)."""
    return 3 if me.went_second else 0
