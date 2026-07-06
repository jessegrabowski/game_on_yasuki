from collections.abc import Iterable

from yasuki_core.engine.players import PlayerId
from yasuki_core.engine.rules import flow
from yasuki_core.engine.rules.actions import Action, DynastyDiscard, Pass, Recruit
from yasuki_core.engine.rules.agents import Agent, AutoAgent
from yasuki_core.engine.rules.decisions import DecisionRequest, DecisionResponse
from yasuki_core.engine.rules.projection import GameView
from yasuki_core.engine.session import EngineSession


class GameRunner:
    """Drives a single-player rules game through an :class:`EngineSession`.

    The human advances their own turn a phase at a time; when the turn ends, the AI-reserved
    opponent's turn auto-runs until control returns to the human. A decision the human owes is left
    pending for the UI to present; the opponent's decisions are answered by its :class:`Agent`.

    Attributes
    ----------
    session : EngineSession
        The authoritative session this runner drives.
    human : PlayerId
        The seat the human plays.
    """

    def __init__(self, session: EngineSession, human: PlayerId, opponent: Agent | None = None):
        self.session = session
        self.human = human
        self._opponent = opponent or AutoAgent()

    def view(self) -> GameView:
        """Return the human's projection — what the board, phase bar, and panels render."""
        return self.session.project(self.human)

    def legal_actions(self) -> list[Action]:
        """Return the actions the human may take right now (empty when it is not their turn)."""
        return self.session.legal_actions(self.human)

    def province_menu(self, card_id: str) -> list[tuple[str, Action]]:
        """The labeled actions offered for a face-up province card, for its left-click menu: a
        Recruit (labeled with its gold cost) when affordable, and a Dynasty Discard. Empty when the
        card offers nothing right now."""
        game = self.session.game
        items: list[tuple[str, Action]] = []
        for action in self.legal_actions():
            if getattr(action, "card_id", None) != card_id:
                continue
            if isinstance(action, Recruit):
                cost = flow.recruit_cost(game, game.table.cards_by_id[card_id])
                items.append((f"Recruit: Pay {cost} gold", action))
            elif isinstance(action, DynastyDiscard):
                items.append(("Repeatable Dynasty: Discard from province", action))
        return items

    @property
    def is_opponent_turn(self) -> bool:
        """Whether control rests with the AI-reserved opponent, so the UI should run its turn."""
        return self.session.game.active is not self.human

    @property
    def pending(self) -> DecisionRequest | None:
        """The decision the human must answer, or None when nothing is awaited from them."""
        pending = self.session.game.pending
        return pending if pending is not None and pending.seat is self.human else None

    def act(self, action: Action) -> None:
        """Perform the human's chosen action. Does not run the opponent — the caller checks
        :attr:`is_opponent_turn` afterwards and runs it so the turn change stays visible."""
        self.session.act(self.human, action)

    def submit(self, choices: Iterable[str]) -> None:
        """Answer the human's pending decision with the chosen ids."""
        self.session.submit(self.human, DecisionResponse(tuple(choices)))

    def cancel(self) -> None:
        """Back out of the human's pending decision, undoing the action that raised it."""
        self.session.cancel(self.human)

    def run_opponent(self) -> None:
        """Run the opponent's turn to completion: it passes each phase and lets its Agent answer any
        decision it owes, until control returns to the human."""
        game = self.session.game
        while game.active is not self.human:
            pending = game.pending
            if pending is not None:
                response = self._opponent.decide(pending, self.session.project(pending.seat))
                self.session.submit(pending.seat, response)
            else:
                self.session.act(game.active, Pass())
