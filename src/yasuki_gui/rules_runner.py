from collections.abc import Iterable

from yasuki_core.engine.players import PlayerId
from yasuki_core.engine.table import ZoneKey, ZoneRole
from yasuki_core.engine.rules.decisions import DiscardToHandSize, DecisionResponse
from yasuki_core.engine.rules.projection import GameView
from yasuki_core.engine.session import EngineSession, LegalAction


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

    def legal_actions(self) -> list[LegalAction]:
        """Return the actions the human may take right now (empty when it is not their turn)."""
        return self.session.legal_actions(self.human)

    @property
    def is_opponent_turn(self) -> bool:
        """Whether control rests with the AI-reserved opponent, so the UI should run its turn."""
        return self.session.game.active is not self.human

    @property
    def pending_discard(self) -> DiscardToHandSize | None:
        """The discard the human must answer, or None when nothing is awaited from them."""
        pending = self.session.game.pending
        if isinstance(pending, DiscardToHandSize) and pending.seat is self.human:
            return pending
        return None

    def act(self, action: LegalAction) -> None:
        """Perform the human's chosen action. Does not run the opponent — the caller checks
        :attr:`is_opponent_turn` afterwards and runs it so the turn change stays visible."""
        self.session.act(self.human, action)

    def resolve_discard(self, card_ids: Iterable[str]) -> None:
        """Answer the human's pending discard with the chosen cards."""
        self.session.submit(self.human, DecisionResponse(tuple(card_ids)))

    def run_opponent(self) -> None:
        """Run the opponent's turn to completion: with no AI, it passes each phase and auto-resolves
        its end-of-turn discard until control returns to the human."""
        game = self.session.game
        while game.active is not self.human:
            pending = game.pending
            if pending is not None:
                self._auto_discard(pending.seat, pending.count)
            else:
                self.session.act(game.active, LegalAction.PASS)

    def _auto_discard(self, seat: PlayerId, count: int) -> None:
        hand = self.session.game.table.zones[ZoneKey(seat, ZoneRole.HAND)].cards
        victims = tuple(card.id for card in hand[:count])
        self.session.submit(seat, DecisionResponse(victims))
