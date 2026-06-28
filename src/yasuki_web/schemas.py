from pydantic import BaseModel, Field
from typing import Annotated, Literal

from yasuki_core.engine.intents import Intent, IntentOp
from yasuki_core.engine.action_log import decode_intent


class JoinRequest(BaseModel):
    name: str = Field(min_length=1, max_length=50)


class ChatRequest(BaseModel):
    text: str = Field(min_length=1, max_length=500)


class ReadyRequest(BaseModel):
    ready: bool = True
    solo: bool = False  # deal a one-seat goldfish table instead of waiting for an opponent


class LoadDeckRequest(BaseModel):
    # The deck-builder export YAML, parsed server-side into dynasty/fate/pre-game name lists. The cap
    # is well above a full decklist (~3-4 KiB) but still bounded; the WS read loop allows a larger
    # frame for this message than for realtime intents (see MAX_WS_MESSAGE_SIZE).
    yaml: str = Field(min_length=1, max_length=16384)
    # Source filename the client loaded from, a fallback deck label when the YAML carries no name.
    filename: str | None = Field(None, max_length=200)


class CardMove(BaseModel):
    # One card's target battlefield position within a SET_CARD_POSITIONS group move.
    id: str = Field(max_length=64)
    x: float
    y: float


class IntentEnvelope(BaseModel):
    """A game intent on the wire: an op plus whichever targets that op needs. The same shape the
    action log persists (see ``encode_intent``); the server maps it to a core ``Intent`` and applies
    it authoritatively. Nested key targets (``to``/``deck``/``zone``) are validated structurally when
    decoded; a malformed one is rejected as a bad intent, not a protocol error.
    """

    op: IntentOp
    card_id: str | None = Field(None, max_length=64)
    card_ids: list[Annotated[str, Field(max_length=64)]] | None = Field(None, max_length=128)
    moves: list[CardMove] | None = Field(None, max_length=128)
    to: dict | None = None
    to_bottom: bool = False
    position: list[float] | None = Field(None, max_length=2)
    deck: dict | None = None
    zone: dict | None = None
    x: float | None = None
    y: float | None = None
    seed: int | None = None
    delta: int | None = None
    value: int | None = None
    # A card's free-text note (SET_NOTE); bounded so a note stays a short label, not a payload.
    text: str | None = Field(None, max_length=200)
    # SPAWN_CARD targets: a brand-new public card's print. The server assigns the card_id (the client
    # leaves it unset), so a replay reproduces the same card.
    name: str | None = Field(None, max_length=120)
    img: str | None = Field(None, max_length=200)
    side: Literal["FATE", "DYNASTY", "STRONGHOLD"] | None = None


def intent_from_envelope(envelope: IntentEnvelope) -> Intent:
    """Build a core ``Intent`` from a validated envelope. Raises on a structurally malformed target
    (``KeyError``/``TypeError``) or an invalid combination (``ValueError``); the caller treats a
    raised error as a rejected intent.
    """
    return decode_intent(
        {
            "op": envelope.op.value,
            "card_id": envelope.card_id,
            "card_ids": envelope.card_ids,
            "moves": None if envelope.moves is None else [[m.id, m.x, m.y] for m in envelope.moves],
            "to": envelope.to,
            "to_bottom": envelope.to_bottom,
            "position": envelope.position,
            "deck": envelope.deck,
            "zone": envelope.zone,
            "x": envelope.x,
            "y": envelope.y,
            "seed": envelope.seed,
            "delta": envelope.delta,
            "value": envelope.value,
            "text": envelope.text,
            "name": envelope.name,
            "image": envelope.img,
            "side": envelope.side,
        }
    )


class ClientMessage(BaseModel):
    type: Literal["JOIN", "INTENT", "CHAT", "LOAD_DECK", "READY", "RESET", "PING"]
    room: str = Field(max_length=64)
    join: JoinRequest | None = None
    intent: IntentEnvelope | None = None
    chat: ChatRequest | None = None
    load_deck: LoadDeckRequest | None = None
    ready: ReadyRequest | None = None
    since_seq: int | None = None


class ServerHello(BaseModel):
    type: Literal["HELLO"] = "HELLO"
    room: str
    you: str
    your_seat: str | None = None
    players: list[str]
    seq: int


class ServerSnapshot(BaseModel):
    type: Literal["SNAPSHOT"] = "SNAPSHOT"
    room: str
    snapshot: dict  # per-viewer redacted view (see snapshot.serialize_snapshot)


class ServerError(BaseModel):
    type: Literal["ERROR"] = "ERROR"
    room: str
    message: str
    # A debug-level error (e.g. a rejected intent) the client only surfaces when its debug flag is
    # on; the authoritative SNAPSHOT revert is the player's real feedback. Default false means
    # user-facing.
    debug: bool = False


class ServerChat(BaseModel):
    type: Literal["CHAT"] = "CHAT"
    room: str
    # ``from`` is a Python keyword, so the field is ``sender`` and serializes to "from" on the wire.
    sender: str = Field(serialization_alias="from")
    text: str


class ServerLog(BaseModel):
    type: Literal["LOG"] = "LOG"
    room: str
    # Ordered segments: {"text": str} for prose, {"card_id": str, "name": str} for a card link.
    parts: list[dict]


class ServerDeckContents(BaseModel):
    """A deck's full ordered contents, delivered to its owner alone in response to a SEARCH_DECK.

    The normal SNAPSHOT redacts deck order, so this is the one message that reveals a deck's cards —
    and only ever to the player who owns it. ``cards`` is top-of-deck first: index 0 is the card that
    would be drawn next. ``deck`` carries the owning seat and side (e.g. ``{"owner": "P1", "side":
    "FATE"}``) so the client can label the dialog and route a pulled card.
    """

    type: Literal["DECK_CONTENTS"] = "DECK_CONTENTS"
    room: str
    deck: dict
    cards: list[dict]


ServerMessage = (
    ServerHello | ServerSnapshot | ServerError | ServerChat | ServerLog | ServerDeckContents
)
