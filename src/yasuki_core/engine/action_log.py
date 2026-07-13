from dataclasses import dataclass, field
from typing import Literal, Protocol, runtime_checkable
from collections.abc import Sequence

from yasuki_core.engine.players import PlayerId
from yasuki_core.engine.table import TableState
from yasuki_core.engine.intents import Intent, Shuffle, Event, apply_intent
from yasuki_core.engine.serialization import encode_intent, decode_intent
from yasuki_core.engine.snapshot import (
    InitialRecord,
    build_initial_state,
    encode_initial,
    decode_initial,
)


@dataclass(frozen=True, slots=True)
class LogEntry:
    """One accepted intent, stamped for ordering and replay.

    Attributes
    ----------
    seq : int
        The table's version after the intent applied; monotonic across a log.
    ts : float
        Server wall-clock time of acceptance, as a POSIX timestamp. The core never reads the clock
        itself; the caller stamps this.
    seat : PlayerId
        The seat that acted.
    intent : Intent
        The original intent as submitted, not the resolved event.
    rng_seed : int, optional
        The RNG seed carried by the intent, if any (currently only ``SHUFFLE``). Default None.
    """

    seq: int
    ts: float
    seat: PlayerId
    intent: Intent
    rng_seed: int | None = None


@dataclass(frozen=True, slots=True)
class ChatEntry:
    """One chat message on the tape — a record that does not change game state.

    Carried on the same tape as ``LogEntry`` so a replay surfaces each message at the moment it was
    sent, interleaved with the moves. ``replay()`` skips these when folding state.

    Attributes
    ----------
    ts : float
        Server wall-clock time the message was sent, as a POSIX timestamp.
    sender : str
        The display name of the player who sent it.
    text : str
        The message body.
    """

    ts: float
    sender: str
    text: str


@dataclass(frozen=True, slots=True)
class SessionEntry:
    """One session/lifecycle event on the tape — a player joining, leaving, or (un)readying.

    Like ``ChatEntry``, it records who and when without changing game state, so ``replay()`` skips it
    when folding.

    Attributes
    ----------
    ts : float
        Server wall-clock time of the event, as a POSIX timestamp.
    seat : PlayerId or None
        The seat involved, or None if the event is not seat-bound.
    name : str
        The player's display name at the time of the event.
    event : {'join', 'leave', 'ready', 'unready'}
        The lifecycle event.
    """

    ts: float
    seat: PlayerId | None
    name: str
    event: Literal["join", "leave", "ready", "unready"]


@dataclass(slots=True)
class ActionLog:
    """An append-only record of a game: an initial snapshot at the head, then one ordered tape of
    game intents, chat messages, and session events.

    Attributes
    ----------
    initial : InitialRecord
        The start configuration the intents fold onto.
    entries : list of LogEntry or ChatEntry or SessionEntry
        The tape, in send order: accepted intents (``LogEntry``, with non-decreasing ``seq``), chat
        messages (``ChatEntry``), and session events (``SessionEntry``) interleaved. Replay folds the
        intents and skips the rest.
    """

    initial: InitialRecord
    entries: list[LogEntry | ChatEntry | SessionEntry] = field(default_factory=list)

    def append(self, entry: LogEntry | ChatEntry | SessionEntry) -> None:
        """Append ``entry`` to the tape. For an intent entry, enforce non-decreasing ``seq`` against
        the prior intent (raising ``ValueError`` on a regression — an out-of-order or duplicated
        record); chat and session entries carry no seq and append freely."""
        if isinstance(entry, LogEntry):
            last = next((e for e in reversed(self.entries) if isinstance(e, LogEntry)), None)
            if last is not None and entry.seq < last.seq:
                raise ValueError(f"log seq regressed: {entry.seq} after {last.seq}")
        self.entries.append(entry)

    def replay(self) -> TableState:
        """Rebuild the table by folding the tape's intents onto a fresh copy of the initial state."""
        return replay(self.initial, self.entries)


def _intent_seed(intent: Intent) -> int | None:
    return intent.seed if isinstance(intent, Shuffle) else None


