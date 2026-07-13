from dataclasses import dataclass
from pathlib import Path

from yasuki_core.engine.players import PlayerId
from yasuki_core.engine.redaction import HiddenCard
from yasuki_core.game_pieces.cards import L5RCard
from yasuki_core.game_pieces.constants import Side


@dataclass(frozen=True, slots=True)
class HiddenFace:
    """A back-only render facade for a redacted :class:`HiddenCard`.

    Exposes the card-render interface the visuals read — ``face_up`` False, no front art, a known
    ``side`` and ``image_back`` for the back — so a hidden card draws as a face-down back without
    the visuals special-casing it. ``active_face`` returns ``self`` so the visuals'
    ``card.active_face.image_front`` and ``.name`` reads resolve harmlessly while the back draws.

    Attributes
    ----------
    id : str
        The hidden card's stable id, so a sprite can still be keyed and animated.
    side : Side
        Which back art to draw.
    owner : PlayerId or None
        Whose card it is — public even while the face is secret.
    """

    id: str
    side: Side
    owner: PlayerId | None
    bowed: bool = False
    inverted: bool = False
    face_up: bool = False
    shown: bool = False
    note: str | None = None
    image_front: Path | None = None
    image_back: Path | None = None
    name: str = ""

    @property
    def active_face(self) -> "HiddenFace":
        return self


RenderCard = L5RCard | HiddenFace


def to_render_card(card: L5RCard | HiddenCard) -> RenderCard:
    """Pass a real card through unchanged; wrap a redacted ``HiddenCard`` as a back-only
    :class:`HiddenFace`."""
    if isinstance(card, HiddenCard):
        return HiddenFace(id=card.card_id, side=card.side, owner=card.owner)
    return card
