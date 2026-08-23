import logging
from pathlib import Path

import psycopg
from numpy.random import Generator

from yasuki_core.engine.players import PlayerId
from yasuki_core.engine.runner import Controls, GameRunner
from yasuki_core.engine.rules.policies import GoldRushPolicy
from yasuki_core.engine.session import EngineSession
from yasuki_core.engine.table import TableState
from yasuki_core.game_setup import build_state_from_deck
from yasuki_gui.session import build_demo_state

logger = logging.getLogger(__name__)


def _opponent_controls() -> Controls:
    """What drives the AI opponent. One :class:`GoldRushPolicy` fills both halves, so the gold it
    chooses to raise and the payments it agrees to come from the same strategy."""
    policy = GoldRushPolicy()
    return Controls(policy, policy)


class GameHost:
    """The game the desktop client is playing: the decks it was dealt from, the live session, and
    the runner driving it.

    Knows nothing about widgets, so a caller that starts or restarts a game is responsible for
    re-rendering afterwards.

    Attributes
    ----------
    human_seat : PlayerId
        The seat the human plays. Who takes the first turn is decided by Family Honor at the deal
        and is not this.
    runner : GameRunner
        Drives the live game. Replaced whenever a new game starts, so read it rather than hold it.
    """

    def __init__(
        self,
        human_deck: Path,
        opponent_deck: Path,
        *,
        rng: Generator | None = None,
        human_seat: PlayerId = PlayerId.P1,
    ) -> None:
        """Deal the opening game, falling back to the placeholder decks if the deal fails.

        Parameters
        ----------
        human_deck : pathlib.Path
            The decklist dealt to the human.
        opponent_deck : pathlib.Path
            The decklist dealt to the AI opponent.
        rng : numpy.random.Generator, optional
            Deals every game this host starts. Default None, which deals from system entropy —
            what a game wants, where a repeated opening is a defect.
        human_seat : PlayerId, optional
            The seat the human plays. Default P1.
        """
        self._decks = {"human": human_deck, "opponent": opponent_deck}
        self._rng = rng
        self.human_seat = human_seat
        self.runner = self._deal_or_fall_back()

    @property
    def session(self) -> EngineSession:
        """The live session. Replaced with the runner whenever a new game starts."""
        return self.runner.session

    def load_human_deck(self, path: Path | str) -> None:
        """Deal the decklist at ``path`` to the human and start a fresh game."""
        self._reload("human", path)

    def load_opponent_deck(self, path: Path | str) -> None:
        """Deal the decklist at ``path`` to the AI opponent and start a fresh game."""
        self._reload("opponent", path)

    def _reload(self, slot: str, path: Path | str) -> None:
        """Swap one deck and start a fresh game on it, committing neither until the deal succeeds,
        so a deck that cannot be read leaves both the slots and the running game as they were.

        No fallback to the placeholder decks here, unlike the opening deal: a deck the player chose
        and that cannot be read is an error to report, not a reason to deal something else.
        """
        candidate = self._decks | {slot: Path(path)}
        runner = self._deal(candidate)
        self._decks = candidate
        self.runner = runner

    def _deal(self, decks: dict[str, Path]) -> GameRunner:
        state, first_player = build_state_from_deck(
            decks["human"],
            opponent_deck_path=decks["opponent"],
            p1_name="You",
            p2_name="Opponent",
            rng=self._rng,
        )
        return self._runner_for(state, first_player)

    def _deal_or_fall_back(self) -> GameRunner:
        """Deal the chosen decks, or the DB-free placeholder ones when the database is unreachable
        or a decklist cannot be read, so the client still opens.

        Narrow on purpose: anything else is a defect rather than a degraded environment, and a
        client that silently opened on placeholder cards would hide it.
        """
        try:
            return self._deal(self._decks)
        except (OSError, psycopg.OperationalError) as exc:
            logger.warning("Could not deal the chosen decks, using the placeholder deck: %s", exc)
            return self._runner_for(*build_demo_state())

    def _runner_for(self, state: TableState, first_player: PlayerId) -> GameRunner:
        session = EngineSession.start(state, first_player)
        return GameRunner(session, self.human_seat, _opponent_controls())
