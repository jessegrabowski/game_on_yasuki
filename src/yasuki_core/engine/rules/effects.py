from collections.abc import Callable
from dataclasses import dataclass

from yasuki_core.engine.players import PlayerId
from yasuki_core.engine.rules.state import GameState
from yasuki_core.game_pieces.cards import L5RCard
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


def effective_gold_production(
    game: GameState, card: L5RCard, targets: tuple[L5RCard, ...] = ()
) -> int:
    """The gold ``card`` produces right now: its registered handler's result against the live views,
    or its printed ``gold_production`` (0 for a card that produces none) when no handler is
    registered.

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
        return getattr(card, "gold_production", 0)
    return handler(card, player_state(game, card.owner), opposing_states(game, card.owner), targets)


# Per-card gold-production handlers, registered on import of this module. The read-sites already load
# it, so a handler is always in place by the time gold is produced.


@gold_handler("ancestral_estate")
def _ancestral_estate(
    card: L5RCard, me: PlayerState, opponents: tuple[PlayerState, ...], targets: tuple[L5RCard, ...]
) -> int:
    """+1 GP while another player's Stronghold out-produces mine."""
    outproduced = me.stronghold is not None and any(
        opponent.stronghold is not None
        and opponent.stronghold.gold_production > me.stronghold.gold_production
        for opponent in opponents
    )
    return card.gold_production + (1 if outproduced else 0)


@gold_handler("dockside_market")
def _dockside_market(
    card: L5RCard, me: PlayerState, opponents: tuple[PlayerState, ...], targets: tuple[L5RCard, ...]
) -> int:
    """+1 GP for controlling any Port, and +1 GP for controlling another Market."""
    bonus = (1 if me.controls("Port") else 0) + (1 if me.controls("Market", other_than=card) else 0)
    return card.gold_production + bonus
