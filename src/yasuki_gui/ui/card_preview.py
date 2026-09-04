import tkinter as tk
from typing import Any

from yasuki_core.game_pieces.cards import L5RCard
from yasuki_gui import theme
from yasuki_gui.constants import CARD_W, CARD_H, PREVIEW_SCALE
from yasuki_gui.layout import card_view_placement
from yasuki_gui.ui.images import ImageProvider


class CardPreview:
    """The enlarged card the view key floats, drawn over the whole window.

    Placed on the window rather than inside whatever holds the card, so it is neither hidden behind
    a panel laid over the board nor clipped and shrunk by the panel a card was previewed from. One
    of these serves every surface that previews a card, so they cannot disagree about its size.
    """

    def __init__(self, host: tk.Misc, images: ImageProvider):
        """Build the preview, hidden.

        Parameters
        ----------
        host : tkinter.Misc
            The window the preview is drawn over, and whose bounds it is kept inside.
        images : ImageProvider
            Where the enlarged art comes from.
        """
        self.host = host
        self.images = images
        self._label: tk.Label | None = None
        self._photo: Any | None = None

    @property
    def showing(self) -> bool:
        """Whether a preview is currently up."""
        return self._label is not None

    def show(self, card: L5RCard, card_rootx: int, card_rooty: int) -> None:
        """Float ``card`` enlarged beside where it sits, given that point in screen coordinates.

        Shows the card's front when it is face up and its back otherwise, so a preview never reveals
        what the board conceals. Does nothing where the art is missing.
        """
        self.hide()
        host_h = self.host.winfo_height()
        height = min(int(PREVIEW_SCALE * CARD_H), max(CARD_H, host_h - 20))
        width = height * CARD_W // CARD_H
        target = (width, height)
        if card.face_up:
            photo = self.images.front(card.active_face.image_front, False, False, target)
        else:
            photo = self.images.back(card.side, False, False, card.image_back, target)
        if photo is None:
            return

        left, top = card_view_placement(
            card_rootx - self.host.winfo_rootx(),
            card_rooty - self.host.winfo_rooty(),
            CARD_W,
            CARD_H,
            width,
            height,
            self.host.winfo_width(),
            host_h,
        )
        self._photo = photo
        self._label = tk.Label(self.host, image=photo, bg=theme.PANEL, borderwidth=0)
        self._label.place(x=left, y=top)
        self._label.lift()

    def hide(self) -> None:
        """Put the preview away. Safe when none is up."""
        if self._label is not None:
            self._label.destroy()
        self._label = None
        self._photo = None
