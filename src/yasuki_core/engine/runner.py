from collections.abc import Iterable, Iterator
from typing import NamedTuple, Protocol

from yasuki_core.engine.players import PlayerId
from yasuki_core.engine.rules import abilities, legality
from yasuki_core.engine.rules.actions import (
    ActivateAbility,
    Action,
    Cycle,
    DynastyDiscard,
    Legacy,
    Pass,
    Recruit,
)
from yasuki_core.engine.rules.agents import Agent, AutoAgent
from yasuki_core.engine.rules.decisions import DecisionRequest, DecisionResponse
from yasuki_core.engine.rules.log import Act, Answer
from yasuki_core.engine.rules.policies import Policy
from yasuki_core.engine.rules.projection import GameView
from yasuki_core.engine.rules.state import GameState
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
                    base = legality.recruit_cost(game, card)
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

    def board_menu(self) -> list[tuple[str, Action]]:
        """The labeled rulebook abilities, for a right-click on the empty board. These belong to no
        card, so the board is the only place they can be offered. Empty when none is legal now."""
        labels = {
            Legacy(): "Legacy: banish a card to search for a Legacy card",
            Cycle(): "Cycle: put Province cards on the bottom of your deck",
        }
        return [(labels[action], action) for action in self.legal_actions() if action in labels]

    def legacy_search_pool(self) -> list:
        """The cards the human's Legacy search looks through — its whole dynasty deck plus its
        face-down province cards — for a search dialog to display."""
        return legality.legacy_search_pool(self.session.game, self.human)

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


class Controls(NamedTuple):
    """What drives one seat with no human at it.

    Attributes
    ----------
    policy : Policy
        Chooses which action the seat takes.
    agent : Agent
        Answers the decisions those actions raise. May be the same object as ``policy`` when a
        strategy wants its payments to agree with its choices.
    """

    policy: Policy
    agent: Agent


class Observer(Protocol):
    """Watches a driven game at both ends of each turn.

    Turn boundaries are where the board is read, because they are the only moments it is canonical.
    Read after an arbitrary action instead, a producer bowed to pay stops counting and the reading
    depends on where in the turn it was taken.

    Actions are not reported here — the game log already records every one with the seat that took
    it, so an observer that wants them reads the tape between these two calls.

    The two ends answer different questions. As a turn begins,
    :func:`~yasuki_core.engine.rules.flow._begin_turn` has straightened the active seat and revealed
    its provinces, so the board shows what it has to spend. As one ends, the board shows what it
    did: producers bowed to pay are still bowed, and a province it cleared holds a face-down
    replacement.
    """

    def turn_began(self, game: GameState) -> None:
        """Called once ``game.active``'s turn has begun, with the board it starts from."""
        ...

    def turn_ended(self, game: GameState, seat: PlayerId) -> None:
        """Called once ``seat``'s turn is over, with the board it left behind.

        By then the next turn has already begun, but ``seat`` is no longer active and nothing has
        touched what it owns — only the new active seat straightens and reveals.
        """
        ...


def run_game(
    session: EngineSession,
    controls: dict[PlayerId, Controls],
    *,
    turn_limit: int,
    observer: Observer | None = None,
) -> Iterator[Act | Answer]:
    """
    Play ``session`` a step at a time, yielding each input as the engine accepts it.

    Nothing happens until the iterator is advanced, and stopping early leaves the game exactly where
    it stopped — which is what lets a caller pause, inspect between steps, or cancel a run. A turn
    abandoned that way is never closed, so an observer never sees it end and a recorder does not
    report it.

    Parameters
    ----------
    session : EngineSession
        The session to drive. Left at whatever state play reached.
    controls : dict mapping PlayerId to Controls
        What drives each seat. Every seat that could act must appear.
    turn_limit : int
        The last turn to play. Games do not end on their own except by the Legacy whiff, so this
        is what bounds a run.
    observer : Observer, optional
        Told when each turn begins and ends, including the first and the last. Default None, which
        costs nothing.

    Yields
    ------
    Act or Answer
        The input just applied, in the vocabulary the game log records — an action a policy chose,
        or a decision an agent answered.

    Raises
    ------
    RuntimeError
        If a seat has no legal action, or a policy returns one it was not offered.
    """
    game = session.game
    watched: int | None = None
    playing: PlayerId | None = None
    while not game.game_over and game.turn <= turn_limit:
        if observer is not None and game.turn != watched:
            if playing is not None:
                observer.turn_ended(game, playing)
            watched, playing = game.turn, game.active
            observer.turn_began(game)
        pending = game.pending
        if pending is not None:
            seat = pending.seat
            response = controls[seat].agent.decide(pending, session.project(seat))
            session.submit(seat, response)
            yield Answer(seat, response)
            continue

        seat = game.active
        actions = session.legal_actions(seat)
        if not actions:
            raise RuntimeError(f"{seat.name} has no legal action in {game.phase}")
        chosen = controls[seat].policy.choose(session.project(seat), actions)
        if chosen not in actions:
            raise RuntimeError(f"{seat.name}'s policy chose {chosen}, which was not offered")
        session.act(seat, chosen)
        yield Act(seat, chosen)

    # The turn the run stopped on has begun but never been closed by the loop.
    if observer is not None and playing is not None:
        observer.turn_ended(game, playing)


def play_game(
    session: EngineSession,
    controls: dict[PlayerId, Controls],
    *,
    turn_limit: int,
    observer: Observer | None = None,
) -> None:
    """
    Play ``session`` to its end or to ``turn_limit``, whichever comes first, mutating it in place.

    Stops only on those two conditions. A driver that inferred its own stopping point would
    silently truncate a run. Drives :func:`run_game` to exhaustion; take that instead when a caller
    needs to act between steps.

    Parameters
    ----------
    session : EngineSession
        The session to drive. Left at whatever state play reached.
    controls : dict mapping PlayerId to Controls
        What drives each seat. Every seat that could act must appear.
    turn_limit : int
        The last turn to play. Games do not end on their own except by the Legacy whiff, so this
        is what bounds a run.
    observer : Observer, optional
        Told when each turn begins and ends, including the first and the last. Default None, which
        costs nothing.

    Raises
    ------
    RuntimeError
        If a seat has no legal action, or a policy returns one it was not offered.
    """
    for _ in run_game(session, controls, turn_limit=turn_limit, observer=observer):
        pass
