from dataclasses import dataclass

from yasuki_core.engine.players import PlayerId
from yasuki_core.engine.table import TableState, ZoneKey, ZoneRole
from yasuki_core.engine.snapshot import InitialRecord
from yasuki_core.engine.rules.state import GameState, Phase
from yasuki_core.engine.rules.actions import (
    ActivateAbility,
    Action,
    DynastyDiscard,
    Legacy,
    Pass,
    Recruit,
)
from yasuki_core.engine.rules.decisions import DecisionResponse
from yasuki_core.engine.rules import abilities, flow, projection
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
        if self.game.game_over or self.game.awaiting_decision or seat is not self.game.active:
            return []
        actions: list[Action] = [Pass()]
        actions.extend(self._abilities(seat))
        if self.game.phase is Phase.DYNASTY:
            actions.extend(self._recruits(seat))
            actions.extend(self._dynasty_discards(seat))
            actions.extend(self._legacy(seat))
        return actions

    def _abilities(self, seat: PlayerId) -> list[Action]:
        """An ActivateAbility for each in-play card whose activated ability the seat can use in the
        current phase (controlled, unbowed, with a legal target)."""
        ready = abilities.activatable(self.game, seat, self.game.phase)
        return [ActivateAbility(card.id) for card in ready]

    def _legacy(self, seat: PlayerId) -> list[Action]:
        """The Legacy ability when the seat can take it: once per turn, and only with a card in hand
        to pay the banish cost. Offered even when no Legacy card can be found — the rules make the
        whiff a loss rather than hiding the option (which would leak face-down province contents)."""
        if self.game.has_used(flow.legacy_key(seat, self.game.turn)):
            return []
        hand = self.game.table.zones[ZoneKey(seat, ZoneRole.HAND)]
        return [Legacy()] if hand.cards else []

    def _dynasty_discards(self, seat: PlayerId) -> list[Action]:
        """A DynastyDiscard for each face-up card in the seat's provinces — the rule allows
        discarding any face-up province card, not only Holdings."""
        discards: list[Action] = []
        for key, zone in self.game.table.zones.items():
            if key.owner is not seat or key.role is not ZoneRole.PROVINCE:
                continue
            discards.extend(DynastyDiscard(card.id) for card in zone.cards if card.face_up)
        return discards

    def _recruits(self, seat: PlayerId) -> list[Action]:
        """The Recruit actions ``seat`` can afford: each face-up Holding in its provinces whose cost
        its pool plus its unbowed producers' gold could cover, plus an Invest variant when the seat
        could also cover the card's Invest cost."""
        recruits: list[Action] = []
        for key, zone in self.game.table.zones.items():
            if key.owner is not seat or key.role is not ZoneRole.PROVINCE:
                continue
            for card in zone.cards:
                if not (isinstance(card, DynastyHolding) and card.face_up):
                    continue
                affordable = flow.reachable_gold(self.game, seat, card)
                base = flow.recruit_cost(self.game, card)
                if base <= affordable:
                    recruits.append(Recruit(card.id))
                invest = abilities.invest_for(card)
                if invest is not None and base + invest.minimum <= affordable:
                    recruits.append(Recruit(card.id, invest=True))
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
