import logging
import tkinter as tk
from collections.abc import Callable

from yasuki_gui.field_view import FieldView
from yasuki_gui.config import load_hotkeys, DEBUG_MODE as GUI_DEBUG_MODE
from yasuki_gui.constants import MIN_HONOR, MAX_HONOR
from yasuki_gui.session import build_demo_state
from yasuki_gui.ui.menus import build_menubar
from yasuki_core.engine.players import PlayerId

logger = logging.getLogger(__name__)

# Optional PIL import for avatar images
try:
    from PIL import Image, ImageTk  # type: ignore
except Exception:  # pragma: no cover
    Image = None  # type: ignore
    ImageTk = None  # type: ignore

LOCAL_DEBUG_OVERRIDE = False


class PlayerPanel(tk.Frame):
    """
    Simple player summary with avatar, username, and honor counter.
    """

    def __init__(
        self,
        master: tk.Misc,
        username: str,
        owner: PlayerId | None = None,
        get_local_player: Callable | None = None,
        initial_honor: int = 10,
    ):
        super().__init__(master, bg="#1f1f1f")
        self.username = username
        self.owner = owner
        self._get_local_player = get_local_player
        self.honor = tk.IntVar(value=initial_honor)

        # Avatar placeholder (circle) and name
        self._avatar_canvas = tk.Canvas(
            self, width=50, height=50, bg="#1f1f1f", highlightthickness=0
        )
        self._avatar_canvas.grid(row=0, column=0, rowspan=2, padx=8, pady=8)
        self._avatar_photo = None
        self._draw_avatar_circle()
        # Draw initials label on top
        initials = "".join([part[0].upper() for part in username.split()[:2]]) or "?"
        self._avatar_initials = initials
        self._avatar_canvas.create_text(
            25,
            25,
            text=initials,
            fill="white",
            font=("TkDefaultFont", 14, "bold"),
            tags=("initials",),
        )
        # Username label
        self._name_label = tk.Label(self, text=username, fg="#eaeaea", bg="#1f1f1f")
        self._name_label.grid(row=0, column=1, sticky="w", padx=(0, 8), pady=(8, 0))

        # Honor counter (big number, clickable)
        honor_lbl = tk.Label(
            self,
            textvariable=self.honor,
            fg="#ffd166",
            bg="#1f1f1f",
            font=("TkDefaultFont", 18, "bold"),
        )
        honor_lbl.grid(row=1, column=1, sticky="w", padx=(0, 8), pady=(0, 8))
        self.honor_label = honor_lbl

        # Click bindings: left = +1, right/middle = -1
        # Replace bindings to guard by ownership
        def _can_edit() -> bool:
            try:
                if self.owner is None or self._get_local_player is None:
                    return True
                return self.owner == self._get_local_player()
            except Exception:
                return False

        honor_lbl.bind("<Button-1>", lambda e: self._adjust(1) if _can_edit() else None)
        honor_lbl.bind(
            "<Button-2>", lambda e: self._adjust(-1) if _can_edit() else None
        )  # middle (trackpads)
        honor_lbl.bind(
            "<Button-3>", lambda e: self._adjust(-1) if _can_edit() else None
        )  # right click
        # Scroll wheel bindings: Windows/macOS use <MouseWheel>; Linux/X11 uses Button-4/5
        honor_lbl.bind("<MouseWheel>", lambda e: self._on_wheel(e) if _can_edit() else None)
        honor_lbl.bind("<Button-4>", lambda e: self._adjust(1) if _can_edit() else None)
        honor_lbl.bind("<Button-5>", lambda e: self._adjust(-1) if _can_edit() else None)

        # Prevent shrinking
        self.grid_columnconfigure(1, weight=1)

    def _adjust(self, delta: int) -> None:
        update = self.honor.get() + delta

        self.honor.set(min(max(update, MIN_HONOR), MAX_HONOR))

    def _on_wheel(self, event: tk.Event) -> None:
        # event.delta is positive when scrolled up, negative when down (units vary by platform)
        d = getattr(event, "delta", 0)
        if d == 0:
            return
        self._adjust(1 if d > 0 else -1)

    def _draw_avatar_circle(self):
        c = self._avatar_canvas
        c.delete("all")
        r = 22
        cx, cy = 25, 25
        c.create_oval(cx - r, cy - r, cx + r, cy + r, fill="#3b82f6", outline="")

    def set_profile(self, name: str | None, avatar_path: str | None) -> None:
        # Update the username label
        if name:
            self._name_label.configure(text=name)
            self._avatar_initials = "".join([part[0].upper() for part in name.split()[:2]]) or "?"
        # Update the avatar image if provided; else draw circle with initials
        c = self._avatar_canvas
        c.delete("all")
        if avatar_path and Image is not None and ImageTk is not None:
            try:
                img = Image.open(avatar_path)
                img = img.resize((50, 50), getattr(Image, "LANCZOS", None) or Image.BILINEAR)
                photo = ImageTk.PhotoImage(img, master=c)
                c.create_image(25, 25, image=photo)
                self._avatar_photo = photo  # keep ref
                return
            except Exception:
                pass
        # Fallback: colored circle + initials
        self._draw_avatar_circle()
        c.create_text(
            25, 25, text=self._avatar_initials, fill="white", font=("TkDefaultFont", 14, "bold")
        )


