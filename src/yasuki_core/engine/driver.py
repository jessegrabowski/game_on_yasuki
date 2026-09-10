from collections.abc import Iterator
from typing import NamedTuple, Protocol

from yasuki_core.bots.agents import Agent
from yasuki_core.bots.policies import Policy
from yasuki_core.engine.players import PlayerId
from yasuki_core.engine.replay.game_log import Act, Answer
from yasuki_core.engine.rules.state import GameState
from yasuki_core.engine.rules.turn.structure import Phase
from yasuki_core.engine.session import EngineSession


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


# How many actions one Action Round may take before the run gives up. A round ends when every seat
# passes consecutively, so a policy that always finds something to take keeps it open forever. No
# legitimate round comes near this; it is a defect detector, not a rule of the game.
MAX_ACTIONS_PER_ROUND = 200


class Observer(Protocol):
    """Watches a driven game at both ends of each turn.

    Turn boundaries are where the board is read, because they are the only moments it is canonical.
    Read after an arbitrary action instead, a producer bowed to pay stops counting and the reading
    depends on where in the turn it was taken.

    Actions are not reported here — the game log already records every one with the seat that took
    it, so an observer that wants them reads the tape between these two calls.

    The two ends answer different questions. As a turn begins,
    ``flow._begin_turn`` has straightened the active seat and revealed
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
        If a seat has no legal action, a policy returns one it was not offered, or one Action Round
        runs past :data:`~yasuki_core.engine.driver.MAX_ACTIONS_PER_ROUND` without closing.
    """
    game = session.game
    watched: int | None = None
    playing: PlayerId | None = None
    round_actions = 0
    # A round is identified by the phase of the turn it belongs to: the record itself is frozen and
    # replaced on every yield, so it cannot be compared by identity.
    open_round: tuple[int, Phase] | None = None
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

        seat = game.round.priority
        actions = session.legal_actions(seat)
        if not actions:
            raise RuntimeError(f"{seat.name} has no legal action in {game.phase}")
        chosen = controls[seat].policy.choose(session.project(seat), actions)
        if chosen not in actions:
            raise RuntimeError(f"{seat.name}'s policy chose {chosen}, which was not offered")
        here = (game.turn, game.phase)
        round_actions = round_actions + 1 if here == open_round else 1
        open_round = here
        if round_actions > MAX_ACTIONS_PER_ROUND:
            raise RuntimeError(
                f"an Action Round in {game.phase} ran past {MAX_ACTIONS_PER_ROUND} actions; "
                f"{seat.name} last chose {chosen}"
            )
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
