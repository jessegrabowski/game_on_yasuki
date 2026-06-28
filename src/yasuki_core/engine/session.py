from dataclasses import dataclass
from enum import Enum

from yasuki_core.engine.players import PlayerId
from yasuki_core.engine.table import TableState
from yasuki_core.engine.snapshot import InitialRecord
from yasuki_core.engine.rules.state import GameState
from yasuki_core.engine.rules.decisions import DecisionResponse
from yasuki_core.engine.rules import projection
from yasuki_core.engine.rules.projection import GameView
from yasuki_core.engine.rules.log import GameLog, build_game, advance_and_log, submit_and_log


class LegalAction(Enum):
    """A free action a seat may take when no decision is pending. The vocabulary grows with the
    rules — gold production and Recruit join it at Steps 1 and 2."""

    PASS = "pass"


@dataclass(slots=True)
class EngineSession:
    """The single surface a client plays a rules-driven game through.

    Owns the authoritative :class:`GameState` and the append-only :class:`GameLog`, and exposes
    the three engine-to-client channels: a per-seat projection, a legal-action query, and decision
    submission — plus turn advancement. Every accepted input is recorded, so ``log`` always replays
    to the current ``game``.

    Attributes
    ----------
    game : GameState
        The authoritative game state.
    log : GameLog
        The tape of accepted inputs, replayable to ``game``.
    """

    game: GameState
    log: GameLog

    @classmethod
    def start(cls, table: TableState, first_player: PlayerId, *, seed: int = 0) -> "EngineSession":
        """Open a session on a dealt ``table``. Snapshot the table into a fresh log, then build the
        live game from that snapshot so the log replays to it exactly.

        Parameters
        ----------
        table : TableState
            The dealt board to play on.
        first_player : PlayerId
            The seat taking the first turn.
        seed : int, optional
            The master RNG seed for deterministic replay. Default 0.
        """
        log = GameLog(initial=InitialRecord.from_state(table), first_player=first_player, seed=seed)
        return cls(game=build_game(log), log=log)

    def project(self, seat: PlayerId) -> GameView:
        """Return the view ``seat`` is entitled to."""
        return projection.project(self.game, seat)

    def legal_actions(self, seat: PlayerId) -> list[LegalAction]:
        """Return the free actions ``seat`` may take right now. Empty while a decision is pending
        (the seat must answer it) and for any seat but the active one. In Step 0 the only action is
        to pass, which ends the current phase."""
        if self.game.awaiting_decision or seat is not self.game.active:
            return []
        return [LegalAction.PASS]

    def act(self, seat: PlayerId, action: LegalAction) -> None:
        """Perform ``action`` for ``seat``. Raise ``ValueError`` if it is not currently legal for
        that seat. Passing ends the current phase."""
        if action not in self.legal_actions(seat):
            raise ValueError(f"{action} is not legal for {seat.name} right now")
        if action is LegalAction.PASS:
            self._advance(seat)

    def _advance(self, seat: PlayerId) -> None:
        # The phase-advance mechanic a pass triggers; the active seat is guaranteed by act().
        advance_and_log(self.game, self.log)

    def submit(self, seat: PlayerId, response: DecisionResponse) -> None:
        """Answer the pending decision and record it. Raise ``RuntimeError`` if no decision is
        pending, or ``ValueError`` if ``seat`` is not the seat being asked or the answer is
        malformed."""
        pending = self.game.pending
        if pending is None:
            raise RuntimeError("no decision is pending")
        if pending.seat is not seat:
            raise ValueError(f"{seat.name} cannot answer {pending.seat.name}'s decision")
        submit_and_log(self.game, self.log, response)
