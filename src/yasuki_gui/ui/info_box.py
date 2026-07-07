import tkinter as tk
from collections.abc import Callable
from functools import partial

from yasuki_core.engine.players import PlayerId
from yasuki_core.engine.intents import SetHonor
from yasuki_core.engine.table import DeckKey, ZoneKey, ZoneRole
from yasuki_core.game_pieces.constants import Side
from yasuki_gui import theme
from yasuki_gui.field_view import FieldView
from yasuki_gui.ui.dialogs import Dialogs
from yasuki_gui.ui.images import ImageProvider

try:
    from PIL import Image, ImageTk  # type: ignore
except Exception:  # pragma: no cover
    Image = None  # type: ignore
    ImageTk = None  # type: ignore

_CELL_W = 58
_CELL_H = 78

# The 3×3 grid of off-board piles, top-to-bottom and left-to-right. Decks and the hand count are
# display-only; discard and banish piles open an inspect dialog. The third column holds only the
# hand count (the playable hand itself stays on the board); its lower cells are intentionally blank.
_DECK_CELLS: tuple[tuple[int, int, Side, str], ...] = (
    (0, 0, Side.FATE, "Fate"),
    (0, 1, Side.DYNASTY, "Dynasty"),
)
_PILE_CELLS: tuple[tuple[int, int, ZoneRole, str], ...] = (
    (1, 0, ZoneRole.FATE_DISCARD, "Fate disc"),
    (1, 1, ZoneRole.DYNASTY_DISCARD, "Dyn disc"),
    (2, 0, ZoneRole.FATE_BANISH, "Fate ban"),
    (2, 1, ZoneRole.DYNASTY_BANISH, "Dyn ban"),
)


class _Cell(tk.Canvas):
    """A compact pile slot: a card silhouette with a count, captioned. Decks draw as a back, piles
    as a face when occupied; an empty pile draws as an outline."""

    def __init__(self, master: tk.Misc, caption: str, on_click: Callable[[], None] | None = None):
        super().__init__(
            master, width=_CELL_W, height=_CELL_H, bg=theme.PANEL, highlightthickness=0
        )
        self._caption = caption
        if on_click is not None:
            self.bind("<Button-1>", lambda e: on_click())
            self.configure(cursor="hand2")

    def render(self, count: int, *, is_back: bool) -> None:
        self.delete("all")
        self.create_text(
            _CELL_W // 2, 7, text=self._caption, fill=theme.INK_DIM, font=theme.serif(8)
        )
        x0, y0, x1, y1 = 4, 16, _CELL_W - 4, _CELL_H - 4
        if count > 0:
            fill = theme.GOLD if is_back else theme.CARD_FACE
            self.create_rectangle(x0, y0, x1, y1, fill=fill, outline=theme.LINE_SOFT)
            ink = "#ffffff" if is_back else theme.INK
            self.create_text(
                _CELL_W // 2,
                (y0 + y1) // 2,
                text=str(count),
                fill=ink,
                font=theme.serif(15, "bold"),
            )
        else:
            self.create_rectangle(x0, y0, x1, y1, outline=theme.LINE_SOFT, dash=(2, 2))


