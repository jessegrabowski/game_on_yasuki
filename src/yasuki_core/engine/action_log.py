from dataclasses import dataclass, field, fields, replace
from enum import Enum
from pathlib import Path
from typing import Literal, Protocol, runtime_checkable
from collections.abc import Sequence

from yasuki_core.engine.players import PlayerId
from yasuki_core.engine.zones import ProvinceZone
from yasuki_core.engine.table import (
    TableState,
    SeatInfo,
    ZoneKey,
    ZoneRole,
    DeckKey,
    BoardPos,
    BATTLEFIELD,
)
from yasuki_core.engine.intents import (
    IntentOp,
    Intent,
    MoveCard,
    MoveDeckTop,
    SetCardPos,
    SetCardPositions,
    ReorderHand,
    ReorderPile,
    Raise,
    CardFlagIntent,
    Bow,
    Unbow,
    Flip,
    FlipFace,
    Invert,
    Show,
    Unshow,
    Peek,
    Unpeek,
    Draw,
    Shuffle,
    FlipDeckTop,
    SearchDeck,
    FillProvince,
    DestroyProvince,
    DiscardProvince,
    CreateProvince,
    SetHonor,
    SetNote,
    GiveControl,
    SpawnCard,
    RemoveCard,
    Event,
    apply_intent,
)
from yasuki_core.game_pieces.cards import L5RCard
from yasuki_core.game_pieces.constants import Side, Element, Timing, AttachmentType
from yasuki_core.game_pieces.dynasty import (
    DynastyCard,
    DynastyPersonality,
    DynastyHolding,
    DynastyEvent,
    DynastyRegion,
    DynastyCelestial,
)
from yasuki_core.game_pieces.fate import (
    FateCard,
    FateAction,
    FateAttachment,
    FateRing,
    FateAncestor,
)
from yasuki_core.game_pieces.pregame import StrongholdCard, SenseiCard, WindCard


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
    creatable_tokens : dict mapping str to L5RCard
        Token templates the loaded decks can create, keyed by token card id, so a replayed token
        spawn resolves against the same templates without a database call.
    setup_seeds : dict mapping str to int
        Named RNG seeds used during setup that no logged intent carries.
    """

    seats: dict[PlayerId, SeatInfo]
    decklists: dict[DeckKey, list[L5RCard]]
    zones: dict[ZoneKey, list[L5RCard]] = field(default_factory=dict)
    battlefield: list[L5RCard] = field(default_factory=list)
    positions: dict[str, BoardPos] = field(default_factory=dict)
    creatable_tokens: dict[str, L5RCard] = field(default_factory=dict)
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
            creatable_tokens={tid: replace(card) for tid, card in state.creatable_tokens.items()},
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
    state.creatable_tokens = {tid: replace(card) for tid, card in initial.creatable_tokens.items()}
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
# a game without reshaping it. No live sink ships; FlushSink below is the attach point.

_ENUM_REGISTRY: dict[str, type[Enum]] = {
    cls.__name__: cls for cls in (Side, Element, Timing, AttachmentType, PlayerId)
}

_CARD_REGISTRY: dict[str, type[L5RCard]] = {
    cls.__name__: cls
    for cls in (
        L5RCard,
        FateCard,
        FateAction,
        FateAttachment,
        FateRing,
        DynastyCard,
        DynastyPersonality,
        DynastyHolding,
        DynastyEvent,
        DynastyRegion,
        DynastyCelestial,
        FateAncestor,
        StrongholdCard,
        SenseiCard,
        WindCard,
    )
}

_FLAG_CLASSES: dict[IntentOp, type[CardFlagIntent]] = {
    IntentOp.BOW: Bow,
    IntentOp.UNBOW: Unbow,
    IntentOp.FLIP: Flip,
    IntentOp.FLIP_FACE: FlipFace,
    IntentOp.INVERT: Invert,
}

# Single-card intents whose only payload is the target card id.
_CARD_ID_CLASSES: dict[IntentOp, type] = {
    IntentOp.SHOW: Show,
    IntentOp.UNSHOW: Unshow,
    IntentOp.PEEK: Peek,
    IntentOp.UNPEEK: Unpeek,
    IntentOp.GIVE_CONTROL: GiveControl,
}


def _encode_value(value):
    # Enum first: Side/Element/Timing are str-Enums, so the primitive check below would otherwise
    # flatten them to bare strings and lose the type on a JSON round-trip.
    if isinstance(value, Enum):
        return {"__enum__": type(value).__name__, "value": value.value}
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    if isinstance(value, Path):
        return {"__path__": str(value)}
    if isinstance(value, tuple):
        return {"__tuple__": [_encode_value(item) for item in value]}
    if isinstance(value, frozenset):
        return {"__frozenset__": [_encode_value(item) for item in value]}
    if isinstance(value, L5RCard):
        return {"__card__": _encode_card(value)}
    raise TypeError(f"cannot serialize card field of type {type(value).__name__}")


def _decode_value(value):
    if isinstance(value, dict):
        if "__enum__" in value:
            return _ENUM_REGISTRY[value["__enum__"]](value["value"])
        if "__path__" in value:
            return Path(value["__path__"])
        if "__tuple__" in value:
            return tuple(_decode_value(item) for item in value["__tuple__"])
        if "__frozenset__" in value:
            return frozenset(_decode_value(item) for item in value["__frozenset__"])
        if "__card__" in value:
            return _decode_card(value["__card__"])
    return value


def _encode_card(card: L5RCard) -> dict:
    payload = {"__type__": type(card).__name__}
    for f in fields(card):
        payload[f.name] = _encode_value(getattr(card, f.name))
    return payload


def _decode_card(payload: dict) -> L5RCard:
    cls = _CARD_REGISTRY[payload["__type__"]]
    kwargs = {key: _decode_value(value) for key, value in payload.items() if key != "__type__"}
    return cls(**kwargs)


def _encode_zone_key(key: ZoneKey) -> dict:
    return {"owner": key.owner.name, "role": key.role.value, "idx": key.idx}


def _decode_zone_key(payload: dict) -> ZoneKey:
    return ZoneKey(PlayerId[payload["owner"]], ZoneRole(payload["role"]), payload["idx"])


def _encode_deck_key(key: DeckKey) -> dict:
    return {"owner": key.owner.name, "side": key.side.value}


def _decode_deck_key(payload: dict) -> DeckKey:
    return DeckKey(PlayerId[payload["owner"]], Side(payload["side"]))


def _encode_move_dest(dest) -> dict:
    if dest == BATTLEFIELD:
        return {"kind": "battlefield"}
    if isinstance(dest, DeckKey):
        return {"kind": "deck", "deck": _encode_deck_key(dest)}
    return {"kind": "zone", "zone": _encode_zone_key(dest)}


def _decode_move_dest(payload: dict):
    kind = payload["kind"]
    if kind == "battlefield":
        return BATTLEFIELD
    if kind == "deck":
        return _decode_deck_key(payload["deck"])
    return _decode_zone_key(payload["zone"])


def encode_intent(intent: Intent) -> dict:
    """Encode an ``Intent`` to JSON-ready plain data (op + targets). The canonical intent wire shape,
    shared by the persisted log and the live wire protocol."""
    payload: dict = {"op": intent.op.value}
    match intent.op:
        case IntentOp.MOVE_CARD:
            payload["card_id"] = intent.card_id
            payload["to"] = _encode_move_dest(intent.to)
            payload["position"] = (
                None if intent.position is None else [intent.position.x, intent.position.y]
            )
            payload["to_bottom"] = intent.to_bottom
            payload["value"] = intent.index  # the hand-slot index, when landing in a hand
        case IntentOp.MOVE_DECK_TOP:
            payload["deck"] = _encode_deck_key(intent.deck)
            payload["to"] = _encode_move_dest(intent.to)
            payload["position"] = (
                None if intent.position is None else [intent.position.x, intent.position.y]
            )
        case IntentOp.SET_CARD_POS:
            payload |= {"card_id": intent.card_id, "x": intent.x, "y": intent.y}
        case IntentOp.SET_CARD_POSITIONS:
            payload["moves"] = [[card_id, x, y] for card_id, x, y in intent.moves]
        case IntentOp.REORDER_HAND:
            payload |= {"card_id": intent.card_id, "value": intent.index}
        case IntentOp.REORDER_PILE:
            payload |= {
                "to": _encode_move_dest(intent.pile),
                "card_id": intent.card_id,
                "value": intent.index,
            }
        case IntentOp.RAISE:
            payload["card_id"] = intent.card_id
        case IntentOp.SET_NOTE:
            payload |= {"card_id": intent.card_id, "text": intent.note}
        case IntentOp.BOW | IntentOp.UNBOW | IntentOp.FLIP | IntentOp.FLIP_FACE | IntentOp.INVERT:
            payload["card_ids"] = list(intent.card_ids)
        case (
            IntentOp.SHOW
            | IntentOp.UNSHOW
            | IntentOp.PEEK
            | IntentOp.UNPEEK
            | IntentOp.GIVE_CONTROL
        ):
            payload["card_id"] = intent.card_id
        case IntentOp.DRAW:
            payload["deck"] = _encode_deck_key(intent.deck)
        case IntentOp.SEARCH_DECK:
            payload["deck"] = _encode_deck_key(intent.deck)
            payload["value"] = intent.limit
        case IntentOp.SHUFFLE:
            payload["deck"] = _encode_deck_key(intent.deck)
            payload["seed"] = intent.seed
        case IntentOp.FLIP_DECK_TOP:
            payload["deck"] = _encode_deck_key(intent.deck)
        case IntentOp.FILL_PROVINCE | IntentOp.DESTROY_PROVINCE | IntentOp.DISCARD_PROVINCE:
            payload["zone"] = _encode_zone_key(intent.zone)
        case IntentOp.CREATE_PROVINCE:
            pass
        case IntentOp.SET_HONOR:
            payload |= {"delta": intent.delta, "value": intent.value}
        case IntentOp.SPAWN_CARD:
            payload |= {
                "card_id": intent.card_id,
                "token_id": intent.token_id,
                "source_card_id": intent.source_card_id,
                "card": _encode_card(intent.card) if intent.card is not None else None,
                "position": [intent.position.x, intent.position.y],
            }
        case IntentOp.REMOVE_CARD:
            payload["card_id"] = intent.card_id
        case _:
            raise ValueError(f"unhandled intent op: {intent.op}")
    return payload


def decode_intent(payload: dict) -> Intent:
    """Rebuild an ``Intent`` from the plain data produced by ``encode_intent``. Raises ``KeyError`` /
    ``ValueError`` on a malformed payload; callers handling untrusted input should validate the
    envelope first and treat a raised error as a rejected message."""
    op = IntentOp(payload["op"])
    match op:
        case IntentOp.MOVE_CARD:
            position = payload["position"]
            return MoveCard(
                payload["card_id"],
                _decode_move_dest(payload["to"]),
                None if position is None else BoardPos(*position),
                to_bottom=payload.get("to_bottom", False),
                index=payload.get("value"),
            )
        case IntentOp.MOVE_DECK_TOP:
            position = payload.get("position")
            return MoveDeckTop(
                _decode_deck_key(payload["deck"]),
                _decode_move_dest(payload["to"]),
                None if position is None else BoardPos(*position),
            )
        case IntentOp.SET_CARD_POS:
            return SetCardPos(payload["card_id"], payload["x"], payload["y"])
        case IntentOp.SET_CARD_POSITIONS:
            return SetCardPositions(tuple((m[0], m[1], m[2]) for m in payload["moves"]))
        case IntentOp.REORDER_HAND:
            return ReorderHand(payload["card_id"], payload["value"])
        case IntentOp.REORDER_PILE:
            return ReorderPile(
                _decode_move_dest(payload["to"]), payload["card_id"], payload["value"]
            )
        case IntentOp.RAISE:
            return Raise(payload["card_id"])
        case IntentOp.SET_NOTE:
            return SetNote(payload["card_id"], payload.get("text"))
        case IntentOp.BOW | IntentOp.UNBOW | IntentOp.FLIP | IntentOp.FLIP_FACE | IntentOp.INVERT:
            return _FLAG_CLASSES[op](tuple(payload["card_ids"]))
        case (
            IntentOp.SHOW
            | IntentOp.UNSHOW
            | IntentOp.PEEK
            | IntentOp.UNPEEK
            | IntentOp.GIVE_CONTROL
        ):
            return _CARD_ID_CLASSES[op](payload["card_id"])
        case IntentOp.DRAW:
            return Draw(_decode_deck_key(payload["deck"]))
        case IntentOp.SEARCH_DECK:
            return SearchDeck(_decode_deck_key(payload["deck"]), limit=payload.get("value"))
        case IntentOp.SHUFFLE:
            return Shuffle(_decode_deck_key(payload["deck"]), payload["seed"])
        case IntentOp.FLIP_DECK_TOP:
            return FlipDeckTop(_decode_deck_key(payload["deck"]))
        case IntentOp.FILL_PROVINCE:
            return FillProvince(_decode_zone_key(payload["zone"]))
        case IntentOp.DESTROY_PROVINCE:
            return DestroyProvince(_decode_zone_key(payload["zone"]))
        case IntentOp.DISCARD_PROVINCE:
            return DiscardProvince(_decode_zone_key(payload["zone"]))
        case IntentOp.CREATE_PROVINCE:
            return CreateProvince()
        case IntentOp.SET_HONOR:
            return SetHonor(delta=payload["delta"], value=payload["value"])
        case IntentOp.SPAWN_CARD:
            encoded_card = payload.get("card")
            return SpawnCard(
                card_id=payload["card_id"],
                position=BoardPos(*payload["position"]),
                token_id=payload.get("token_id"),
                source_card_id=payload.get("source_card_id"),
                card=_decode_card(encoded_card) if encoded_card else None,
            )
        case IntentOp.REMOVE_CARD:
            return RemoveCard(payload["card_id"])
        case _:
            raise ValueError(f"unhandled intent op: {op}")


def _encode_seat(info: SeatInfo) -> dict:
    return {
        "name": info.name,
        "honor": info.honor,
        "ready": info.ready,
        "connected": info.connected,
    }


def _decode_seat(payload: dict) -> SeatInfo:
    return SeatInfo(**payload)


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
            {"seat": pid.name, "info": _encode_seat(info)} for pid, info in initial.seats.items()
        ],
        "decklists": [
            {"deck": _encode_deck_key(key), "cards": [_encode_card(card) for card in cards]}
            for key, cards in initial.decklists.items()
        ],
        "zones": [
            {"zone": _encode_zone_key(key), "cards": [_encode_card(card) for card in cards]}
            for key, cards in initial.zones.items()
        ],
        "battlefield": [_encode_card(card) for card in initial.battlefield],
        "positions": {card_id: [pos.x, pos.y] for card_id, pos in initial.positions.items()},
        "creatable_tokens": {
            tid: _encode_card(card) for tid, card in initial.creatable_tokens.items()
        },
        "setup_seeds": dict(initial.setup_seeds),
    }


def _decode_initial(payload: dict) -> InitialRecord:
    seats = {PlayerId[item["seat"]]: _decode_seat(item["info"]) for item in payload["seats"]}
    decklists = {
        _decode_deck_key(item["deck"]): [_decode_card(card) for card in item["cards"]]
        for item in payload["decklists"]
    }
    zones = {
        _decode_zone_key(item["zone"]): [_decode_card(card) for card in item["cards"]]
        for item in payload["zones"]
    }
    battlefield = [_decode_card(card) for card in payload["battlefield"]]
    positions = {card_id: BoardPos(*xy) for card_id, xy in payload["positions"].items()}
    creatable_tokens = {
        tid: _decode_card(card) for tid, card in payload.get("creatable_tokens", {}).items()
    }
    return InitialRecord(
        seats=seats,
        decklists=decklists,
        zones=zones,
        battlefield=battlefield,
        positions=positions,
        creatable_tokens=creatable_tokens,
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
