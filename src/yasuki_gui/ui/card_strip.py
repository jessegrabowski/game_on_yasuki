import tkinter as tk

from yasuki_core.game_pieces.cards import L5RCard
from yasuki_gui import theme
from yasuki_gui.constants import CARD_H, CARD_W
from yasuki_gui.ui.card_panel import CardPanel
from yasuki_gui.ui.floating_panel import BORDER, TITLEBAR_H
from yasuki_gui.ui.images import ImageProvider

STRIP_W = 820
CELL_PAD = 10
# What Tk's horizontal scrollbar asks for. Asking a live widget would need one to exist before the
# strip's size is decided, so the strip's tests check this against a real one instead.
SCROLLBAR_H = 15
# Exactly one row of cards and the bar under it: the strip scrolls sideways and never wraps, and
# opening it any taller would say otherwise.
STRIP_H = TITLEBAR_H + 2 * BORDER + 2 * CELL_PAD + CARD_H + SCROLLBAR_H


class CardStrip(CardPanel):
    """A pile laid over the board, its cards left to right and scrolling horizontally.

    A look rather than a chooser: nothing here commits, so it is dragged, rolled up and closed like
    any other panel, and reopening it keeps wherever the player left it.
    """

    def __init__(self, master: tk.Misc, images: ImageProvider):
        super().__init__(
            master, "", width=STRIP_W, height=STRIP_H, closable=True, images=images, bg=theme.PANEL
        )
        self._scroll = tk.Scrollbar(self.body, orient="horizontal", command=self.canvas.xview)
        self.canvas.configure(xscrollcommand=self._scroll.set)
        # Packed ahead of the canvas, which already fills the body: pack hands out room in packing
        # order, so a scrollbar packed after it would be left nothing to sit in.
        self._scroll.pack(side="bottom", fill="x", before=self.canvas)
        # One wheel notch is one card, rather than Tk's tenth of whatever the panel is wide.
        self.canvas.configure(xscrollincrement=CARD_W + CELL_PAD)
        self.canvas.bind("<MouseWheel>", self._on_wheel)
        # X11 reports the wheel as buttons 4 and 5 rather than a delta.
        self.canvas.bind("<Button-4>", lambda _event: self.canvas.xview_scroll(-1, "units"))
        self.canvas.bind("<Button-5>", lambda _event: self.canvas.xview_scroll(1, "units"))

    def show(self, cards: list[L5RCard], title: str) -> None:
        """Fill the strip with ``cards`` under ``title``, replacing whatever it held."""
        self.set_title(title)
        self.clear()
        x = CELL_PAD
        for card in cards:
            width = CARD_H if card.bowed else CARD_W
            self.draw_card(card, x + width // 2, CELL_PAD + CARD_H // 2)
            x += width + CELL_PAD
        # Scroll over exactly what the row holds, padded so the last card clears the edge.
        self.canvas.configure(scrollregion=(0, 0, x, 2 * CELL_PAD + CARD_H))
        # The title and the cards both change after the panel is placed, and Tk holds that layout
        # until its next redraw. Flushing idle work here paints the whole panel on the click that
        # opened it rather than the one after. Idle tasks only, because pumping events here would
        # run the handler that is still on the stack.
        self.update_idletasks()

    def _on_wheel(self, event: tk.Event) -> None:
        self.canvas.xview_scroll(-1 if event.delta > 0 else 1, "units")