class PlayerInfoBox(tk.Frame):
    """The off-board panel for one seat: avatar, name, editable honor, and a 3×3 grid of the seat's
    decks, discard and banish piles, and hand count.

    Reads every count and top card from the field's active render source (the redacted projection in
    rules mode), so the opponent's box shows only what the viewer is entitled to — counts, never
    hidden identities. Honor edits dispatch a ``SetHonor`` intent and so apply only in the manual
    sandbox; the rules engine owns honor during play.
    """

    def __init__(
        self,
        master: tk.Misc,
        field: FieldView,
        owner: PlayerId,
        on_deck_activated: Callable[[DeckKey], None] | None = None,
    ):
        super().__init__(master, bg=theme.PANEL)
        self.field = field
        self.owner = owner
        self._on_deck_activated = on_deck_activated
        self._honor_text = tk.StringVar()

        self._avatar_canvas = tk.Canvas(
            self, width=50, height=50, bg=theme.PANEL, highlightthickness=0
        )
        self._avatar_canvas.grid(row=0, column=0, rowspan=2, padx=8, pady=(8, 4))
        self._avatar_photo = None
        name = field.state.seats[owner].name
        self._avatar_initials = self._initials(name)
        self._draw_avatar_circle()

        self._name_label = tk.Label(
            self, text=name, fg=theme.INK, bg=theme.PANEL, font=theme.serif(13)
        )
        self._name_label.grid(row=0, column=1, sticky="w", padx=(0, 8), pady=(8, 0))

        self._honor_label = tk.Label(
            self,
            textvariable=self._honor_text,
            fg=theme.GOLD,
            bg=theme.PANEL,
            font=theme.serif(14, "bold"),
        )
        self._honor_label.grid(row=1, column=1, sticky="w", padx=(0, 8), pady=(0, 4))
        self._honor_label.bind("<Button-1>", lambda e: self._adjust(1))
        self._honor_label.bind("<Button-2>", lambda e: self._adjust(-1))
        self._honor_label.bind("<Button-3>", lambda e: self._adjust(-1))
        self._honor_label.bind("<MouseWheel>", self._on_wheel)
        self._honor_label.bind("<Button-4>", lambda e: self._adjust(1))
        self._honor_label.bind("<Button-5>", lambda e: self._adjust(-1))
        self._honor_label.bind("<Enter>", self._on_hover)
        self._honor_label.bind("<Leave>", lambda e: self._restore_honor_bg())

        self._grid = tk.Frame(self, bg=theme.PANEL)
        self._grid.grid(row=2, column=0, columnspan=2, sticky="ew", padx=6, pady=(0, 8))
        self._deck_cells: dict[Side, _Cell] = {}
        self._pile_cells: dict[ZoneRole, _Cell] = {}
        self._build_cells()

        self.grid_columnconfigure(1, weight=1)
        self.refresh()

    # ----- header (avatar / name / honor) -----------------------------------

    @staticmethod
    def _initials(name: str) -> str:
        return "".join(part[0].upper() for part in name.split()[:2]) or "?"

    def _editable(self) -> bool:
        return self.owner is self.field.seat

    def _adjust(self, delta: int) -> None:
        if not self._editable():
            return
        self.field.dispatch(SetHonor(delta=delta))
        self.refresh()

    def _on_wheel(self, event: tk.Event) -> None:
        if event.delta:
            self._adjust(1 if event.delta > 0 else -1)

    def _on_hover(self, event: tk.Event) -> None:
        if self._editable():
            self._honor_label.configure(bg=theme.GOLD, fg="#ffffff")

    def _restore_honor_bg(self) -> None:
        self._honor_label.configure(
            bg=theme.PANEL, fg=theme.GOLD if self._editable() else theme.INK_DIM
        )

    def _draw_avatar_circle(self) -> None:
        c = self._avatar_canvas
        c.delete("all")
        c.create_oval(3, 3, 47, 47, fill=theme.AVATAR_BG, outline="")
        c.create_text(
            25,
            25,
            text=self._avatar_initials,
            fill=theme.AVATAR_FG,
            font=("TkDefaultFont", 14, "bold"),
        )

    def set_profile(self, name: str | None, avatar_path: str | None) -> None:
        if name:
            self._name_label.configure(text=name)
            self._avatar_initials = self._initials(name)
        if avatar_path and Image is not None and ImageTk is not None:
            try:
                img = Image.open(avatar_path)
                img = img.resize((50, 50), getattr(Image, "LANCZOS", None) or Image.BILINEAR)
                photo = ImageTk.PhotoImage(img, master=self._avatar_canvas)
                self._avatar_canvas.delete("all")
                self._avatar_canvas.create_image(25, 25, image=photo)
                self._avatar_photo = photo  # keep a reference so Tk does not GC it
                return
            except OSError:
                pass
        self._draw_avatar_circle()

    # ----- the 3×3 pile grid -------------------------------------------------

    def _build_cells(self) -> None:
        for row, col, side, caption in _DECK_CELLS:
            # The dynasty deck is clickable — it hosts the Legacy rulebook ability; other decks stay
            # display-only. deck_menu gates the action to the human's own deck.
            on_click = None
            if side is Side.DYNASTY and self._on_deck_activated is not None:
                on_click = partial(self._on_deck_activated, DeckKey(self.owner, side))
            cell = _Cell(self._grid, caption, on_click=on_click)
            cell.grid(row=row, column=col, padx=2, pady=2)
            self._deck_cells[side] = cell
        for row, col, role, caption in _PILE_CELLS:
            cell = _Cell(self._grid, caption, on_click=partial(self._inspect, role, caption))
            cell.grid(row=row, column=col, padx=2, pady=2)
            self._pile_cells[role] = cell
        self._hand_cell = _Cell(self._grid, "Hand")
        self._hand_cell.grid(row=0, column=2, padx=2, pady=2)

    def _inspect(self, role: ZoneRole, label: str) -> None:
        cards = self.field.zone_render_cards(ZoneKey(self.owner, role))
        if not cards:
            return
        master = self.winfo_toplevel()
        Dialogs(master, ImageProvider(master)).deck_inspect(cards, label)

    def cell_counts(self) -> dict[str, int]:
        """The count shown in each grid cell, keyed by a stable cell name, read from the field's
        active source. Pure data with no Tk, so the box's derivation is testable."""
        counts = {
            f"{side.name.lower()}_deck": self.field.deck_summary(DeckKey(self.owner, side))[0]
            for side in (Side.FATE, Side.DYNASTY)
        }
        for _, _, role, _ in _PILE_CELLS:
            counts[role.value] = len(self.field.zone_render_cards(ZoneKey(self.owner, role)))
        counts["hand"] = self.field.hand_count(self.owner)
        return counts

    def refresh(self) -> None:
        """Resync the honor header and every pile count with the field's current source."""
        honor = self.field.state.seats[self.owner].honor
        self._honor_text.set(f"Honor {honor}")
        editable = self._editable()
        self._honor_label.configure(
            fg=theme.GOLD if editable else theme.INK_DIM, cursor="hand2" if editable else ""
        )
        counts = self.cell_counts()
        for side, cell in self._deck_cells.items():
            cell.render(counts[f"{side.name.lower()}_deck"], is_back=True)
        for role, cell in self._pile_cells.items():
            cell.render(counts[role.value], is_back=False)
        self._hand_cell.render(counts["hand"], is_back=True)
