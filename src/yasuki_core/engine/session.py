from dataclasses import dataclass

from yasuki_core.engine.players import PlayerId
from yasuki_core.engine.table import TableState
from yasuki_core.engine.snapshot import InitialRecord
from yasuki_core.engine.rules.state import GameState
from yasuki_core.engine.rules.actions import (
    Action,
    DynastyDiscard,
)
from yasuki_core.engine.rules.decisions import DecisionResponse
from yasuki_core.engine.rules import legality, projection
from yasuki_core.engine.rules.projection import GameView
from yasuki_core.engine.rules.log import (
    Act,
    GameLog,
    build_game,
    act_and_log,
    submit_and_log,
    cancel_and_log,
    replay,
)


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

    def legal_actions(self, seat: PlayerId) -> list[Action]:
        """Return the free actions ``seat`` may take right now."""
        return legality.legal_actions(self.game, seat)

    def act(self, seat: PlayerId, action: Action) -> None:
        """Perform ``action`` for ``seat`` and record it. Raise ``ValueError`` if it is not
        currently legal for that seat."""
        if not legality.is_legal(self.game, seat, action):
            raise ValueError(f"{action} is not legal for {seat.name} right now")
        act_and_log(self.game, self.log, action)

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

    def cancel(self, seat: PlayerId) -> None:
        """Back out of ``seat``'s pending decision, undoing the action that raised it, and record it.
        Raise ``RuntimeError`` if no decision is pending, or ``ValueError`` if ``seat`` is not the
        seat being asked or the decision cannot be cancelled."""
        pending = self.game.pending
        if pending is None:
            raise RuntimeError("no decision is pending")
        if pending.seat is not seat:
            raise ValueError(f"{seat.name} cannot cancel {pending.seat.name}'s decision")
        cancel_and_log(self.game, self.log)

    def undo_last(self, seat: PlayerId) -> bool:
        """Undo ``seat``'s most recent action when it was a Dynasty Discard and no decision is
        pending — the one free action safe to reverse, as it has no cost and does not advance the
        turn. Drop it from the tape and rebuild by replay. Return whether anything was undone."""
        if self.game.pending is not None:
            return False
        entries = self.log.entries
        if not entries:
            return False
        last = entries[-1]
        if not isinstance(last, Act) or last.seat is not seat:
            return False
        if not isinstance(last.action, DynastyDiscard):
            return False
        entries.pop()
        self.game = replay(self.log)
        return True
