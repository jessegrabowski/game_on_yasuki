import logging
import tkinter as tk

from yasuki_core.engine.players import PlayerId
from yasuki_core.engine.rules.actions import Action, Pass, Recruit
from yasuki_core.engine.rules.decisions import (
    ChoosePayment,
    DecisionRequest,
    DecisionResponse,
    DiscardToHandSize,
)
from collections.abc import Iterable
from yasuki_core.engine.session import EngineSession
from yasuki_gui import theme
from yasuki_gui.config import DEBUG_MODE as GUI_DEBUG_MODE, load_hotkeys
from yasuki_gui.field_view import FieldView
from yasuki_gui.rules_runner import GameRunner
from yasuki_gui.session import build_demo_state, build_state_from_deck
from yasuki_gui.ui.info_box import PlayerInfoBox
from yasuki_gui.ui.menus import build_menubar
from yasuki_gui.ui.phase_bar import PhaseBar
from yasuki_gui.ui.prompt_box import PromptBox

logger = logging.getLogger(__name__)

LOCAL_DEBUG_OVERRIDE = False

# How long the board lingers on "Opponent's turn" before the opponent's (AI-less) turn auto-runs.
OPPONENT_TURN_DELAY_MS = 700


def _describe_decision(request: DecisionRequest, chosen: Iterable[str]) -> tuple[str, str]:
    """A pending decision's prompt text and confirm-button label, given the cards chosen so far.
    Raise on an unmapped decision so a new request type can't ship without its prompt."""
    if isinstance(request, DiscardToHandSize):
        return f"discard {request.count} card(s)", "Discard"
    if isinstance(request, ChoosePayment):
        yields = dict(request.produced)
        covered = request.available + sum(yields[card_id] for card_id in chosen)
        remaining = max(0, request.amount - covered)
        return f"Pay {remaining} gold for {request.label}", "Pay"
    raise ValueError(f"no prompt defined for {type(request).__name__}")


def _action_button_label(action: Action) -> str:
    """The prompt-box button label for a non-card action. Raise on an unmapped one."""
    if isinstance(action, Pass):
        return "Pass"
    raise ValueError(f"no button label for {type(action).__name__}")


def main() -> None:
    debug_enabled = GUI_DEBUG_MODE or LOCAL_DEBUG_OVERRIDE

    root = tk.Tk()
    root.title("Game on, Yasuki!" if not debug_enabled else "!! DEBUG DEBUG DEBUG !!")

    hotkeys = load_hotkeys()
    screen_w, screen_h = root.winfo_screenwidth(), root.winfo_screenheight()
    root.geometry(f"{screen_w}x{screen_h}+0+0")

    container = tk.Frame(root)
    container.pack(fill="both", expand=True)
    sidebar_w = 260
    sidebar = tk.Frame(container, width=sidebar_w, bg=theme.PANEL)
    sidebar.pack(side="left", fill="y")
    sidebar.grid_propagate(False)  # hold the fixed width; the prompt row takes the slack height
    sidebar.grid_columnconfigure(0, weight=1)
    sidebar.grid_rowconfigure(0, weight=0)  # opponent info box (sized to content)
    sidebar.grid_rowconfigure(1, weight=1)  # prompt box (fills the middle)
    sidebar.grid_rowconfigure(2, weight=0)  # your info box (sized to content)
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
        field.gold = view.gold[view.viewer]
        field.render_snapshot(view.table, human_seat)
        phase_bar.refresh(view)
        pending = runner.pending
        if pending is not None:
            chosen = tuple(field.selection)
            prompt, button_label = _describe_decision(pending, chosen)
            can_confirm = pending.accepts(DecisionResponse(chosen))
            buttons = [(button_label, confirm_decision, can_confirm)]
            if pending.cancellable:
                buttons.append(("Cancel", cancel_decision, True))
            prompt_box.show(prompt, buttons)
        else:
            whose = "Your turn" if view.active is view.viewer else "Opponent's turn"
            # Pass is a button; a Recruit is invoked by clicking a holding on the board.
            buttons = [
                (_action_button_label(action), lambda chosen=action: on_action(chosen), True)
                for action in runner.legal_actions()
                if isinstance(action, Pass)
            ]
            prompt_box.show(whose, buttons)
        opponent_panel.refresh()
        human_panel.refresh()

    def run_opponent() -> None:
        runner.run_opponent()
        refresh()

    def after_human_action() -> None:
        pending = runner.pending
        if pending is not None:
            # A payment's candidate producers become selectable and preview as bowed when picked.
            paying = isinstance(pending, ChoosePayment)
            field.begin_selection(pending.candidates, render_bowed=paying)
        refresh()
        if pending is None and runner.is_opponent_turn:
            # The board already shows "Opponent's turn"; run it after a beat so the hand-off shows.
            root.after(OPPONENT_TURN_DELAY_MS, run_opponent)

    def confirm_decision() -> None:
        runner.submit(field.selection)
        field.end_selection()
        after_human_action()

    def cancel_decision() -> None:
        # Back out of a pending payment: drop the announced Recruit and clear the gold selection.
        runner.cancel()
        field.end_selection()
        after_human_action()

    def on_action(action: Action) -> None:
        runner.act(action)
        after_human_action()

    def on_card_activated(card_id: str) -> None:
        # A click on a face-up province holding recruits it; producers are clicked during the
        # ensuing payment, which the selection path handles, not this one.
        action = next(
            (a for a in runner.legal_actions() if isinstance(a, Recruit) and a.card_id == card_id),
            None,
        )
        if action is not None:
            on_action(action)

    def undo_payment(_event=None) -> None:
        # Ctrl+Z while paying unbows the last producer tapped for gold; no effect otherwise.
        if isinstance(runner.pending, ChoosePayment):
            field.undo_last_selection()

    # Re-render (board borders + confirm-button state) as the player toggles candidates.
    field.on_selection_changed = refresh
    field.on_card_activated = on_card_activated
    root.bind("<Control-z>", undo_payment)

    phase_bar = PhaseBar(content)
    phase_bar.pack(side="bottom", fill="x")
    field.pack(side="top", fill="both", expand=True)
    field.configure_hotkeys(hotkeys)

    # The left column runs opponent / prompt / you, top to bottom.
    opponent_panel = PlayerInfoBox(sidebar, field, PlayerId.P2)
    human_panel = PlayerInfoBox(sidebar, field, PlayerId.P1)
    prompt_box = PromptBox(sidebar)
    prompt_box.grid(row=1, column=0, sticky="nsew")
    # Spacebar takes the primary offered action (Pass/Pay/Discard), never a secondary like Cancel.
    field.bind("<space>", lambda e: prompt_box.invoke_primary())

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
