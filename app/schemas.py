from pydantic import BaseModel, Field
from typing import Literal


class JoinRequest(BaseModel):
    name: str


class Action(BaseModel):
    kind: Literal[
        "SHUFFLE",
        "DEAL",
        "PLAY_CARD",
        "DRAW",
        "PASS",
    ]
    seed: int | None = None
    card: str | None = None


class ClientMessage(BaseModel):
    type: Literal["JOIN", "ACTION", "PING"]
    room: str
    join: JoinRequest | None = None
    action: Action | None = None
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


ServerMessage = ServerHello | ServerState | ServerError


class Player(BaseModel):
    name: str
    hand: list[str] = Field(default_factory=list)


class GameState(BaseModel):
    deck: list[str]
    discard: list[str] = Field(default_factory=list)
    players: list[Player] = Field(default_factory=list)
    turn_index: int = 0
