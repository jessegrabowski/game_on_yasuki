from enum import Enum
from pathlib import Path
from dataclasses import fields

from yasuki_core.engine.players import PlayerId
from yasuki_core.engine.table import (
    SeatInfo,
    ZoneKey,
    ZoneRole,
    DeckKey,
    BoardPos,
    MoveDest,
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
    AdjustCounter,
    GiveControl,
    SpawnCard,
    RemoveCard,
    Attach,
    Detach,
    FlipCoin,
    RollDice,
)
from yasuki_core.game_pieces.cards import L5RCard
from yasuki_core.game_pieces.constants import Side, Element, Timing, AttachmentType
from yasuki_core.game_pieces.counters import counter_from_key
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

# The shared JSON codec: plain-dict (JSON-ready) round-trips for the engine's value types — cards,
# zone/deck keys, seats, and intents. One canonical wire shape, consumed by the persisted action
# log, the live web protocol, and the rules-engine plumbing (decisions, game log, projection), so
# no two of them can drift apart.

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
    if isinstance(value, dict):
        if not all(isinstance(key, str) for key in value):
            raise TypeError("card dict fields need str keys; JSON would silently coerce others")
        return {"__dict__": {key: _encode_value(item) for key, item in value.items()}}
    if isinstance(value, L5RCard):
        return {"__card__": encode_card(value)}
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
        if "__dict__" in value:
            return {key: _decode_value(item) for key, item in value["__dict__"].items()}
        if "__card__" in value:
            return decode_card(value["__card__"])
    return value


def encode_card(card: L5RCard) -> dict:
    """Encode an ``L5RCard`` (any subclass) to JSON-ready plain data, tagged with its concrete type
    so ``decode_card`` rebuilds the same class."""
    payload = {"__type__": type(card).__name__}
    for f in fields(card):
        payload[f.name] = _encode_value(getattr(card, f.name))
    return payload


def decode_card(payload: dict) -> L5RCard:
    """Rebuild the card encoded by ``encode_card``, dispatching on its ``__type__`` tag."""
    cls = _CARD_REGISTRY[payload["__type__"]]
    kwargs = {key: _decode_value(value) for key, value in payload.items() if key != "__type__"}
    return cls(**kwargs)


def encode_zone_key(key: ZoneKey) -> dict:
    """Encode a ``ZoneKey`` to JSON-ready plain data."""
    return {"owner": key.owner.name, "role": key.role.value, "idx": key.idx}


def decode_zone_key(payload: dict) -> ZoneKey:
    """Rebuild the ``ZoneKey`` encoded by ``encode_zone_key``."""
    return ZoneKey(PlayerId[payload["owner"]], ZoneRole(payload["role"]), payload["idx"])


def encode_deck_key(key: DeckKey) -> dict:
    """Encode a ``DeckKey`` to JSON-ready plain data."""
    return {"owner": key.owner.name, "side": key.side.value}


def decode_deck_key(payload: dict) -> DeckKey:
    """Rebuild the ``DeckKey`` encoded by ``encode_deck_key``."""
    return DeckKey(PlayerId[payload["owner"]], Side(payload["side"]))


def encode_move_dest(dest: MoveDest) -> dict:
    """Encode a move destination — the shared battlefield, a deck, or an owned zone — to plain
    data."""
    if dest == BATTLEFIELD:
        return {"kind": "battlefield"}
    if isinstance(dest, DeckKey):
        return {"kind": "deck", "deck": encode_deck_key(dest)}
    return {"kind": "zone", "zone": encode_zone_key(dest)}


def decode_move_dest(payload: dict) -> MoveDest:
    """Rebuild the move destination encoded by ``encode_move_dest``."""
    kind = payload["kind"]
    if kind == "battlefield":
        return BATTLEFIELD
    if kind == "deck":
        return decode_deck_key(payload["deck"])
    return decode_zone_key(payload["zone"])


def encode_attach_target(target) -> dict:
    """Encode an attachment target — a parent card id or a province — to plain data."""
    if isinstance(target, ZoneKey):
        return {"kind": "zone", "zone": encode_zone_key(target)}
    return {"kind": "card", "card_id": target}


def decode_attach_target(payload: dict):
    """Rebuild the attachment target encoded by ``encode_attach_target``."""
    if payload["kind"] == "zone":
        return decode_zone_key(payload["zone"])
    return payload["card_id"]


def encode_seat(info: SeatInfo) -> dict:
    """Encode a ``SeatInfo`` to JSON-ready plain data."""
    return {
        "name": info.name,
        "honor": info.honor,
        "ready": info.ready,
        "connected": info.connected,
    }


def decode_seat(payload: dict) -> SeatInfo:
    """Rebuild the ``SeatInfo`` encoded by ``encode_seat``."""
    return SeatInfo(**payload)


