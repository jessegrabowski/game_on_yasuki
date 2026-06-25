from pydantic import BaseModel, Field
from typing import Annotated, Literal

from yasuki_core.engine.table import Intent, IntentOp
from yasuki_core.engine.action_log import decode_intent


class JoinRequest(BaseModel):
    name: str = Field(min_length=1, max_length=50)


class ChatRequest(BaseModel):
    text: str = Field(min_length=1, max_length=500)


class IntentEnvelope(BaseModel):
    """A game intent on the wire: an op plus whichever targets that op needs. The same shape the
    action log persists (see ``encode_intent``); the server maps it to a core ``Intent`` and applies
    it authoritatively. Nested key targets (``to``/``deck``/``zone``) are validated structurally when
    decoded; a malformed one is rejected as a bad intent, not a protocol error.
    """

    op: IntentOp
    card_id: str | None = Field(None, max_length=64)
    card_ids: list[Annotated[str, Field(max_length=64)]] | None = Field(None, max_length=128)
    to: dict | None = None
    position: list[float] | None = Field(None, max_length=2)
    deck: dict | None = None
    zone: dict | None = None
    x: float | None = None
    y: float | None = None
    seed: int | None = None
    delta: int | None = None
    value: int | None = None


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
            "to": envelope.to,
            "position": envelope.position,
            "deck": envelope.deck,
            "zone": envelope.zone,
            "x": envelope.x,
            "y": envelope.y,
            "seed": envelope.seed,
            "delta": envelope.delta,
            "value": envelope.value,
        }
    )


class SpawnRequest(BaseModel):
    # The wire form of a spawn; the server turns it into a logged SpawnCard intent (assigning the id).
    name: str = Field(max_length=120)
    img: str | None = Field(None, max_length=200)
    side: Literal["FATE", "DYNASTY", "STRONGHOLD"] = "FATE"
    x: int = 0
    y: int = 0


class RemoveRequest(BaseModel):
    id: str = Field(max_length=64)


class ClientMessage(BaseModel):
    type: Literal["JOIN", "INTENT", "SPAWN", "REMOVE", "CHAT", "PING"]
    room: str = Field(max_length=64)
    join: JoinRequest | None = None
    intent: IntentEnvelope | None = None
    spawn: SpawnRequest | None = None
    remove: RemoveRequest | None = None
    chat: ChatRequest | None = None
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


class ServerChat(BaseModel):
    type: Literal["CHAT"] = "CHAT"
    room: str
    # ``from`` is a Python keyword, so the field is ``sender`` and serializes to "from" on the wire.
    sender: str = Field(serialization_alias="from")
    text: str


class ServerLog(BaseModel):
    type: Literal["LOG"] = "LOG"
    room: str
    text: str


ServerMessage = ServerHello | ServerSnapshot | ServerError | ServerChat | ServerLog
