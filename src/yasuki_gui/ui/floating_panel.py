import tkinter as tk

from yasuki_gui import theme
from yasuki_gui.ui.geometry import widget_size

# Tall enough to read as a bar you take hold of rather than a stripe of padding.
TITLEBAR_H = 34
# The panel's outer edge, drawn in gold so the whole frame reads as one grabbable object.
BORDER = 3
# What is left of the panel once it is rolled up.
ROLLED_H = TITLEBAR_H + 2 * BORDER
# How much of the panel's width has to stay over the board. Its whole height cannot be asked for —
# a panel resized larger than the board would then have nowhere legal to sit — so what a drag
# preserves is a strip of title bar wide enough to take hold of again.
KEEP_VISIBLE = 80
MIN_W = 280
MIN_H = 140

ROLL_UP = "\u2013"  # en dash, the bar the panel rolls down to
UNROLL = "\u25a1"  # an empty box, the panel it rolls back out into
GRIP = "\u25e2"  # a filled corner, the one the panel resizes from


class FloatingPanel(tk.Frame):
    """A window inside the game: a frame laid over the board, with a bar to drag it by, a corner to
    resize it by, and a button that rolls it up to the bar.

    Placed rather than packed, so it covers the board instead of taking room from it. Subclasses
    build their content into :attr:`body` and leave the chrome alone.

    Attributes
    ----------
    body : tkinter.Frame
        Everything below the title bar, which is where a subclass puts its content.
    """

    def __init__(self, master: tk.Misc, title: str, *, width: int, height: int):
        """Build the panel, unplaced. It appears on the first :meth:`open_at`.

        Parameters
        ----------
        master : tkinter.Misc
            The widget the panel floats over, and the box it is dragged around inside.
        title : str
            The name shown in the title bar.
        width : int
            How wide the panel opens.
        height : int
            How tall the panel opens, title bar included.
        """
        super().__init__(
            master,
            bg=theme.SURFACE,
            highlightthickness=BORDER,
            highlightbackground=theme.GOLD,
            highlightcolor=theme.GOLD,
        )
        # Prefixed because these share a namespace with everything Tk and every subclass already
        # keep on a widget — ``_w`` is Tk's own path to it, and a panel that shadows one of those
        # stops working in a way that points nowhere near here.
        self._panel_left, self._panel_top = 0, 0
        self._panel_width, self._panel_height = width, height
        self._grab_at = (0, 0)
        self._minimized = False
        self._ever_opened = False

        self._build_titlebar(title)
        self.body = tk.Frame(self, bg=theme.SURFACE)
        self.body.pack(side="top", fill="both", expand=True)

        self._grip = tk.Label(
            self,
            text=GRIP,
            bg=theme.SURFACE,
            fg=theme.GOLD,
            font=theme.serif(13),
            cursor="bottom_right_corner",
            width=2,
            height=1,
        )
        self._grip.bind("<Button-1>", self._grab)
        self._grip.bind("<B1-Motion>", self._resize)
        # Added to whatever the board already listens for, which on a canvas is its own redraw.
        master.bind("<Configure>", self._on_board_resized, add="+")

    def _build_titlebar(self, title: str) -> None:
        """Pack the bar the panel is dragged by, and the button that rolls it up."""
        # Gold like the border, so the bar and the frame read as the same piece of chrome, and the
        # only part of the panel that is not the pale table underneath.
        bar = tk.Frame(self, bg=theme.GOLD, height=TITLEBAR_H, cursor="fleur")
        bar.pack(side="top", fill="x")
        bar.pack_propagate(False)  # hold the height against whatever the label asks for
        label = tk.Label(
            bar,
            text=title,
            bg=theme.GOLD,
            fg=theme.ON_DARK,
            font=theme.serif(12, "bold"),
            cursor="fleur",
        )
        label.pack(side="left", padx=10)
        for widget in (bar, label):
            widget.bind("<Button-1>", self._grab)
            widget.bind("<B1-Motion>", self._drag)

        self._roll = tk.Label(
            bar,
            text=ROLL_UP,
            bg=theme.GOLD_HOVER,
            fg=theme.ON_DARK,
            font=theme.serif(14, "bold"),
            width=3,
            cursor="hand2",
        )
        self._roll.pack(side="right", fill="y", padx=(0, 4), pady=4)
        self._roll.bind("<Button-1>", lambda _event: self.toggle_minimized())
        self._roll.bind("<Enter>", lambda _event: self._roll.configure(bg=theme.INK))
        self._roll.bind("<Leave>", lambda _event: self._roll.configure(bg=theme.GOLD_HOVER))

    @property
    def showing(self) -> bool:
        """Whether the panel is currently laid over the board."""
        return bool(self.place_info())

    @property
    def minimized(self) -> bool:
        """Whether the panel is rolled up to its title bar."""
        return self._minimized

    def open_at(self, x: int, y: int) -> None:
        """Lay the panel over the board, at ``x``, ``y`` the first time and wherever the player has
        since put it every time after. Safe to call on every refresh."""
        if self.showing:
            return
        if not self._ever_opened:
            self._panel_left, self._panel_top = x, y
            self._ever_opened = True
        self._apply()

    def open_over(self, left: int, top: int, width: int, height: int) -> None:
        """Lay the panel over the given box the first time, or where the player has since put it.

        A starting place rather than a dock: the panel is free to be dragged and resized off the box
        afterwards, and opening again keeps wherever it was left.

        Parameters
        ----------
        left : int
            The box's left edge, in the coordinates of what the panel floats over.
        top : int
            The box's top edge.
        width : int
            How wide to open. Trimmed to the board by :meth:`_clamp` if it does not fit.
        height : int
            How tall to open, title bar included.
        """
        if not self._ever_opened:
            self._panel_width, self._panel_height = width, height
        self.open_at(left, top)

    def close(self) -> None:
        """Take the panel off the board. Its size and position survive for the next open."""
        self.place_forget()

    def toggle_minimized(self) -> None:
        """Roll the panel up to its title bar, or unroll it to the size it had."""
        self._minimized = not self._minimized
        if self.showing:
            self._apply()

    def _apply(self) -> None:
        self._clamp()
        height = ROLLED_H if self._minimized else self._panel_height
        self.place(x=self._panel_left, y=self._panel_top, width=self._panel_width, height=height)
        self.lift()
        self._roll.configure(text=UNROLL if self._minimized else ROLL_UP)
        if self._minimized:
            self._grip.place_forget()
        else:
            self._grip.place(relx=1.0, rely=1.0, anchor="se")

    def _clamp(self) -> None:
        """Pull the panel back to somewhere it can be worked with: no bigger than the board, and far
        enough onto it that a strip of title bar is still there to take hold of.

        Every path that places the panel comes through here, so a board that shrinks under one
        already sitting near its edge cannot strand it out of reach.
        """
        board_w, board_h = widget_size(self.master)
        self._panel_width = max(min(self._panel_width, board_w), MIN_W)
        self._panel_height = max(min(self._panel_height, board_h), MIN_H)
        # The bar runs the panel's full width and sits at its top, so a strip of width keeps it
        # grabbable while the whole rolled-up height has to stay on for the bar to be on at all.
        self._panel_left = min(max(self._panel_left, 0), max(board_w - KEEP_VISIBLE, 0))
        self._panel_top = min(max(self._panel_top, 0), max(board_h - ROLLED_H, 0))

    def _on_board_resized(self, _event: tk.Event) -> None:
        """Re-place the panel against the board's new size, so one near an edge that has just moved
        comes back with it."""
        if self.showing:
            self._apply()

    def _grab(self, event: tk.Event) -> None:
        """Remember where the pointer took hold, so a drag can move by how far it travelled rather
        than jump the panel's corner to the pointer."""
        self._grab_at = (event.x_root, event.y_root)
        self.lift()

    def _travelled(self, event: tk.Event) -> tuple[int, int]:
        dx = event.x_root - self._grab_at[0]
        dy = event.y_root - self._grab_at[1]
        self._grab_at = (event.x_root, event.y_root)
        return dx, dy

    def _drag(self, event: tk.Event) -> None:
        """Move the panel with the pointer. :meth:`_apply` is what keeps it on the board."""
        dx, dy = self._travelled(event)
        self._panel_left += dx
        self._panel_top += dy
        self._apply()

    def _resize(self, event: tk.Event) -> None:
        """Grow or shrink the panel from its bottom-right corner. :meth:`_apply` is what keeps the
        result a size that still holds a title bar and something under it."""
        if self._minimized:
            return
        dx, dy = self._travelled(event)
        self._panel_width += dx
        self._panel_height += dy
        self._apply()
