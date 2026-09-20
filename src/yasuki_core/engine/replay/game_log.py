from dataclasses import dataclass, field

from yasuki_core.engine.debug import (
    DebugCard,
    DebugGold,
    DebugPersonality,
    DebugStep,
    apply_debug,
)
from yasuki_core.engine.players import PlayerId
from yasuki_core.engine.replay.serialization import decode_print, encode_print
from yasuki_core.engine.replay.snapshot import (
    InitialRecord,
    build_initial_state,
    encode_initial,
    decode_initial,
)
from yasuki_core.engine.rules.state import GameState
from yasuki_core.engine.rules.vocabulary.actions import (
    Action,
    ActivateAbility,
    Cycle,
    DeclareAttack,
    DiscardToInterrupt,
    DynastyDiscard,
    Equip,
    KharmicDraw,
    KharmicRefill,
    Inheritance,
    Legacy,
    Lobby,
    Pass,
    PlayInterrupt,
    UseFavorAbility,
    PlayStrategy,
    Recruit,
)
from yasuki_core.engine.rules.vocabulary.decisions import DecisionResponse
from yasuki_core.engine.rules.turn import action_sequence, sequence


@dataclass(frozen=True, slots=True)
class Act:
    """Tape entry: the active player took an action (a pass or a card action).

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


@dataclass(frozen=True, slots=True)
class Cancel:
    """Tape entry: the active player backed out of the pending decision, undoing the action that
    raised it.

    Attributes
    ----------
    seat : PlayerId
        The seat that cancelled.
    """

    seat: PlayerId


@dataclass(frozen=True, slots=True)
class Debug:
    """Tape entry: a developer put Gold or a card on the table from nowhere. Recorded so the game
    still replays to itself. Only a debug client writes one.

    Attributes
    ----------
    seat : PlayerId
        The seat the step was taken for.
    step : DebugGold, DebugCard or DebugPersonality
        What was put where.
    """

    seat: PlayerId
    step: DebugStep


GameInput = Act | Answer | Cancel | Debug


@dataclass(slots=True)
class GameLog:
    """An append-only record of a rules-driven game: a start snapshot at the head, then the ordered
    tape of engine inputs. Replay re-runs the engine from the snapshot, feeding each logged input in
    turn. The save format, the replay format, and the netcode are one tape.

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
    """Rebuild the starting :class:`~.GameState` from ``log``: its snapshot table, first player, and
    seed, with the first turn's start-of-turn housekeeping already run."""
    game = GameState.start(build_initial_state(log.initial), log.first_player, seed=log.seed)
    sequence.begin_game(game)
    return game


def act_and_log(game: GameState, log: GameLog, action: Action) -> None:
    """Perform ``action`` for the seat holding the opportunity and record it. The acting seat is
    captured first, since the action hands the opportunity on and may end the turn."""
    seat = game.round.priority
    action_sequence.perform(game, action)
    log.entries.append(Act(seat, action))


def submit_and_log(game: GameState, log: GameLog, response: DecisionResponse) -> None:
    """Answer the pending decision and, on success, record it. A rejected answer raises out of
    ``action_sequence.submit`` before anything is recorded, so the tape holds only accepted inputs.

    Raise ``RuntimeError`` if no decision is pending.
    """
    if game.pending is None:
        raise RuntimeError("no decision is pending")
    seat = game.pending.seat
    action_sequence.submit(game, response)
    log.entries.append(Answer(seat, response))


def debug_and_log(game: GameState, log: GameLog, step: DebugStep) -> None:
    """Apply a developer's step and, on success, record it."""
    apply_debug(game, step)
    log.entries.append(Debug(step.seat, step))


def cancel_and_log(game: GameState, log: GameLog) -> None:
    """Cancel the pending decision and, on success, record it. A decision that cannot be cancelled
    raises out of ``action_sequence.cancel`` before anything is recorded, so the tape holds only
    accepted inputs.

    Raise ``RuntimeError`` if no decision is pending.
    """
    if game.pending is None:
        raise RuntimeError("no decision is pending")
    seat = game.pending.seat
    action_sequence.cancel(game)
    log.entries.append(Cancel(seat))


def replay(log: GameLog) -> GameState:
    """Deterministically rebuild the final game state by re-running the engine from the start
    snapshot and feeding each logged input in order. Raise ``ValueError`` if an entry does not match
    the engine's expectation at that point (a desynced or corrupted tape)."""
    game = build_game(log)
    for entry in log.entries:
        _apply(game, entry)
    return game


def _apply(game: GameState, entry: GameInput) -> None:
    match entry:
        case Act(seat=seat, action=action):
            if game.round.priority is not seat:
                raise ValueError(
                    f"log out of step: {seat.name} acted but the opportunity is "
                    f"{game.round.priority.name}'s"
                )
            action_sequence.perform(game, action)
        case Answer(seat=seat, response=response):
            pending = game.pending
            if pending is None or pending.seat is not seat:
                raise ValueError(f"log out of step: {seat.name} answered with no matching request")
            action_sequence.submit(game, response)
        case Cancel(seat=seat):
            pending = game.pending
            if pending is None or pending.seat is not seat:
                raise ValueError(f"log out of step: {seat.name} cancelled with no matching request")
            action_sequence.cancel(game)
        case Debug(step=step):
            apply_debug(game, step)


def game_log_to_dict(log: GameLog) -> dict:
    """Serialize a whole ``GameLog`` (snapshot and tape) to JSON-ready plain data."""
    return {
        "initial": encode_initial(log.initial),
        "first_player": log.first_player.name,
        "seed": log.seed,
        "entries": [_encode_input(entry) for entry in log.entries],
    }


