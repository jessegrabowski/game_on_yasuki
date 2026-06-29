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


def _card(
    view: L5RCard | HiddenCard,
    peeked_ids: frozenset[str] = frozenset(),
    token_names: dict[str, str] | None = None,
) -> dict:
    """Encode a viewer's card as the client renders it. A ``HiddenCard`` becomes a back stub carrying
    no identity; a full card carries the presented face's name and art plus its flags. A double-faced
    card also carries its back link and which face is showing, so the client can render the flip.

    The ``shown`` flag marks a card the owner has made public-facing (render a public indicator); the
    ``peeked`` flag, set from ``peeked_ids``, marks one this viewer sees only through their own peek
    (render the private-peek cue). A hidden stub carries neither — the viewer cannot see it at all.

    Parameters
    ----------
    view : L5RCard or HiddenCard
        The card or back stub to encode.
    peeked_ids : frozenset of str, optional
        Ids the viewer sees solely by peeking, from the snapshot. Default empty.
    token_names : dict mapping str to str, optional
        Creatable-token card id to display name. When given, a card that creates tokens carries a
        ``creates`` list of ``{id, name}`` for the per-card "Create" menu. Default none.
    """
    if isinstance(view, HiddenCard):
        return {
            "id": view.card_id,
            "side": view.side.value,
            "owner": view.owner.name if view.owner is not None else None,
            "token": False,
            "hidden": True,
        }
    face = view.active_face
    card = {
        "id": view.id,
        "name": face.name,
        "img": face.image_front.as_posix() if face.image_front is not None else None,
        "side": face.side.value,
        "owner": view.owner.name if view.owner is not None else None,
        "pregame": isinstance(view, _PREGAME_TYPES),
        "token": view.is_token,
        "bowed": view.bowed,
        "face_up": view.face_up,
        "inverted": view.inverted,
        "shown": view.shown,
        "peeked": view.id in peeked_ids,
        "hidden": False,
    }
    if view.back_card_id is not None:
        card["back_card_id"] = view.back_card_id
        card["showing_back"] = view.showing_back
    if face.art_swap is not None:
        card["art"] = face.art_swap
    if face.note:
        card["note"] = face.note
    if token_names and view.creates:
        card["creates"] = [{"id": tid, "name": token_names.get(tid, tid)} for tid in view.creates]
    return card


def serialize_deck_cards(cards: list[L5RCard]) -> list[dict]:
    """Serialize a deck's cards for delivery to its owner, top of deck first.

    Only the deck's owner ever receives this, so each card is encoded at full identity (no
    redaction). Index 0 is the top card, the next one drawn.

    Parameters
    ----------
    cards : list of L5RCard
        The deck's cards, bottom-first as stored on the table.
    """
    return [_card(card) for card in reversed(cards)]


def serialize_snapshot(snapshot: ViewSnapshot, token_names: dict[str, str] | None = None) -> dict:
    """Serialize a redacted ``ViewSnapshot`` to the JSON-ready shape the board client renders from.

    Cards the viewer may not identify are already ``HiddenCard`` stubs in the snapshot, so this
    serializer cannot leak an identity it was not handed. Zone and deck keys are flattened to stable
    strings (``"P1:province:0"``, ``"P2:fate"``).

    ``token_names`` maps a creatable-token card id to its display name; when given, a battlefield or
    province card that creates tokens carries a ``creates`` list for the per-card "Create" menu (a
    face-down province card is a ``HiddenCard`` stub, so its creations stay concealed).
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
                "avatar": view.avatar,
            }
            for seat, view in snapshot.seats.items()
        },
        "zones": {
            _zone_key_str(key): [
                _card(card, snapshot.peeked_ids, token_names) for card in zone.cards
            ]
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
            {
                **_card(entry.card, snapshot.peeked_ids, token_names),
                "x": entry.pos.x,
                "y": entry.pos.y,
            }
            for entry in snapshot.battlefield
        ],
    }