def apply_and_log(
    state: TableState, log: ActionLog, seat: PlayerId, intent: Intent, ts: float
) -> list[Event]:
    """Apply ``intent`` and, if accepted, append a ``LogEntry`` for it.

    The recording hook lives in core so every transport records identically. An intent is recorded
    exactly when ``apply_intent`` accepts it (returns at least one event); rejected intents change
    neither the state nor the log.

    Parameters
    ----------
    state : TableState
        The authoritative table, mutated in place on acceptance.
    log : ActionLog
        The log to append to.
    seat : PlayerId
        The acting seat.
    intent : Intent
        The operation to apply.
    ts : float
        Server wall-clock timestamp for the entry, as a POSIX time; the caller reads the clock.
    """
    events = apply_intent(state, seat, intent)
    if events:
        log.append(
            LogEntry(seq=state.seq, ts=ts, seat=seat, intent=intent, rng_seed=_intent_seed(intent))
        )
    return events


def replay(
    initial: InitialRecord, entries: Sequence[LogEntry | ChatEntry | SessionEntry]
) -> TableState:
    """Deterministically rebuild a table from its start and tape.

    Fold each intent entry through ``apply_intent`` onto a fresh state built from ``initial``,
    reproducing the live state bit-for-bit, deck order included. Chat and session entries on the tape
    are skipped — they carry no game state — but their position records when each occurred.

    Parameters
    ----------
    initial : InitialRecord
        The start configuration to fold onto.
    entries : sequence of LogEntry or ChatEntry or SessionEntry
        The ordered tape to fold; only the intent entries apply.
    """
    state = build_initial_state(initial)
    for entry in entries:
        if isinstance(entry, LogEntry):
            apply_intent(state, entry.seat, entry.intent)
    return state


# Plain-dict (JSON-ready) round-trip for the whole log, so a future DB/object-store sink can persist
# a game without reshaping it. The entry wrappers below compose the shared codecs from
# serialization.py and snapshot.py; FlushSink is the attach point.


def _encode_entry(entry: LogEntry | ChatEntry | SessionEntry) -> dict:
    if isinstance(entry, ChatEntry):
        return {"kind": "chat", "ts": entry.ts, "sender": entry.sender, "text": entry.text}
    if isinstance(entry, SessionEntry):
        return {
            "kind": "session",
            "ts": entry.ts,
            "seat": None if entry.seat is None else entry.seat.name,
            "name": entry.name,
            "event": entry.event,
        }
    return {
        "kind": "intent",
        "seq": entry.seq,
        "ts": entry.ts,
        "seat": entry.seat.name,
        "intent": encode_intent(entry.intent),
        "rng_seed": entry.rng_seed,
    }


def _decode_entry(payload: dict) -> LogEntry | ChatEntry | SessionEntry:
    if payload.get("kind") == "chat":
        return ChatEntry(ts=payload["ts"], sender=payload["sender"], text=payload["text"])
    if payload.get("kind") == "session":
        seat = payload["seat"]
        return SessionEntry(
            ts=payload["ts"],
            seat=None if seat is None else PlayerId[seat],
            name=payload["name"],
            event=payload["event"],
        )
    return LogEntry(
        seq=payload["seq"],
        ts=payload["ts"],
        seat=PlayerId[payload["seat"]],
        intent=decode_intent(payload["intent"]),
        rng_seed=payload.get("rng_seed"),
    )


def action_log_to_dict(log: ActionLog) -> dict:
    """Serialize a whole ``ActionLog`` — initial record and entries — to JSON-ready plain data."""
    return {
        "initial": encode_initial(log.initial),
        "entries": [_encode_entry(entry) for entry in log.entries],
    }


def action_log_from_dict(payload: dict) -> ActionLog:
    """Reconstruct an ``ActionLog`` from the plain data produced by ``action_log_to_dict``."""
    return ActionLog(
        initial=decode_initial(payload["initial"]),
        entries=[_decode_entry(entry) for entry in payload["entries"]],
    )


@runtime_checkable
class FlushSink(Protocol):
    """Where a persisted log lands. A future DB or object-store backend implements ``write`` to
    accept the plain-dict payload from ``action_log_to_dict``. No concrete sink ships yet."""

    def write(self, payload: dict) -> None: ...


def flush(log: ActionLog, sink: FlushSink) -> None:
    """Serialize ``log`` and hand it to ``sink``. The single attach point for persistence; with no
    sink wired in the runtime, nothing calls this yet."""
    sink.write(action_log_to_dict(log))
