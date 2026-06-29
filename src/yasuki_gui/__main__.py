import logging
import tkinter as tk

from yasuki_core.engine.players import PlayerId
from yasuki_core.engine.intents import SetHonor
from yasuki_core.engine.rules.actions import Action, Pass, ProduceGold, Recruit
from yasuki_core.engine.rules.decisions import (
    ChoosePayment,
    DecisionRequest,
    DecisionResponse,
    DiscardToHandSize,
)
from yasuki_core.engine.session import EngineSession
from yasuki_gui import theme
from yasuki_gui.config import DEBUG_MODE as GUI_DEBUG_MODE, load_hotkeys
from yasuki_gui.field_view import FieldView
from yasuki_gui.rules_runner import GameRunner
from yasuki_gui.session import build_demo_state, build_state_from_deck
from yasuki_gui.ui.menus import build_menubar
from yasuki_gui.ui.phase_bar import PhaseBar
from yasuki_gui.ui.prompt_box import PromptBox

logger = logging.getLogger(__name__)

# Optional PIL import for avatar images
try:
    from PIL import Image, ImageTk  # type: ignore
except Exception:  # pragma: no cover
    Image = None  # type: ignore
    ImageTk = None  # type: ignore

LOCAL_DEBUG_OVERRIDE = False

# How long the board lingers on "Opponent's turn" before the opponent's (AI-less) turn auto-runs.
OPPONENT_TURN_DELAY_MS = 700


def _describe_decision(request: DecisionRequest) -> tuple[str, str]:
    """A pending decision's prompt text and confirm-button label for the prompt box. Raise on an
    unmapped decision so a new request type can't ship without its prompt."""
    if isinstance(request, DiscardToHandSize):
        return f"discard {request.count} card(s)", "Discard"
    if isinstance(request, ChoosePayment):
        return f"pay {request.amount} gold", "Pay"
    raise ValueError(f"no prompt defined for {type(request).__name__}")


def _action_button_label(action: Action) -> str:
    """The prompt-box button label for a non-card action. Raise on an unmapped one."""
    if isinstance(action, Pass):
        return "Pass"
    raise ValueError(f"no button label for {type(action).__name__}")


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
    sidebar.grid_propagate(False)  # hold the fixed width; rows split the height by weight
    sidebar.grid_columnconfigure(0, weight=1)
    sidebar.grid_rowconfigure(0, weight=1)  # opponent seat (~20%)
    sidebar.grid_rowconfigure(1, weight=3)  # prompt box (~60%)
    sidebar.grid_rowconfigure(2, weight=1)  # your seat (~20%)
    content = tk.Frame(container)
    content.pack(side="left", fill="both", expand=True)

    root.update_idletasks()
    win_w, win_h = root.winfo_width(), root.winfo_height()
    canvas_w, canvas_h = max(400, win_w - sidebar_w), max(300, win_h)

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

    session = EngineSession.start(state, human_seat)
    runner = GameRunner(session, human_seat)

    field = FieldView(content, width=canvas_w, height=canvas_h)
    # The table backs panel and dialog reads; the board itself renders from the redacted projection.
    field.state = session.game.table
    field.seat = human_seat

    def refresh() -> None:
        view = runner.view()
        field.render_snapshot(view.table, human_seat)
        phase_bar.refresh(view)
        pending = runner.pending
        if pending is not None:
            prompt, button_label = _describe_decision(pending)
            can_confirm = pending.accepts(DecisionResponse(tuple(field.selection)))
            prompt_box.show(view, prompt, [(button_label, confirm_decision, can_confirm)])
        else:
            whose = "Your turn" if view.active is view.viewer else "Opponent's turn"
            # Non-card actions are buttons; card actions (produce gold) are invoked on the board.
            buttons = [
                (_action_button_label(action), lambda chosen=action: on_action(chosen), True)
                for action in runner.legal_actions()
                if isinstance(action, Pass)
            ]
            prompt_box.show(view, whose, buttons)
        opponent_panel.refresh()
        human_panel.refresh()

    def run_opponent() -> None:
        runner.run_opponent()
        refresh()

    def after_human_action() -> None:
        pending = runner.pending
        if pending is not None:
            field.begin_selection(pending.candidates)  # its candidates become selectable
        refresh()
        if pending is None and runner.is_opponent_turn:
            # The board already shows "Opponent's turn"; run it after a beat so the hand-off shows.
            root.after(OPPONENT_TURN_DELAY_MS, run_opponent)

    def confirm_decision() -> None:
        runner.submit(field.selection)
        field.end_selection()
        after_human_action()

    def on_action(action: Action) -> None:
        runner.act(action)
        after_human_action()

    def on_card_activated(card_id: str) -> None:
        # A board click invokes whatever action that card offers — produce gold (a battlefield
        # producer) or recruit (a face-up province card).
        action = next(
            (
                a
                for a in runner.legal_actions()
                if isinstance(a, ProduceGold | Recruit) and a.card_id == card_id
            ),
            None,
        )
        if action is not None:
            on_action(action)

    # Re-render (board borders + confirm-button state) as the player toggles candidates.
    field.on_selection_changed = refresh
    field.on_card_activated = on_card_activated

    phase_bar = PhaseBar(content)
    phase_bar.pack(side="bottom", fill="x")
    field.pack(side="top", fill="both", expand=True)
    field.configure_hotkeys(hotkeys)

    # The left column runs opponent / prompt / you, top to bottom.
    opponent_panel = PlayerPanel(sidebar, field, PlayerId.P2)
    human_panel = PlayerPanel(sidebar, field, PlayerId.P1)
    prompt_box = PromptBox(sidebar)
    prompt_box.grid(row=1, column=0, sticky="nsew")

    def relayout_panels() -> None:
        """Place the seat being played at the bottom of the column and refresh both panels. Driven
        by the debug seat toggle; with no toggle the human stays at the bottom all game."""
        opponent_panel.grid_forget()
        human_panel.grid_forget()
        top, bottom = (
            (opponent_panel, human_panel)
            if field.seat is PlayerId.P1
            else (human_panel, opponent_panel)
        )
        top.grid(row=0, column=0, sticky="new")
        bottom.grid(row=2, column=0, sticky="sew")
        opponent_panel.refresh()
        human_panel.refresh()

    field.on_local_player_changed = relayout_panels
    relayout_panels()
    refresh()  # render the opening projection and phase bar

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
