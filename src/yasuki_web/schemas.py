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


class BoardAction(BaseModel):
    # INTERIM (PR03): a flat, fully-public battlefield, replaced by the authoritative TableState
    # protocol in PR07.
    kind: Literal["ADD_CARD", "SET_CARD_POS", "CARD_FLAG", "REMOVE_CARD"]
    id: str = Field(max_length=64)
    name: str | None = Field(None, max_length=120)
    img: str | None = Field(None, max_length=200)
    x: int | None = None
    y: int | None = None
    flag: Literal["bowed", "face_up"] | None = None


class ClientMessage(BaseModel):
    type: Literal["JOIN", "ACTION", "CHAT", "BOARD", "PING"]
    room: str = Field(max_length=64)
    join: JoinRequest | None = None
    action: Action | None = None
    chat: ChatRequest | None = None
    board: BoardAction | None = None
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


class ServerLog(BaseModel):
    type: Literal["LOG"] = "LOG"
    room: str
    text: str


ServerMessage = ServerHello | ServerState | ServerError | ServerChat | ServerLog


class Player(BaseModel):
    name: str
    hand: list[str] = Field(default_factory=list)


class GameState(BaseModel):
    deck: list[str]
    discard: list[str] = Field(default_factory=list)
    players: list[Player] = Field(default_factory=list)
    turn_index: int = 0
