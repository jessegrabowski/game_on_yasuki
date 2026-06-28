from dataclasses import dataclass, field, replace
from typing import Literal, Protocol, runtime_checkable
from collections.abc import Sequence

from yasuki_core.engine.players import PlayerId
from yasuki_core.engine.zones import ProvinceZone
from yasuki_core.engine.table import (
    TableState,
    SeatInfo,
    ZoneKey,
    DeckKey,
    BoardPos,
)
from yasuki_core.engine.intents import Intent, Shuffle, Event, apply_intent
from yasuki_core.engine.serialization import (
    encode_card,
    decode_card,
    encode_zone_key,
    decode_zone_key,
    encode_deck_key,
    decode_deck_key,
    encode_seat,
    decode_seat,
    encode_intent,
    decode_intent,
    encode_attach_target,
    decode_attach_target,
)
from yasuki_core.game_pieces.cards import L5RCard


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
class InitialRecord:
    """A complete table snapshot that seeds a replay.

    Captures the full state at the log head — seats, every owned zone and deck with its ordered
    contents, and the battlefield with positions — so a replay rebuilds the table exactly and then
    folds the recorded intents onto it.

    Attributes
    ----------
    seats : dict mapping PlayerId to SeatInfo
        Each seat's status (name, honor, ready, connected).
    decklists : dict mapping DeckKey to list of L5RCard
        The ordered contents of each fate and dynasty deck.
    zones : dict mapping ZoneKey to list of L5RCard
        The contents of every owned zone, including provinces.
    battlefield : list of L5RCard
        The shared battlefield's cards.
    positions : dict mapping str to BoardPos
        Battlefield card positions, keyed by card id.
    attachments : dict mapping str to (str or ZoneKey)
        The attachment graph, keyed by attached card id, mapping to a parent card id or province.
    setup_seeds : dict mapping str to int
        Named RNG seeds used during setup that no logged intent carries.
    """

    seats: dict[PlayerId, SeatInfo]
    decklists: dict[DeckKey, list[L5RCard]]
    zones: dict[ZoneKey, list[L5RCard]] = field(default_factory=dict)
    battlefield: list[L5RCard] = field(default_factory=list)
    positions: dict[str, BoardPos] = field(default_factory=dict)
    attachments: dict[str, str | ZoneKey] = field(default_factory=dict)
    setup_seeds: dict[str, int] = field(default_factory=dict)

    @classmethod
    def from_state(
        cls, state: TableState, setup_seeds: dict[str, int] | None = None
    ) -> "InitialRecord":
        """Snapshot ``state`` into an initial record, deep-copying every card so later in-place
        mutation of the live table never touches the snapshot.

        Parameters
        ----------
        state : TableState
            The table to capture.
        setup_seeds : dict mapping str to int, optional
            Named setup seeds to record. Default empty.
        """
        return cls(
            seats={pid: replace(info) for pid, info in state.seats.items()},
            decklists={
                key: [replace(card) for card in deck.cards] for key, deck in state.decks.items()
            },
            zones={
                key: [replace(card) for card in zone.cards] for key, zone in state.zones.items()
            },
            battlefield=[replace(card) for card in state.battlefield.cards],
            positions=dict(state.positions),
            attachments=dict(state.attachments),
            setup_seeds=dict(setup_seeds or {}),
        )


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


def build_initial_state(initial: InitialRecord) -> TableState:
    """Rebuild a full ``TableState`` from an initial record: the recorded seats, decks, zones,
    battlefield, and positions, with every card deep-copied so the record stays pristine and
    repeated builds are independent."""
    state = TableState.empty_two_seat()
    for pid, info in initial.seats.items():
        state.seats[pid] = replace(info)
    for key, cards in initial.decklists.items():
        state.decks[key].cards = _restore_cards(state, cards)
    for key, cards in initial.zones.items():
        zone = state.zones.get(key)
        if zone is None:
            zone = ProvinceZone(owner=key.owner)  # provinces are the only on-demand zone
            state.zones[key] = zone
        zone.cards = _restore_cards(state, cards)
    state.battlefield.cards = _restore_cards(state, initial.battlefield)
    state.positions = dict(initial.positions)
    state.attachments = dict(initial.attachments)
    return state


def _restore_cards(state: TableState, cards: list[L5RCard]) -> list[L5RCard]:
    copied = [replace(card) for card in cards]
    for card in copied:
        state.cards_by_id[card.id] = card
    return copied


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
# a game without reshaping it. The entry/initial wrappers below compose the shared value codecs from
# serialization.py; FlushSink is the attach point.


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


def _encode_initial(initial: InitialRecord) -> dict:
    return {
        "seats": [
            {"seat": pid.name, "info": encode_seat(info)} for pid, info in initial.seats.items()
        ],
        "decklists": [
            {"deck": encode_deck_key(key), "cards": [encode_card(card) for card in cards]}
            for key, cards in initial.decklists.items()
        ],
        "zones": [
            {"zone": encode_zone_key(key), "cards": [encode_card(card) for card in cards]}
            for key, cards in initial.zones.items()
        ],
        "battlefield": [encode_card(card) for card in initial.battlefield],
        "positions": {card_id: [pos.x, pos.y] for card_id, pos in initial.positions.items()},
        "attachments": {
            card_id: encode_attach_target(target)
            for card_id, target in initial.attachments.items()
        },
        "setup_seeds": dict(initial.setup_seeds),
    }


def _decode_initial(payload: dict) -> InitialRecord:
    seats = {PlayerId[item["seat"]]: decode_seat(item["info"]) for item in payload["seats"]}
    decklists = {
        decode_deck_key(item["deck"]): [decode_card(card) for card in item["cards"]]
        for item in payload["decklists"]
    }
    zones = {
        decode_zone_key(item["zone"]): [decode_card(card) for card in item["cards"]]
        for item in payload["zones"]
    }
    battlefield = [decode_card(card) for card in payload["battlefield"]]
    positions = {card_id: BoardPos(*xy) for card_id, xy in payload["positions"].items()}
    attachments = {
        card_id: decode_attach_target(target)
        for card_id, target in payload.get("attachments", {}).items()
    }
    return InitialRecord(
        seats=seats,
        decklists=decklists,
        zones=zones,
        battlefield=battlefield,
        positions=positions,
        attachments=attachments,
        setup_seeds=dict(payload["setup_seeds"]),
    )


def action_log_to_dict(log: ActionLog) -> dict:
    """Serialize a whole ``ActionLog`` — initial record and entries — to JSON-ready plain data."""
    return {
        "initial": _encode_initial(log.initial),
        "entries": [_encode_entry(entry) for entry in log.entries],
    }


def action_log_from_dict(payload: dict) -> ActionLog:
    """Reconstruct an ``ActionLog`` from the plain data produced by ``action_log_to_dict``."""
    return ActionLog(
        initial=_decode_initial(payload["initial"]),
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
