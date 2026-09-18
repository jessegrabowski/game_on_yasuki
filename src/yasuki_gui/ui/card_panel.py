import tkinter as tk

from yasuki_core.engine.rules.vocabulary.modifiers import Stat
from yasuki_gui import theme
from yasuki_gui.ui.floating_panel import BORDER, FloatingPanel, TITLEBAR_H
from yasuki_gui.ui.geometry import widget_size
from yasuki_gui.ui.images import ImageProvider
from yasuki_gui.visuals.cardface import RenderCard
from yasuki_gui.visuals.sprite import CardSpriteVisual

# What a card drawn to be looked at but never picked is tagged with, so that a click on it answers
# nothing while the view key still finds it.
_SHOWN_PREFIX = "shown:"


class CardPanel(FloatingPanel):
    """A floating panel whose body is a canvas of card sprites.

    Every window that shows cards over the board is one of these, so they cannot disagree about how
    a card is drawn, how a click finds one, or which card the view key enlarges. A subclass lays
    cards out with :meth:`draw_card` and reads clicks back with :meth:`card_at`. The view key itself
    belongs to the window, which asks each surface :meth:`card_under_pointer`.

    Attributes
    ----------
    canvas : tkinter.Canvas
        Where the cards are drawn, filling the body.
    """

    def __init__(
        self,
        master: tk.Misc,
        title: str,
        *,
        width: int,
        height: int,
        closable: bool = False,
        images: ImageProvider | None = None,
        tag_prefix: str = "card:",
        bg: str = theme.SURFACE,
    ):
        """Build the panel, unplaced.

        Parameters
        ----------
        master : tkinter.Misc
            The widget the panel floats over.
        title : str
            The name shown in the title bar.
        width : int
            How wide the panel opens.
        height : int
            How tall the panel opens, title bar included.
        closable : bool, optional
            Whether the player may dismiss the panel. Default False.
        images : ImageProvider, optional
            Where card art comes from. None draws every card as a named placeholder. Default None.
        tag_prefix : str, optional
            What a pickable card's sprite is tagged with, ahead of its id, and what :meth:`card_at`
            reads back. Default ``"card:"``.
        bg : str, optional
            The canvas color. Default the table felt.
        """
        super().__init__(master, title, width=width, height=height, closable=closable)
        self.images = images
        self.tag_prefix = tag_prefix
        self._shown_prefix = f"{tag_prefix}{_SHOWN_PREFIX}"
        # Sized to the panel it fills, so a layout computed before Tk maps it is the one it ends up
        # with.
        self.canvas = tk.Canvas(
            self.body,
            bg=bg,
            highlightthickness=0,
            width=width - 2 * BORDER,
            height=height - TITLEBAR_H - 2 * BORDER,
        )
        self.canvas.pack(fill="both", expand=True)
        # The visuals are kept, not just their positions: each holds the strong reference to its
        # PhotoImage, and Tk blanks a sprite the moment nothing references its image.
        self._drawn: dict[str, CardSpriteVisual] = {}

    def clear(self) -> None:
        """Empty the canvas and forget every card drawn on it."""
        self.canvas.delete("all")
        self._drawn = {}

    def draw_card(
        self,
        card: RenderCard,
        x: int,
        y: int,
        *,
        selected: bool = False,
        stats: dict[str, dict[Stat, int]] | None = None,
        pickable: bool = True,
    ) -> str:
        """Draw ``card`` centered on ``x``, ``y`` and return the tag its sprite carries.

        Parameters
        ----------
        card : RenderCard
            The card to draw, front up or back up as it says.
        x, y : int
            The sprite's center on the canvas.
        selected : bool, optional
            Whether to ring it as picked. Default False.
        stats : dict, optional
            ``GameView.stats``, for the Force and Chi stamps. Default None, which stamps nothing.
        pickable : bool, optional
            Whether a click on it answers with its id. A card drawn only to be looked at, such as
            the Province in a battle lane, is not. Default True.
        """
        prefix = self.tag_prefix if pickable else self._shown_prefix
        visual = CardSpriteVisual(card, x, y, f"{prefix}{card.id}", images=self.images, stats=stats)
        visual.draw(self.canvas, selected=selected)
        self._drawn[visual.tag] = visual
        return visual.tag

    def card_at(self, event: tk.Event) -> str | None:
        """The id of the pickable card under the pointer, or None.

        Topmost first, because a unit is drawn as a tower: taking the bottommost would answer a
        click on a Personality with the Follower fanned out behind him.
        """
        tag = self._tag_at(event.x, event.y)
        if tag is None or tag.startswith(self._shown_prefix):
            return None
        return tag[len(self.tag_prefix) :]

    def card_under_pointer(self, x_root: int, y_root: int) -> tuple[RenderCard, int, int] | None:
        """Find the card under a screen point.

        Returns
        -------
        card : RenderCard
            The card there.
        x_root, y_root : int
            Its center in screen coordinates.

        None when the panel is closed, rolled up, or the point is off its cards.
        """
        if not self.showing or self.minimized:
            return None
        x = x_root - self.canvas.winfo_rootx()
        y = y_root - self.canvas.winfo_rooty()
        width, height = widget_size(self.canvas)
        if not (0 <= x < width and 0 <= y < height):
            return None
        tag = self._tag_at(x, y)
        if tag is None:
            return None
        visual = self._drawn[tag]
        return (
            visual.card,
            self.canvas.winfo_rootx() + int(visual.x - self.canvas.canvasx(0)),
            self.canvas.winfo_rooty() + int(visual.y - self.canvas.canvasy(0)),
        )

    def _tag_at(self, x: int, y: int) -> str | None:
        # Window coordinates into canvas coordinates, for a panel that scrolls its cards.
        canvas_x, canvas_y = self.canvas.canvasx(x), self.canvas.canvasy(y)
        for item in reversed(self.canvas.find_overlapping(canvas_x, canvas_y, canvas_x, canvas_y)):
            for tag in self.canvas.gettags(item):
                if tag in self._drawn:
                    return tag
        return None
