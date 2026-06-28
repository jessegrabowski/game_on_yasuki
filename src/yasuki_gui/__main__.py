import logging
import tkinter as tk

from yasuki_core.engine.players import PlayerId
from yasuki_core.engine.table import SetHonor
from yasuki_gui import theme
from yasuki_gui.config import DEBUG_MODE as GUI_DEBUG_MODE, load_hotkeys
from yasuki_gui.field_view import FieldView
from yasuki_gui.session import build_demo_state, build_state_from_deck
from yasuki_gui.ui.menus import build_menubar

logger = logging.getLogger(__name__)

# Optional PIL import for avatar images
try:
    from PIL import Image, ImageTk  # type: ignore
except Exception:  # pragma: no cover
    Image = None  # type: ignore
    ImageTk = None  # type: ignore

LOCAL_DEBUG_OVERRIDE = False


class PlayerPanel(tk.Frame):
    """Sidebar summary for one seat: avatar, name, and honor.

    Honor reads from the table and is editable only when the panel's seat is the one being played;
    an adjustment dispatches a ``SetHonor`` intent rather than tracking a local counter, so the
    table stays the single source of truth.
    """

    def __init__(self, master: tk.Misc, field: FieldView, owner: PlayerId):
        super().__init__(master, bg=theme.PANEL)
        self.field = field
        self.owner = owner
        self.honor = tk.IntVar(value=field.state.seats[owner].honor)
        self._honor_text = tk.StringVar()

        self._avatar_canvas = tk.Canvas(
            self, width=50, height=50, bg=theme.PANEL, highlightthickness=0
        )
        self._avatar_canvas.grid(row=0, column=0, rowspan=2, padx=8, pady=8)
        self._avatar_photo = None
        name = field.state.seats[owner].name
        self._avatar_initials = self._initials(name)
        self._draw_avatar_circle()

        self._name_label = tk.Label(
            self, text=name, fg=theme.INK, bg=theme.PANEL, font=theme.serif(13)
        )
        self._name_label.grid(row=0, column=1, sticky="w", padx=(0, 8), pady=(8, 0))

        self.honor_label = tk.Label(
            self,
            textvariable=self._honor_text,
            fg=theme.GOLD,
            bg=theme.PANEL,
            font=theme.serif(14, "bold"),
        )
        self.honor_label.grid(row=1, column=1, sticky="w", padx=(0, 8), pady=(0, 8))

        # Left click raises honor, right/middle lowers it; the wheel does both.
        self.honor_label.bind("<Button-1>", lambda e: self._adjust(1))
        self.honor_label.bind("<Button-2>", lambda e: self._adjust(-1))
        self.honor_label.bind("<Button-3>", lambda e: self._adjust(-1))
        self.honor_label.bind("<MouseWheel>", self._on_wheel)
        self.honor_label.bind("<Button-4>", lambda e: self._adjust(1))
        self.honor_label.bind("<Button-5>", lambda e: self._adjust(-1))
        self.honor_label.bind("<Enter>", self._on_hover)
        self.honor_label.bind("<Leave>", lambda e: self._restore_honor_bg())

        self.grid_columnconfigure(1, weight=1)
        self.refresh()

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
            self.honor_label.configure(bg=theme.GOLD, fg="#ffffff")

    def _restore_honor_bg(self) -> None:
        self.honor_label.configure(
            bg=theme.PANEL, fg=theme.GOLD if self._editable() else theme.INK_DIM
        )

    def refresh(self) -> None:
        """Resync honor and edit affordance with the table; call after any state change."""
        self.honor.set(self.field.state.seats[self.owner].honor)
        self._honor_text.set(f"Honor {self.field.state.seats[self.owner].honor}")
        editable = self._editable()
        self.honor_label.configure(
            fg=theme.GOLD if editable else theme.INK_DIM,
            cursor="hand2" if editable else "",
        )

    def _draw_avatar_circle(self):
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


def main() -> None:
    debug_enabled = GUI_DEBUG_MODE or LOCAL_DEBUG_OVERRIDE

    root = tk.Tk()
    root.title("Game on, Yasuki!" if not debug_enabled else "!! DEBUG DEBUG DEBUG !!")

    hotkeys = load_hotkeys()
    screen_w, screen_h = root.winfo_screenwidth(), root.winfo_screenheight()
    root.geometry(f"{screen_w}x{screen_h}+0+0")

    container = tk.Frame(root)
    container.pack(fill="both", expand=True)
    sidebar_w = 220
    sidebar = tk.Frame(container, width=sidebar_w, bg=theme.PANEL)
    sidebar.pack(side="left", fill="y")
    content = tk.Frame(container)
    content.pack(side="left", fill="both", expand=True)

    root.update_idletasks()
    win_w, win_h = root.winfo_width(), root.winfo_height()
    canvas_w, canvas_h = max(400, win_w - sidebar_w), max(300, win_h)

    field = FieldView(content, width=canvas_w, height=canvas_h)
    field.pack(fill="both", expand=True)
    field.configure_hotkeys(hotkeys)
    if debug_enabled:
        import yasuki_gui.config as gui_config

        gui_config.DEBUG_MODE = True

    # Deal the bundled deck (needs the database); fall back to the DB-free placeholder deck so the
    # client still launches without a database or card images.
    try:
        state, human_seat = build_state_from_deck()
    except Exception as exc:
        logger.warning("Could not load the bundled deck, using the placeholder deck: %s", exc)
        state, human_seat = build_demo_state()
    field.load_state(state, human_seat)

    # The human seat sits at the bottom, the AI-reserved opponent across the top.
    opponent_panel = PlayerPanel(sidebar, field, PlayerId.P2)
    human_panel = PlayerPanel(sidebar, field, PlayerId.P1)

    def relayout_panels() -> None:
        """Place the seat being played on the bottom and refresh both panels. Driven by the debug
        seat toggle; with no toggle the human stays on the bottom for the whole game."""
        for panel in (opponent_panel, human_panel):
            panel.pack_forget()
        bottom, top = (
            (human_panel, opponent_panel)
            if field.seat is PlayerId.P1
            else (opponent_panel, human_panel)
        )
        top.pack(side="top", fill="x")
        bottom.pack(side="bottom", fill="x")
        opponent_panel.refresh()
        human_panel.refresh()

    field.on_local_player_changed = relayout_panels
    relayout_panels()

    menubar = build_menubar(root, field)
    root.config(menu=menubar)

    def apply_profile_to_panels() -> None:
        name = getattr(field, "profile_name", None)
        avatar = getattr(field, "profile_avatar", None)
        panel = human_panel if field.seat is PlayerId.P1 else opponent_panel
        panel.set_profile(name, avatar)
        root.update_idletasks()

    field.apply_profile_to_panels = apply_profile_to_panels

    root.mainloop()


if __name__ == "__main__":
    main()
