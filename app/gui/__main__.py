import logging
import tkinter as tk
from collections.abc import Callable
from app.game_pieces.constants import Side
from app.game_pieces.fate import FateCard, FateAction, FateAttachment, FateRing
from app.game_pieces.dynasty import DynastyCard, DynastyPersonality, DynastyHolding, DynastyEvent
from app.game_pieces.deck import Deck
from app.gui.field_view import FieldView
from app.gui.config import load_hotkeys, DEBUG_MODE as GUI_DEBUG_MODE
from app.gui.constants import CARD_W, CARD_H, MIN_HONOR, MAX_HONOR
from app.engine.zones import (
    HandZone,
    ProvinceZone,
    FateDiscardZone,
    DynastyDiscardZone,
    BattlefieldZone,
)
from app.gui.ui.menus import build_menubar
from app.engine.players import PlayerId

logger = logging.getLogger(__name__)

# Optional PIL import for avatar images
try:
    from PIL import Image, ImageTk  # type: ignore
except Exception:  # pragma: no cover
    Image = None  # type: ignore
    ImageTk = None  # type: ignore

LOCAL_DEBUG_OVERRIDE = False
# Choose which player is local on startup; if P2, rotate board 180° before showing
STARTING_PLAYER: PlayerId = PlayerId.P1


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
            import app.gui.config as gui_config

            gui_config.DEBUG_MODE = True  # type: ignore[attr-defined]
        except Exception:
            pass

    # Set the acting local player (starts as configured)
    field.local_player = STARTING_PLAYER

    # Battlefield is public/shared
    battlefield = BattlefieldZone()  # owner=None => shared
    field.set_battlefield_zone(battlefield)

    # Helper to add a player's layout (decks, discards, provinces, hand)
    def setup_player(
        owner: PlayerId, dynasty_x: int, fate_x: int, y_line: int, hand_y: int
    ) -> dict:
        # Hand zone spans most of the content width
        hand_tag = field.add_zone(HandZone(owner=owner), x=CW // 2, y=hand_y, w=CW - 200, h=120)
        # Build decks with concrete subtypes so defaults include front art
        dynasty_cards: list[DynastyCard] = []
        for i in range(1, 11):
            if i % 2 == 0:
                dynasty_cards.append(
                    DynastyHolding(
                        id=f"d{owner.value}-H{i}", name=f"Holding {i}", side=Side.DYNASTY
                    )
                )
            elif i % 3 == 0:
                dynasty_cards.append(
                    DynastyEvent(id=f"d{owner.value}-E{i}", name=f"Event {i}", side=Side.DYNASTY)
                )
            else:
                dynasty_cards.append(
                    DynastyPersonality(
                        id=f"d{owner.value}-P{i}", name=f"Personality {i}", side=Side.DYNASTY
                    )
                )
        fate_cards: list[FateCard] = []
        for i in range(1, 11):
            if i % 3 == 1:
                fate_cards.append(
                    FateAction(id=f"f{owner.value}-A{i}", name=f"Strategy {i}", side=Side.FATE)
                )
            elif i % 3 == 2:
                fate_cards.append(
                    FateAttachment(id=f"f{owner.value}-I{i}", name=f"Item {i}", side=Side.FATE)
                )
            else:
                fate_cards.append(
                    FateRing(id=f"f{owner.value}-R{i}", name=f"Ring {i}", side=Side.FATE)
                )
        dynasty_deck = Deck.build(dynasty_cards)
        fate_deck = Deck.build(fate_cards)
        d_tag = field.add_deck(dynasty_deck, x=dynasty_x, y=y_line, label="Dynasty Deck")
        f_tag = field.add_deck(fate_deck, x=fate_x, y=y_line, label="Fate Deck")
        # Assign deck ownership on visuals
        field._decks[d_tag].owner = owner
        field._decks[f_tag].owner = owner

        # Discards adjacent to decks (use content width for right-side)
        sign = -1 if owner == PlayerId.P1 else 1
        field.add_zone(
            DynastyDiscardZone(owner=owner),
            x=max(60, dynasty_x + sign * 120),
            y=y_line,
            w=CARD_W,
            h=CARD_H,
        )
        field.add_zone(
            FateDiscardZone(owner=owner),
            x=max(60, min(CW - 60, fate_x - sign * 120)),
            y=y_line,
            w=CARD_W,
            h=CARD_H,
        )

        # Provinces centered between decks (use content width center)
        centers = [
            int(CW // 2 - 1.5 * CARD_W),
            int(CW // 2 - 0.5 * CARD_W),
            int(CW // 2 + 0.5 * CARD_W),
            int(CW // 2 + 1.5 * CARD_W),
        ]
        centers = centers if owner == PlayerId.P1 else list(reversed(centers))
        for i, cx in enumerate(centers, start=1):
            field.add_zone(
                ProvinceZone(name=f"Province {i}", owner=owner), x=cx, y=y_line, w=CARD_W, h=CARD_H
            )
        return {
            "owner": owner,
            "hand_tag": hand_tag,
            "fate_deck_tag": f_tag,
            "dynasty_deck_tag": d_tag,
        }

    # Player 2 at top (use content width for deck positions)
    p2 = setup_player(
        owner=PlayerId.P2,
        dynasty_x=CW - 200,  # swapped so after rotation dynasty is left
        fate_x=200,  # swapped so after rotation fate is right
        y_line=200,
        hand_y=60,
    )
    # Player 1 at bottom
    p1 = setup_player(
        owner=PlayerId.P1,
        dynasty_x=200,
        fate_x=CW - 200,
        y_line=CH - 200,
        hand_y=CH - 60,
    )

    # After setup: shuffle all decks
    for dv in field._decks.values():
        dv.deck.shuffle()

    # Draw 5 Fate cards into each player's hand
    for pdata in (p1, p2):
        ftag = pdata["fate_deck_tag"]
        htag = pdata["hand_tag"]
        owner = pdata["owner"]
        dv = field._decks.get(ftag)
        hv = field._hands.get(htag)
        if not dv or not hv:
            continue
        for _ in range(5):
            card = dv.deck.draw_one()
            if card is None:
                break
            # Assign ownership and show face up in hand (opponent will still see back per HandVisual)
            if getattr(card, "owner", None) != owner:
                try:
                    object.__setattr__(card, "owner", owner)
                except Exception:
                    pass
            card.turn_face_up()
            hv.zone.add(card)
        # Redraw visuals
        field.redraw_deck(ftag)
        field.redraw_zone(htag)

    # Ensure the active player is on the bottom on startup
    root.update_idletasks()
    if field.local_player == PlayerId.P2 and hasattr(field, "flip_orientation"):
        field.flip_orientation()
        if hasattr(field, "redraw_all"):
            field.redraw_all()

    # Demo cards (tracked on battlefield, shared) placed relative to content width/height
    # Use concrete subtypes so default fronts are available
    from app.game_pieces.fate import FateAction as _DemoFate
    from app.game_pieces.dynasty import DynastyPersonality as _DemoDyn

    field.add_card(
        _DemoFate(id="demo-1", name="Sample Fate", side=Side.FATE), x=CW // 2 - 100, y=CH // 2 - 50
    )
    field.add_card(
        _DemoDyn(id="demo-2", name="Sample Dynasty", side=Side.DYNASTY),
        x=CW // 2 + 100,
        y=CH // 2 - 50,
    )

    # Players in the left sidebar: create with owners and gate honor edits
    def get_lp() -> PlayerId:
        return field.local_player

    top_panel = PlayerPanel(
        sidebar,
        username="Top Player (P2)",
        owner=PlayerId.P2,
        get_local_player=get_lp,
        initial_honor=10,
    )
    bottom_panel = PlayerPanel(
        sidebar,
        username="Bottom Player (P1)",
        owner=PlayerId.P1,
        get_local_player=get_lp,
        initial_honor=10,
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
