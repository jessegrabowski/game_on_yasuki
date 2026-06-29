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