def main() -> None:
    debug_enabled = GUI_DEBUG_MODE or LOCAL_DEBUG_OVERRIDE

    root = tk.Tk()
    root.title("Game on, Yasuki!" if not debug_enabled else "!! DEBUG DEBUG DEBUG !!")

    hotkeys = load_hotkeys()
    # Use actual screen size for outer window and set geometry; then measure client area
    screen_w, screen_h = root.winfo_screenwidth(), root.winfo_screenheight()
    root.geometry(f"{screen_w}x{screen_h}+0+0")

    # Layout: left sidebar for players, right content for field
    container = tk.Frame(root)
    container.pack(fill="both", expand=True)
    sidebar_w = 220
    sidebar = tk.Frame(container, width=sidebar_w, bg="#1f1f1f")
    sidebar.pack(side="left", fill="y")
    content = tk.Frame(container)
    content.pack(side="left", fill="both", expand=True)

    # Realize geometry to get actual client sizes
    root.update_idletasks()
    win_w, win_h = root.winfo_width(), root.winfo_height()
    CW, CH = max(400, win_w - sidebar_w), max(300, win_h)  # canvas width/height

    # Field to the right of sidebar (use content width/height, not total window)
    field = FieldView(content, width=CW, height=CH)
    field.pack(fill="both", expand=True)
    field.configure_hotkeys(hotkeys)
    # If debug is enabled, ensure controller will bind Ctrl+T
    if debug_enabled:
        try:
            import yasuki_gui.config as gui_config

            gui_config.DEBUG_MODE = True  # type: ignore[attr-defined]
        except Exception:
            pass

    # Build the table from placeholder decks (DB-free) and render it from the human's seat.
    state, human_seat = build_demo_state()
    field.load_state(state, human_seat)

    # Players in the left sidebar: create with owners and gate honor edits
    def get_lp() -> PlayerId:
        return field.seat

    top_panel = PlayerPanel(
        sidebar,
        username=state.seats[PlayerId.P2].name,
        owner=PlayerId.P2,
        get_local_player=get_lp,
        initial_honor=state.seats[PlayerId.P2].honor,
    )
    bottom_panel = PlayerPanel(
        sidebar,
        username=state.seats[PlayerId.P1].name,
        owner=PlayerId.P1,
        get_local_player=get_lp,
        initial_honor=state.seats[PlayerId.P1].honor,
    )

    def restack_panels() -> None:
        # Clear existing placement
        for w in (top_panel, bottom_panel):
            try:
                w.pack_forget()
            except Exception:
                pass
        # Active player should be on bottom
        if field.local_player == PlayerId.P1:
            top_panel.pack(side="top", fill="x")  # P2 on top
            bottom_panel.pack(side="bottom", fill="x")  # P1 on bottom
        else:
            bottom_panel.pack(side="top", fill="x")  # P1 on top
            top_panel.pack(side="bottom", fill="x")  # P2 on bottom

    # expose callback for controller to call on toggle
    setattr(field, "on_local_player_changed", restack_panels)

    # Initial stack per starting player
    restack_panels()

    # Build menu bar with Preferences
    menubar = build_menubar(root, field)
    root.config(menu=menubar)

    # Apply profile to panels helper
    def apply_profile_to_panels():
        name = getattr(field, "profile_name", None)
        avatar = getattr(field, "profile_avatar", None)
        # Apply to active player's panel on bottom
        if field.local_player == PlayerId.P1:
            bottom_panel.set_profile(name, avatar)
        else:
            top_panel.set_profile(name, avatar)
        # Force immediate UI update
        root.update_idletasks()

    setattr(field, "apply_profile_to_panels", apply_profile_to_panels)

    root.mainloop()


if __name__ == "__main__":
    main()
