from dataclasses import dataclass

from yasuki_core.engine.players import PlayerId
from yasuki_core.engine.table import TableState, ZoneRole
from yasuki_core.engine.snapshot import InitialRecord
from yasuki_core.engine.rules.state import GameState, Phase
from yasuki_core.engine.rules.actions import Action, Pass, Recruit
from yasuki_core.engine.rules.decisions import DecisionResponse
from yasuki_core.engine.rules import flow, projection
from yasuki_core.engine.rules.projection import GameView
from yasuki_core.engine.rules.log import GameLog, build_game, act_and_log, submit_and_log
from yasuki_core.game_pieces.dynasty import DynastyHolding


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
        """Return the free actions ``seat`` may take right now: always a pass, plus — in the Dynasty
        phase — a Recruit for each face-up Holding in its provinces it could pay for. Empty while a
        decision is pending and for any seat but the active one.

        Gold is not a free action: it is produced only while paying a cost (rules-skeleton §7), so
        it surfaces through the Recruit's ``ChoosePayment``, never here."""
        if self.game.awaiting_decision or seat is not self.game.active:
            return []
        actions: list[Action] = [Pass()]
        if self.game.phase is Phase.DYNASTY:
            actions.extend(self._recruits(seat))
        return actions

    def _recruits(self, seat: PlayerId) -> list[Action]:
        """The Recruit actions ``seat`` can afford: each face-up Holding in its provinces whose cost
        its pool plus its unbowed producers' gold could cover."""
        producers = flow.gold_producers(self.game, seat)
        affordable = self.game.gold[seat] + sum(card.gold_production for card in producers)
        recruits: list[Action] = []
        for key, zone in self.game.table.zones.items():
            if key.owner is not seat or key.role is not ZoneRole.PROVINCE:
                continue
            for card in zone.cards:
                if isinstance(card, DynastyHolding) and card.face_up:
                    if flow.recruit_cost(self.game, card) <= affordable:
                        recruits.append(Recruit(card.id))
        return recruits

    def act(self, seat: PlayerId, action: Action) -> None:
        """Perform ``action`` for ``seat`` and record it. Raise ``ValueError`` if it is not
        currently legal for that seat."""
        if action not in self.legal_actions(seat):
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
