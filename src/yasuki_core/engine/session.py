from dataclasses import dataclass

from dataclasses import replace

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
    Answer,
    GameLog,
    build_game,
    act_and_log,
    submit_and_log,
    replay,
)


def _position(game: GameState, seat: PlayerId) -> tuple:
    """What ``seat`` holds: its scalars, the contents of every zone and deck it owns, and its cards
    in play. Compared across a rewind to tell whether an action reached across the table.

    Keyed by zone rather than ordered, because a Province created mid-game leaves the two states
    holding the same zones in a different order.
    """
    table = game.table
    return (
        table.seats[seat].honor,
        game.gold.get(seat, 0),
        {
            key: tuple(card.id for card in zone.cards)
            for key, zone in table.zones.items()
            if key.owner is seat
        },
        {
            key: tuple(card.id for card in deck.cards)
            for key, deck in table.decks.items()
            if key.owner is seat
        },
        {
            card.id: (card.bowed, card.counters)
            for card in table.battlefield.cards
            if card.owner is seat
        },
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
        """Back out of ``seat``'s pending decision, unwinding the whole action that raised it.

        Backing out of one step of a multi-step action undoes every step of it, including the cost
        it has already paid — see :meth:`abort`. Raise ``RuntimeError`` if no decision is pending, or
        ``ValueError`` if ``seat`` is not the seat being asked or the action cannot be unwound.
        """
        pending = self.game.pending
        if pending is None:
            raise RuntimeError("no decision is pending")
        if pending.seat is not seat:
            raise ValueError(f"{seat.name} cannot cancel {pending.seat.name}'s decision")
        if not pending.cancellable:
            raise ValueError(f"{type(pending).__name__} cannot be cancelled")
        if not self.abort(seat):
            raise ValueError("the opportunity has passed; there is nothing left to unwind")

    def abort(self, seat: PlayerId) -> bool:
        """Abandon the action ``seat`` has in flight, unwinding everything it has done so far.

        An ability announced and half-resolved has already paid its cost and may have taken several
        answers; backing out of any one step has to undo all of them, not just the last. The tape is
        truncated to before the action was announced and the game rebuilt by replay, so the unwind
        reverses whatever the action did without any effect needing its own inverse.

        Refuse once the action has moved anything another seat holds. Taking back a card an opponent
        has already drawn does not take back their having seen it, so an action that reached across
        the table is committed the moment it did. Refuse likewise for a decision the rules force, for
        an action already complete, once another seat has resolved a step of its own, and while
        another seat is the one being asked — an action that has handed the question on is past the
        point where its announcer may take it back.

        Return whether anything was unwound.
        """
        pending = self.game.pending
        if pending is None or not pending.cancellable:
            return False  # nothing in flight, or a decision the seat is not allowed to back out of
        if pending.seat is not seat:
            return False  # another seat is mid-decision; the question is not this seat's to erase
        entries = self.log.entries
        cut = len(entries)
        while cut and isinstance(entries[cut - 1], Answer) and entries[cut - 1].seat is seat:
            cut -= 1
        if not cut or not isinstance(entries[cut - 1], Act) or entries[cut - 1].seat is not seat:
            return False  # the pending decision is not one this seat's own action raised
        rewound = replace(self.log, entries=entries[: cut - 1]).replay()
        others = [other for other in self.game.table.seats if other is not seat]
        if any(_position(rewound, other) != _position(self.game, other) for other in others):
            return False
        del entries[cut - 1 :]
        self.game = rewound
        return True

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
