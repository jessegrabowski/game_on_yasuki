from yasuki_core.engine.redaction import ViewSnapshot, HiddenCard
from yasuki_core.engine.table import ZoneKey, DeckKey
from yasuki_core.game_pieces.cards import L5RCard
from yasuki_core.game_pieces.pregame import StrongholdCard, SenseiCard, WindCard

_PREGAME_TYPES = (StrongholdCard, SenseiCard, WindCard)


def _zone_key_str(key: ZoneKey) -> str:
    base = f"{key.owner.name}:{key.role.value}"
    return f"{base}:{key.idx}" if key.idx is not None else base


def _deck_key_str(key: DeckKey) -> str:
    return f"{key.owner.name}:{key.side.value.lower()}"


def _card(view: L5RCard | HiddenCard) -> dict:
    """Encode a viewer's card as the client renders it. A ``HiddenCard`` becomes a back stub carrying
    no identity; a full card carries the presented face's name and art plus its flags. A double-faced
    card also carries its back link and which face is showing, so the client can render the flip."""
    if isinstance(view, HiddenCard):
        return {"id": view.card_id, "side": view.side.value, "hidden": True}
    face = view.active_face
    card = {
        "id": view.id,
        "name": face.name,
        "img": face.image_front.as_posix() if face.image_front is not None else None,
        "side": face.side.value,
        "owner": view.owner.name if view.owner is not None else None,
        "pregame": isinstance(view, _PREGAME_TYPES),
        "bowed": view.bowed,
        "face_up": view.face_up,
        "inverted": view.inverted,
        "hidden": False,
    }
    if view.back_card_id is not None:
        card["back_card_id"] = view.back_card_id
        card["showing_back"] = view.showing_back
    return card


def serialize_snapshot(snapshot: ViewSnapshot) -> dict:
    """Serialize a redacted ``ViewSnapshot`` to the JSON-ready shape the board client renders from.

    Cards the viewer may not identify are already ``HiddenCard`` stubs in the snapshot, so this
    serializer cannot leak an identity it was not handed. Zone and deck keys are flattened to stable
    strings (``"P1:province:0"``, ``"P2:fate"``).
    """
    return {
        "seq": snapshot.seq,
        "your_seat": snapshot.viewer.name,
        "seats": {
            seat.name: {
                "name": view.name,
                "honor": view.honor,
                "ready": view.ready,
                "connected": view.connected,
            }
            for seat, view in snapshot.seats.items()
        },
        "zones": {
            _zone_key_str(key): [_card(card) for card in zone.cards]
            for key, zone in snapshot.zones.items()
        },
        "decks": {
            _deck_key_str(key): {
                "count": deck.count,
                "top": _card(deck.top) if deck.top is not None else None,
            }
            for key, deck in snapshot.decks.items()
        },
        "battlefield": [
            {**_card(entry.card), "x": entry.pos.x, "y": entry.pos.y}
            for entry in snapshot.battlefield
        ],
    }