def game_log_from_dict(payload: dict) -> GameLog:
    """Reconstruct a ``GameLog`` from the plain data produced by :func:`~.game_log_to_dict`."""
    return GameLog(
        initial=decode_initial(payload["initial"]),
        first_player=PlayerId[payload["first_player"]],
        seed=payload["seed"],
        entries=[_decode_input(entry) for entry in payload["entries"]],
    )


def _encode_input(entry: GameInput) -> dict:
    if isinstance(entry, Act):
        return {"kind": "act", "seat": entry.seat.name, "action": _encode_action(entry.action)}
    if isinstance(entry, Answer):
        return {
            "kind": "answer",
            "seat": entry.seat.name,
            "choices": list(entry.response.choices),
        }
    if isinstance(entry, Debug):
        return {"kind": "debug", "seat": entry.seat.name, "step": _encode_debug(entry.step)}
    return {"kind": "cancel", "seat": entry.seat.name}


def _encode_debug(step: DebugStep) -> dict:
    """The step without its seat, which the entry around it carries."""
    match step:
        case DebugGold(amount=amount):
            return {"kind": "gold", "amount": amount}
        case DebugCard(card_id=card_id, printed=printed):
            return {"kind": "card", "card_id": card_id, "printed": encode_print(printed)}
        case DebugPersonality(card_id=card_id, printed=printed):
            return {"kind": "personality", "card_id": card_id, "printed": encode_print(printed)}
    raise ValueError(f"no encoding for debug step {type(step).__name__}")


def _decode_debug(seat: PlayerId, payload: dict) -> DebugStep:
    match payload["kind"]:
        case "gold":
            return DebugGold(seat, payload["amount"])
        case "card":
            return DebugCard(seat, payload["card_id"], decode_print(payload["printed"]))
        case "personality":
            return DebugPersonality(seat, payload["card_id"], decode_print(payload["printed"]))
    raise ValueError(f"no debug step of kind {payload['kind']!r}")


def _decode_input(payload: dict) -> GameInput:
    if payload["kind"] == "act":
        return Act(PlayerId[payload["seat"]], _decode_action(payload["action"]))
    if payload["kind"] == "answer":
        return Answer(PlayerId[payload["seat"]], DecisionResponse(tuple(payload["choices"])))
    if payload["kind"] == "debug":
        seat = PlayerId[payload["seat"]]
        return Debug(seat, _decode_debug(seat, payload["step"]))
    return Cancel(PlayerId[payload["seat"]])


def _encode_action(action: Action) -> dict:
    match action:
        case Pass():
            return {"kind": "pass"}
        case Recruit(card_id=card_id, invest=invest, proclaim=proclaim):
            return {"kind": "recruit", "card_id": card_id, "invest": invest, "proclaim": proclaim}
        case Equip(card_id=card_id, invest=invest):
            return {"kind": "equip", "card_id": card_id, "invest": invest}
        case DynastyDiscard(card_id=card_id):
            return {"kind": "dynasty_discard", "card_id": card_id}
        case Legacy():
            return {"kind": "legacy"}
        case Inheritance():
            return {"kind": "inheritance"}
        case Cycle():
            return {"kind": "cycle"}
        case Lobby():
            return {"kind": "lobby"}
        case UseFavorAbility(key=key):
            return {"kind": "use_favor_ability", "key": key}
        case KharmicDraw(card_id=card_id):
            return {"kind": "kharmic_draw", "card_id": card_id}
        case KharmicRefill(card_id=card_id):
            return {"kind": "kharmic_refill", "card_id": card_id}
        case ActivateAbility(card_id=card_id):
            return {"kind": "activate_ability", "card_id": card_id}
        case PlayStrategy(card_id=card_id):
            return {"kind": "play_strategy", "card_id": card_id}
        case DeclareAttack():
            return {"kind": "declare_attack"}
        case PlayInterrupt(card_id=card_id):
            return {"kind": "play_interrupt", "card_id": card_id}
        case DiscardToInterrupt(card_id=card_id, key=key):
            return {"kind": "discard_to_interrupt", "card_id": card_id, "key": key}
    raise ValueError(f"no encoding for action {action!r}")


def _decode_action(payload: dict) -> Action:
    kind = payload["kind"]
    if kind == "pass":
        return Pass()
    if kind == "recruit":
        return Recruit(
            payload["card_id"],
            invest=payload.get("invest", False),
            proclaim=payload.get("proclaim", False),
        )
    if kind == "equip":
        return Equip(payload["card_id"], invest=payload.get("invest", False))
    if kind == "dynasty_discard":
        return DynastyDiscard(payload["card_id"])
    if kind == "legacy":
        return Legacy()
    if kind == "inheritance":
        return Inheritance()
    if kind == "cycle":
        return Cycle()
    if kind == "lobby":
        return Lobby()
    if kind == "use_favor_ability":
        return UseFavorAbility(payload["key"])
    if kind == "kharmic_draw":
        return KharmicDraw(payload["card_id"])
    if kind == "kharmic_refill":
        return KharmicRefill(payload["card_id"])
    if kind == "activate_ability":
        return ActivateAbility(payload["card_id"])
    if kind == "play_strategy":
        return PlayStrategy(payload["card_id"])
    if kind == "declare_attack":
        return DeclareAttack()
    if kind == "play_interrupt":
        return PlayInterrupt(payload["card_id"])
    if kind == "discard_to_interrupt":
        return DiscardToInterrupt(payload["card_id"], payload["key"])
    raise ValueError(f"unknown action kind {kind!r}")
