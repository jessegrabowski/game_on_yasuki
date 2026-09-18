import tkinter as tk
from collections.abc import Callable
from dataclasses import replace

from yasuki_core.game_pieces.cards import L5RCard
from yasuki_gui import theme
from yasuki_gui.constants import CARD_H, CARD_W
from yasuki_gui.layout import centered_row
from yasuki_gui.ui.card_panel import CardPanel
from yasuki_gui.ui.floating_panel import BORDER, TITLEBAR_H
from yasuki_gui.ui.geometry import widget_size
from yasuki_gui.ui.images import ImageProvider

CELL_PAD = 12
# What a card the seat may not pick is veiled with, so it reads as shown rather than offered.
_VEIL_TAG = "veil"
# Room for six cards in a row: one more than the longest look a Shattered Empire card prints, so a
# look sized by a stat has some headroom before the row runs past the panel.
LOOK_W = 6 * (CARD_W + CELL_PAD) + CELL_PAD
LOOK_H = TITLEBAR_H + 2 * BORDER + 2 * CELL_PAD + CARD_H


class LookView(CardPanel):
    """The cards a seat is looking at in a deck, laid in one row while the questions about them are
    asked: which to take, which to put on the bottom, and in what order the rest go back.

    Opened and closed by the game rather than the player, like the battle view: a stray dismissal
    would hide cards the seat still has to answer about. A card the current question offers is drawn
    plain and a click reports it; one it does not is veiled and answers nothing. A card the seat has
    already placed while arranging is not drawn at all, which is what makes the arranging read as
    taking cards off the table one by one.

    Attributes
    ----------
    on_card_click : callable or None
        Taken with a card id when the seat clicks a card the question offers.
    """

    def __init__(self, master: tk.Misc, images: ImageProvider):
        super().__init__(
            master, "Looking at", width=LOOK_W, height=LOOK_H, images=images, bg=theme.PANEL
        )
        self.on_card_click: Callable[[str], None] | None = None
        self.canvas.bind("<Button-1>", self._on_click)

    def refresh(
        self,
        cards: list[L5RCard],
        candidates: frozenset[str],
        selected: frozenset[str] = frozenset(),
        placed: frozenset[str] = frozenset(),
    ) -> None:
        """Redraw for ``cards`` in their order, top of the deck leftmost.

        Parameters
        ----------
        cards : list of L5RCard
            The cards in view, top first.
        candidates : frozenset of str
            The ids the current question may be answered with. The rest are veiled.
        selected : frozenset of str, optional
            The ids picked so far, ringed. Default empty.
        placed : frozenset of str, optional
            The ids the seat has already put back while arranging, left out of the row. Default
            empty.
        """
        self.clear()
        # The cards are face down in the deck and stay so on the table; here the seat is looking
        # at them, so each is drawn from a face-up copy. The copy is what the view key previews.
        shown = [replace(card, face_up=True) for card in cards if card.id not in placed]
        center = widget_size(self.canvas)[0] // 2
        y = CELL_PAD + CARD_H // 2
        for x, card in zip(centered_row(center, len(shown), step=CARD_W + CELL_PAD), shown):
            pickable = card.id in candidates
            self.draw_card(card, x, y, selected=card.id in selected, pickable=pickable)
            if not pickable:
                self._veil(x, y)

    def _veil(self, x: int, y: int) -> None:
        self.canvas.create_rectangle(
            x - CARD_W // 2,
            y - CARD_H // 2,
            x + CARD_W // 2,
            y + CARD_H // 2,
            fill=theme.PANEL,
            stipple="gray50",
            outline="",
            tags=(_VEIL_TAG,),
        )

    def _on_click(self, event: tk.Event) -> None:
        card_id = self.card_at(event)
        if card_id is not None and self.on_card_click:
            self.on_card_click(card_id)
