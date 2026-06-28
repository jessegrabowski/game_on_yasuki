from collections.abc import Iterable

from yasuki_core.engine.players import PlayerId
from yasuki_core.engine.table import ZoneKey, ZoneRole
from yasuki_core.engine.rules.decisions import DiscardToHandSize, DecisionResponse
from yasuki_core.engine.rules.projection import GameView
from yasuki_core.engine.session import EngineSession


class GameRunner:
    """Drives a single-player rules game through an :class:`EngineSession`.

    The human advances their own turn a phase at a time; when the turn ends, the AI-reserved
    opponent's empty turn auto-runs (there is no AI yet) until control returns to the human. An
    end-of-turn discard the human owes is left pending for the UI to resolve.

    Attributes
    ----------
    session : EngineSession
        The authoritative session this runner drives.
    human : PlayerId
        The seat the human plays.
    """

    def __init__(self, session: EngineSession, human: PlayerId):
        self.session = session
        self.human = human

    def view(self) -> GameView:
        """Return the human's projection — what the board, phase bar, and panels render."""
        return self.session.project(self.human)

    @property
    def pending_discard(self) -> DiscardToHandSize | None:
        """The discard the human must answer, or None when nothing is awaited from them."""
        pending = self.session.game.pending
        if isinstance(pending, DiscardToHandSize) and pending.seat is self.human:
            return pending
        return None

    def advance(self) -> None:
        """Advance the human's turn one phase. If that ends the turn, auto-run the opponent back to
        the human. A no-op while the human owes a decision — resolve it first."""
        if self.session.game.awaiting_decision:
            return
        self.session.advance(self.human)
        self._settle()

    def resolve_discard(self, card_ids: Iterable[str]) -> None:
        """Answer the human's pending discard with the chosen cards, then settle the opponent's
        turn."""
        self.session.submit(self.human, DecisionResponse(tuple(card_ids)))
        self._settle()

    def _settle(self) -> None:
        # With no AI yet, run the opponent's empty turn to completion whenever it holds the turn:
        # advance each phase and auto-resolve its end-of-turn discard, until the human acts again.
        game = self.session.game
        while game.active is not self.human:
            pending = game.pending
            if pending is not None:
                self._auto_discard(pending.seat, pending.count)
            else:
                self.session.advance(game.active)

    def _auto_discard(self, seat: PlayerId, count: int) -> None:
        hand = self.session.game.table.zones[ZoneKey(seat, ZoneRole.HAND)].cards
        victims = tuple(card.id for card in hand[:count])
        self.session.submit(seat, DecisionResponse(victims))
