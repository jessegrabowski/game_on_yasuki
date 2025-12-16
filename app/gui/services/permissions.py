from typing import TYPE_CHECKING
from app.engine.players import PlayerId

if TYPE_CHECKING:
    from app.gui.field_view import FieldView


def tag_owner(tag: str) -> PlayerId | None:
    if tag.startswith("p1:"):
        return PlayerId.P1
    if tag.startswith("p2:"):
        return PlayerId.P2

    return None


def can_interact(view: "FieldView", owner: PlayerId | None) -> bool:
    # Unowned tags are unrestricted; else only the controller of the target may act on it
    return owner is None or owner == view.local_player


def same_owner(a: PlayerId | None, b: PlayerId | None) -> bool:
    return a is not None and b is not None and a == b