def encode_intent(intent: Intent) -> dict:
    """Encode an ``Intent`` to JSON-ready plain data (op + targets). The canonical intent wire
    shape, shared by the persisted log and the live wire protocol."""
    payload: dict = {"op": intent.op.value}
    match intent.op:
        case IntentOp.MOVE_CARD:
            payload["card_id"] = intent.card_id
            payload["to"] = encode_move_dest(intent.to)
            payload["position"] = (
                None if intent.position is None else [intent.position.x, intent.position.y]
            )
            payload["to_bottom"] = intent.to_bottom
            payload["value"] = intent.index  # the hand-slot index, when landing in a hand
            payload["face_down"] = intent.face_down  # lay it face down, on a battlefield landing
        case IntentOp.MOVE_DECK_TOP:
            payload["deck"] = encode_deck_key(intent.deck)
            payload["to"] = encode_move_dest(intent.to)
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
                "to": encode_move_dest(intent.pile),
                "card_id": intent.card_id,
                "value": intent.index,
            }
        case IntentOp.RAISE:
            payload["card_id"] = intent.card_id
        case IntentOp.SET_NOTE:
            payload |= {"card_id": intent.card_id, "text": intent.note}
        case IntentOp.ADJUST_COUNTER:
            payload |= {
                "card_id": intent.card_id,
                "name": intent.counter.key,
                "delta": intent.delta,
            }
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
            payload["deck"] = encode_deck_key(intent.deck)
        case IntentOp.SEARCH_DECK:
            payload["deck"] = encode_deck_key(intent.deck)
            payload["value"] = intent.limit
        case IntentOp.SHUFFLE:
            payload["deck"] = encode_deck_key(intent.deck)
            payload["seed"] = intent.seed
        case IntentOp.FLIP_DECK_TOP:
            payload["deck"] = encode_deck_key(intent.deck)
        case IntentOp.FILL_PROVINCE | IntentOp.DESTROY_PROVINCE | IntentOp.DISCARD_PROVINCE:
            payload["zone"] = encode_zone_key(intent.zone)
        case IntentOp.CREATE_PROVINCE:
            pass
        case IntentOp.SET_HONOR:
            payload |= {"delta": intent.delta, "value": intent.value}
        case IntentOp.SPAWN_CARD:
            payload |= {
                "card_id": intent.card_id,
                "name": intent.name,
                "side": intent.side.value,
                "image": intent.image,
                "position": [intent.position.x, intent.position.y],
            }
        case IntentOp.REMOVE_CARD:
            payload["card_id"] = intent.card_id
        case IntentOp.ATTACH:
            payload |= {"card_id": intent.card_id, "to": encode_attach_target(intent.to)}
        case IntentOp.DETACH:
            payload["card_id"] = intent.card_id
        case IntentOp.FLIP_COIN:
            payload["seed"] = intent.seed
        case IntentOp.ROLL_DICE:
            payload |= {"seed": intent.seed, "value": intent.sides}
        case _:
            raise ValueError(f"unhandled intent op: {intent.op}")
    return payload


def decode_intent(payload: dict) -> Intent:
    """Rebuild an ``Intent`` from the plain data produced by ``encode_intent``. Raises
    ``KeyError`` / ``ValueError`` on a malformed payload; callers handling untrusted input should
    validate the envelope first and treat a raised error as a rejected message."""
    op = IntentOp(payload["op"])
    match op:
        case IntentOp.MOVE_CARD:
            position = payload["position"]
            return MoveCard(
                payload["card_id"],
                decode_move_dest(payload["to"]),
                None if position is None else BoardPos(*position),
                to_bottom=payload.get("to_bottom", False),
                index=payload.get("value"),
                face_down=payload.get("face_down", False),
            )
        case IntentOp.MOVE_DECK_TOP:
            position = payload.get("position")
            return MoveDeckTop(
                decode_deck_key(payload["deck"]),
                decode_move_dest(payload["to"]),
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
                decode_move_dest(payload["to"]), payload["card_id"], payload["value"]
            )
        case IntentOp.RAISE:
            return Raise(payload["card_id"])
        case IntentOp.SET_NOTE:
            return SetNote(payload["card_id"], payload.get("text"))
        case IntentOp.ADJUST_COUNTER:
            counter = counter_from_key(payload["name"])
            return AdjustCounter(payload["card_id"], counter, payload["delta"])
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
            return Draw(decode_deck_key(payload["deck"]))
        case IntentOp.SEARCH_DECK:
            return SearchDeck(decode_deck_key(payload["deck"]), limit=payload.get("value"))
        case IntentOp.SHUFFLE:
            return Shuffle(decode_deck_key(payload["deck"]), payload["seed"])
        case IntentOp.FLIP_DECK_TOP:
            return FlipDeckTop(decode_deck_key(payload["deck"]))
        case IntentOp.FILL_PROVINCE:
            return FillProvince(decode_zone_key(payload["zone"]))
        case IntentOp.DESTROY_PROVINCE:
            return DestroyProvince(decode_zone_key(payload["zone"]))
        case IntentOp.DISCARD_PROVINCE:
            return DiscardProvince(decode_zone_key(payload["zone"]))
        case IntentOp.CREATE_PROVINCE:
            return CreateProvince()
        case IntentOp.SET_HONOR:
            return SetHonor(delta=payload["delta"], value=payload["value"])
        case IntentOp.SPAWN_CARD:
            return SpawnCard(
                payload["card_id"],
                payload["name"],
                Side(payload["side"]),
                payload["image"],
                BoardPos(*payload["position"]),
            )
        case IntentOp.REMOVE_CARD:
            return RemoveCard(payload["card_id"])
        case IntentOp.ATTACH:
            return Attach(payload["card_id"], decode_attach_target(payload["to"]))
        case IntentOp.DETACH:
            return Detach(payload["card_id"])
        case IntentOp.FLIP_COIN:
            return FlipCoin(payload["seed"])
        case IntentOp.ROLL_DICE:
            sides = payload.get("value")
            return RollDice(payload["seed"]) if sides is None else RollDice(payload["seed"], sides)
        case _:
            raise ValueError(f"unhandled intent op: {op}")
