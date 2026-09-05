import tkinter as tk
from typing import Any

from yasuki_core.game_pieces.cards import L5RCard
from yasuki_gui import theme
from yasuki_gui.constants import CARD_W, CARD_H
from yasuki_gui.config import DEFAULT_HOTKEYS, Hotkeys
from yasuki_gui.ui.card_preview import CardPreview
from yasuki_gui.ui.floating_panel import FloatingPanel
from yasuki_gui.ui.images import ImageProvider

STRIP_W = 820
STRIP_H = 300
CELL_PAD = 10


def card_face(images: ImageProvider, card: L5RCard) -> Any | None:
    """The image ``card`` shows in a strip: its front when it is face up, its back otherwise.

    Returns None where the art is missing, which the caller renders as a named placeholder.
    """
    if card.face_up:
        return images.front(card.image_front, card.bowed, card.inverted)
    return images.back(card.side, card.bowed, card.inverted, card.image_back)


class CardStrip(FloatingPanel):
    """A pile laid over the board, its cards left to right and scrolling horizontally.

    A look rather than a chooser: nothing here commits, so it is dragged, rolled up and closed like
    any other panel, and reopening it keeps wherever the player left it. Which face each card shows
    is :func:`card_face`'s call.
    """

    def __init__(self, master: tk.Misc, images: ImageProvider):
        super().__init__(master, "", width=STRIP_W, height=STRIP_H, closable=True)
        self.images = images
        self._canvas = tk.Canvas(self.body, bg=theme.PANEL, highlightthickness=0)
        self._scroll = tk.Scrollbar(self.body, orient="horizontal", command=self._canvas.xview)
        self._canvas.configure(xscrollcommand=self._scroll.set)
        self._row = tk.Frame(self._canvas, bg=theme.PANEL)
        self._canvas.create_window((0, 0), window=self._row, anchor="nw")
        self._canvas.pack(side="top", fill="both", expand=True)
        self._scroll.pack(side="bottom", fill="x")
        # The row reports its size once Tk has actually laid it out, which is after the panel is
        # placed. Measuring it here instead would scroll against a size the cards do not have yet.
        self._row.bind("<Configure>", self._fit_scrollregion)
        # Tk drops a PhotoImage the moment nothing references it, blanking the cell it was drawn
        # into, so the panel holds on to the ones it is currently showing.
        self._showing: list[Any] = []
        self.hotkeys: Hotkeys = DEFAULT_HOTKEYS
        # Set by whoever owns the window, so a card previews over everything rather than inside
        # this panel, which would clip it and shrink it with the panel.
        self.preview: CardPreview | None = None
        self._hovered: tuple[L5RCard, tk.Misc] | None = None
        # Bound once rather than per open: the key is live for the panel's whole life and the
        # handler is what checks whether the panel is up, so reopening cannot stack handlers.
        self.bind_all(f"<KeyPress-{self.hotkeys.view}>", self._toggle_preview, add="+")

    def show(self, cards: list[L5RCard], title: str) -> None:
        """Fill the strip with ``cards`` under ``title``, replacing whatever it held."""
        self.set_title(title)
        for child in self._row.winfo_children():
            child.destroy()
        self._showing = []
        for column, card in enumerate(cards):
            holder = tk.Frame(self._row, bg=theme.PANEL)
            holder.grid(row=0, column=column, padx=CELL_PAD, pady=CELL_PAD)
            photo = card_face(self.images, card)
            if photo is None:
                self._draw_placeholder(holder, card)
            else:
                tk.Label(holder, image=photo, bg=theme.PANEL).pack()
                self._showing.append(photo)
            self._track_hover(holder, card)
        # The title and the cards both change after the panel is placed, and Tk holds that layout
        # until its next redraw. Flushing idle work here paints the whole panel on the click that
        # opened it rather than the one after. Idle tasks only — pumping events here would run the
        # handler that is still on the stack.
        self.update_idletasks()

    def _track_hover(self, cell: tk.Misc, card: L5RCard) -> None:
        """Remember which card the pointer is over, so the preview key knows what to enlarge."""
        for widget in (cell, *cell.winfo_children()):
            widget.bind("<Enter>", lambda _event, c=card, w=cell: self._set_hovered((c, w)))
        cell.bind("<Leave>", lambda _event: self._set_hovered(None))

    def _set_hovered(self, hovered: tuple[L5RCard, tk.Misc] | None) -> None:
        self._hovered = hovered

    def close(self) -> None:
        """Take the strip off the board, dropping any preview it put up."""
        if self.preview is not None:
            self.preview.hide()
        self._hovered = None
        super().close()

    def _toggle_preview(self, _event: tk.Event | None = None) -> None:
        """Enlarge the hovered card, or put an open preview away.

        The key is bound app-wide and this handler runs after the board's, so it acts only while one
        of the strip's own cards is under the pointer. Anywhere else the press belongs to the board,
        and taking it would close the preview the board had just opened.
        """
        if self.preview is None or not self.showing or self._hovered is None:
            return
        if self.preview.showing:
            self.preview.hide()
            return
        card, cell = self._hovered
        self.preview.show(
            card,
            cell.winfo_rootx() + cell.winfo_width() // 2,
            cell.winfo_rooty() + cell.winfo_height() // 2,
        )

    def _fit_scrollregion(self, _event: tk.Event | None = None) -> None:
        """Scroll over exactly what the row holds, re-read whenever its layout settles."""
        self._canvas.configure(scrollregion=self._canvas.bbox("all"))

    def _draw_placeholder(self, parent: tk.Misc, card: L5RCard) -> None:
        """Stand in for a card whose art is missing, so the cell reads as that card rather than as a
        gap in the pile."""
        width, height = (CARD_H, CARD_W) if card.bowed else (CARD_W, CARD_H)
        canvas = tk.Canvas(
            parent, width=width, height=height, bg=theme.CARD_FACE, highlightthickness=0
        )
        canvas.pack()
        canvas.create_text(width // 2, height // 2, text=card.name, fill=theme.INK)
