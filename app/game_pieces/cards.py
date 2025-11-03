from dataclasses import dataclass
from pathlib import Path
from app.game_pieces.constants import Side
from app.engine.players import PlayerId


@dataclass(frozen=True, slots=True)
class L5RCard:
    id: str
    name: str
    side: Side
    clan: str | None = None
    keywords: tuple[str, ...] = ()
    traits: tuple[str, ...] = ()
    text: str = ""
    bowed: bool = False
    face_up: bool = True
    inverted: bool = False
    image_front: Path | None = None
    image_back: Path | None = None
    owner: PlayerId | None = None
    revealed: bool = False

    def __post_init__(self):
        # Normalize collections to tuples for consistent immutability
        if not isinstance(self.keywords, tuple):
            object.__setattr__(self, "keywords", tuple(self.keywords))
        if not isinstance(self.traits, tuple):
            object.__setattr__(self, "traits", tuple(self.traits))

    # State transitions
    def bow(self) -> None:
        if not self.bowed:
            object.__setattr__(self, "bowed", True)

    def unbow(self) -> None:
        if self.bowed:
            object.__setattr__(self, "bowed", False)

    def turn_face_up(self) -> None:
        if not self.face_up:
            object.__setattr__(self, "face_up", True)

    def turn_face_down(self) -> None:
        if self.face_up:
            object.__setattr__(self, "face_up", False)

    def flip(self) -> None:
        object.__setattr__(self, "face_up", not self.face_up)

    def invert(self) -> None:
        if not self.inverted:
            object.__setattr__(self, "inverted", True)

    def uninvert(self) -> None:
        if self.inverted:
            object.__setattr__(self, "inverted", False)
