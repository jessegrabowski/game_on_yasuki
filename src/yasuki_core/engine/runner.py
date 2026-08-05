from collections.abc import Iterable

from yasuki_core.engine.players import PlayerId
from yasuki_core.engine.table import DeckKey
from yasuki_core.game_pieces.constants import Side
from yasuki_core.engine.rules import abilities, flow
from yasuki_core.engine.rules.actions import (
    ActivateAbility,
    Action,
    DynastyDiscard,
    Legacy,
    Pass,
    Recruit,
)
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
        """The labeled actions offered for a face-up province card, for its left-click menu: a plain
        Recruit plus its second purchase option where one exists — Invest for an Invest holding,
        Proclaim for an own-clan Personality (all labeled with their gold) — and a Dynasty Discard.
        Empty when the card offers nothing right now."""
        game = self.session.game
        card = game.table.cards_by_id[card_id]
        # Deferred until a Recruit action confirms this is a recruitable card: recruit_cost reads
        # gold_cost, which only Dynasty/Fate cards carry. Clicking a card that only offers an
        # activated ability (e.g. a stronghold) must not reach it.
        base: int | None = None
        items: list[tuple[str, Action]] = []
        for action in self.legal_actions():
            if getattr(action, "card_id", None) != card_id:
                continue
            if isinstance(action, Recruit):
                if base is None:
                    base = flow.recruit_cost(game, card)
                if action.invest:
                    items.append((self._invest_label(card, base), action))
                elif action.proclaim:
                    label = f"Recruit & Proclaim: Pay {base} gold, gain {card.personal_honor} honor"
                    items.append((label, action))
                else:
                    items.append((f"Recruit: Pay {base} gold", action))
            elif isinstance(action, DynastyDiscard):
                items.append(("Discard from province", action))
        return items

    @staticmethod
    def _invest_label(card, base: int) -> str:
        invest = abilities.invest_for(card)
        if invest.minimum == invest.maximum:
            return f"Invest: Pay {base + invest.minimum} gold"
        return f"Invest: Pay {base + invest.minimum}–{base + invest.maximum} gold"

    def ability_menu(self, card_id: str) -> list[tuple[str, Action]]:
        """The activated-ability action offered for an in-play card the human controls, labelled with
        the ability's description, when it is legal to use now. Empty otherwise."""
        for action in self.legal_actions():
            if isinstance(action, ActivateAbility) and action.card_id == card_id:
                ability = abilities.ability_for(self.session.game.table.cards_by_id[card_id])
                label = ability.label if ability is not None else "Activate ability"
                return [(label, action)]
        return []

    def deck_menu(self, deck_key: DeckKey) -> list[tuple[str, Action]]:
        """The labeled actions for a left-click on a deck. The human's dynasty deck offers Legacy —
        the Dynasty rulebook ability that searches it — when it is legal; empty otherwise."""
        if deck_key.owner is not self.human or deck_key.side is not Side.DYNASTY:
            return []
        if Legacy() not in self.legal_actions():
            return []
        return [("Legacy: banish a card to search for a Legacy card", Legacy())]

    def legacy_search_pool(self) -> list:
        """The cards the human's Legacy search looks through — its whole dynasty deck plus its
        face-down province cards — for a search dialog to display."""
        return flow.legacy_search_pool(self.session.game, self.human)

    @property
    def loser(self) -> PlayerId | None:
        """The seat that has lost the game, or None while it is ongoing."""
        return self.session.game.loser

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

    def undo_last(self) -> bool:
        """Undo the human's last action if it was a Dynasty Discard and nothing has happened since.
        Return whether anything was undone, so the caller can re-render only when it did."""
        return self.session.undo_last(self.human)

    def submit(self, choices: Iterable[str], boosted: Iterable[str] = ()) -> None:
        """Answer the human's pending decision with the chosen ids, and the subset whose bow-time
        production boost was taken (Outlying Farms paying boosted)."""
        self.session.submit(self.human, DecisionResponse(tuple(choices), tuple(boosted)))

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
