from pydantic import BaseModel, Field
from typing import Literal


class JoinRequest(BaseModel):
    name: str = Field(min_length=1, max_length=50)


class ChatRequest(BaseModel):
    text: str = Field(min_length=1, max_length=500)


class Action(BaseModel):
    kind: Literal[
        "SHUFFLE",
        "DEAL",
        "PLAY_CARD",
        "DRAW",
        "PASS",
    ]
    seed: int | None = None
    card: str | None = Field(None, max_length=200)
    deck_type: str | None = Field(None, max_length=20)


class ClientMessage(BaseModel):
    type: Literal["JOIN", "ACTION", "CHAT", "PING"]
    room: str = Field(max_length=64)
    join: JoinRequest | None = None
    action: Action | None = None
    chat: ChatRequest | None = None
    since_seq: int | None = None


class ServerHello(BaseModel):
    type: Literal["HELLO"] = "HELLO"
    room: str
    you: str
    players: list[str]
    seq: int


class ServerState(BaseModel):
    type: Literal["STATE"] = "STATE"
    room: str
    seq: int
    state: dict


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


ServerMessage = ServerHello | ServerState | ServerError | ServerChat


class Player(BaseModel):
    name: str
    hand: list[str] = Field(default_factory=list)


class GameState(BaseModel):
    deck: list[str]
    discard: list[str] = Field(default_factory=list)
    players: list[Player] = Field(default_factory=list)
    turn_index: int = 0
