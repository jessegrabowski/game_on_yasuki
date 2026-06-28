from dataclasses import dataclass, field

from yasuki_core.engine.players import PlayerId
from yasuki_core.engine.snapshot import (
    InitialRecord,
    build_initial_state,
    encode_initial,
    decode_initial,
)
from yasuki_core.engine.rules.state import GameState
from yasuki_core.engine.rules.actions import Action, Pass, ProduceGold
from yasuki_core.engine.rules.decisions import DecisionResponse
from yasuki_core.engine.rules import flow


@dataclass(frozen=True, slots=True)
class Act:
    """Tape entry: the active player took an action — a pass or a card action.

    Attributes
    ----------
    seat : PlayerId
        The seat that acted, recorded so replay can verify the log stays in step with the engine.
    action : Action
        The action taken.
    """

    seat: PlayerId
    action: Action


@dataclass(frozen=True, slots=True)
class Answer:
    """Tape entry: the active player answered the pending decision.

    Attributes
    ----------
    seat : PlayerId
        The seat that answered.
    response : DecisionResponse
        The answer submitted.
    """

    seat: PlayerId
    response: DecisionResponse


GameInput = Act | Answer


@dataclass(slots=True)
class GameLog:
    """An append-only record of a rules-driven game: a start snapshot at the head, then the ordered
    tape of engine inputs. Replay re-runs the engine from the snapshot, feeding each logged input in
    turn — the save format, the replay format, and the netcode are one tape.

    Attributes
    ----------
    initial : InitialRecord
        The dealt table at game start.
    first_player : PlayerId
        The seat that takes the first turn.
    seed : int
        The master RNG seed for deterministic replay. Default 0.
    entries : list of Act or Answer
        The ordered tape of engine inputs. Default empty.
    """

    initial: InitialRecord
    first_player: PlayerId
    seed: int = 0
    entries: list[GameInput] = field(default_factory=list)

    def replay(self) -> GameState:
        """Rebuild the final game state by re-running the engine over the recorded tape."""
        return replay(self)


def build_game(log: GameLog) -> GameState:
    """Rebuild the starting :class:`GameState` from ``log``: its snapshot table, first player, and
    seed, with the first turn's start-of-turn housekeeping already run."""
    game = GameState.start(build_initial_state(log.initial), log.first_player, seed=log.seed)
    flow.begin_game(game)
    return game


def act_and_log(game: GameState, log: GameLog, action: Action) -> None:
    """Perform ``action`` for the active seat and record it. The acting seat is captured first, since
    a pass may hand the turn to the other seat."""
    seat = game.active
    flow.perform(game, action)
    log.entries.append(Act(seat, action))


def submit_and_log(game: GameState, log: GameLog, response: DecisionResponse) -> None:
    """Answer the pending decision and, on success, record it. A rejected answer raises out of
    ``flow.submit`` before anything is recorded, so the tape holds only accepted inputs.

    Raise ``RuntimeError`` if no decision is pending.
    """
    if game.pending is None:
        raise RuntimeError("no decision is pending")
    seat = game.pending.seat
    flow.submit(game, response)
    log.entries.append(Answer(seat, response))


def replay(log: GameLog) -> GameState:
    """Deterministically rebuild the final game state by re-running the engine from the start
    snapshot and feeding each logged input in order. Raise ``ValueError`` if an entry does not match
    the engine's expectation at that point — a desynced or corrupted tape."""
    game = build_game(log)
    for entry in log.entries:
        _apply(game, entry)
    return game


def _apply(game: GameState, entry: GameInput) -> None:
    match entry:
        case Act(seat=seat, action=action):
            if game.active is not seat:
                raise ValueError(
                    f"log out of step: {seat.name} acted but {game.active.name} is active"
                )
            flow.perform(game, action)
        case Answer(seat=seat, response=response):
            pending = game.pending
            if pending is None or pending.seat is not seat:
                raise ValueError(f"log out of step: {seat.name} answered with no matching request")
            flow.submit(game, response)


def game_log_to_dict(log: GameLog) -> dict:
    """Serialize a whole ``GameLog`` — snapshot and tape — to JSON-ready plain data."""
    return {
        "initial": encode_initial(log.initial),
        "first_player": log.first_player.name,
        "seed": log.seed,
        "entries": [_encode_input(entry) for entry in log.entries],
    }


def game_log_from_dict(payload: dict) -> GameLog:
    """Reconstruct a ``GameLog`` from the plain data produced by :func:`game_log_to_dict`."""
    return GameLog(
        initial=decode_initial(payload["initial"]),
        first_player=PlayerId[payload["first_player"]],
        seed=payload["seed"],
        entries=[_decode_input(entry) for entry in payload["entries"]],
    )


def _encode_input(entry: GameInput) -> dict:
    if isinstance(entry, Act):
        return {"kind": "act", "seat": entry.seat.name, "action": _encode_action(entry.action)}
    return {"kind": "answer", "seat": entry.seat.name, "choices": list(entry.response.choices)}


def _decode_input(payload: dict) -> GameInput:
    if payload["kind"] == "act":
        return Act(PlayerId[payload["seat"]], _decode_action(payload["action"]))
    return Answer(PlayerId[payload["seat"]], DecisionResponse(tuple(payload["choices"])))


def _encode_action(action: Action) -> dict:
    if isinstance(action, Pass):
        return {"kind": "pass"}
    return {"kind": "produce_gold", "card_id": action.card_id, "amount": action.amount}


def _decode_action(payload: dict) -> Action:
    if payload["kind"] == "pass":
        return Pass()
    return ProduceGold(payload["card_id"], payload["amount"])
