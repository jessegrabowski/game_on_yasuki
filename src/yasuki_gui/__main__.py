import logging
import tkinter as tk
from pathlib import Path

from yasuki_core.engine.players import PlayerId
from yasuki_core.engine.rules.actions import Action, Pass
from yasuki_core.engine.rules.decisions import (
    ChooseDistribution,
    ChooseInvestAmount,
    ChoosePayment,
    Confirm,
    DecisionResponse,
)
from yasuki_core.engine.rules.policies import GoldRushPolicy
from yasuki_core.engine.session import EngineSession
from yasuki_gui import theme
from yasuki_gui.config import DEBUG_MODE as GUI_DEBUG_MODE, load_hotkeys
from yasuki_gui.field_view import FieldView
from yasuki_core.engine.runner import Controls, GameRunner, SearchView
from yasuki_core.game_setup import build_state_from_deck
from yasuki_gui.session import DEMO_DECK_PATH, build_demo_state
from yasuki_gui.ui.dialogs import Dialogs
from yasuki_gui.ui.images import ImageProvider
from yasuki_gui.ui.info_box import PlayerInfoBox
from yasuki_gui.ui.menus import build_menubar
from yasuki_gui.ui.phase_bar import PhaseBar
from yasuki_gui.ui.prompt_box import PromptBox

logger = logging.getLogger(__name__)

LOCAL_DEBUG_OVERRIDE = False

# How long the board lingers on "Opponent's turn" before the opponent's turn auto-runs.
OPPONENT_TURN_DELAY_MS = 700


def _opponent_controls() -> Controls:
    """What drives the AI opponent. One :class:`GoldRushPolicy` fills both halves, so the gold it
    chooses to raise and the payments it agrees to come from the same strategy."""
    policy = GoldRushPolicy()
    return Controls(policy, policy)


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
    sidebar_w = 190
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

    # The human always sits at P1; who takes the first turn is decided by Family Honor at deal.
    human_seat = PlayerId.P1
    # Deal the bundled deck (needs the database); fall back to the DB-free placeholder deck so the
    # client still launches without a database or card images.
    try:
        state, first_player = build_state_from_deck(
            DEMO_DECK_PATH, p1_name="You", p2_name="Opponent"
        )
    except Exception as exc:
        logger.warning("Could not load the bundled deck, using the placeholder deck: %s", exc)
        state, first_player = build_demo_state()

    session = EngineSession.start(state, first_player)
    runner = GameRunner(session, human_seat, _opponent_controls())

    field = FieldView(content, width=canvas_w, height=canvas_h)
    # The table backs panel and dialog reads; the board itself renders from the redacted projection.
    field.state = session.game.table
    field.seat = human_seat

    # The producer awaiting a boost answer mid-payment, or None; its prompt pre-empts the payment.
    boost_producer: str | None = None

    def refresh() -> None:
        view = runner.view()
        field.gold = view.gold[view.viewer]
        field.render_snapshot(view.table, human_seat)
        phase_bar.refresh(view)
        pending = runner.pending
        if runner.loser is not None:
            lost = runner.loser is human_seat
            prompt_box.show(
                "You lose (failed Legacy)" if lost else "Opponent loses (failed Legacy)", []
            )
        elif pending is not None and runner.search_view() is not None:
            # Answered by the search dialog (opened in present_pending), not the board.
            prompt_box.show(pending.prompt(), [])
        elif isinstance(pending, Confirm):
            # A question, not a selection: the subjects are already settled, so the seat answers it
            # rather than picking them off the board.
            prompt_box.show(
                pending.prompt(),
                [
                    ("Yes", lambda asked=pending: submit_answer(asked.candidates), True),
                    ("No", lambda: submit_answer(()), True),
                ],
            )
        elif isinstance(pending, ChooseInvestAmount):
            # An amount, not a board card — answered by one button per affordable amount.
            buttons = [
                (f"Invest {amount}", lambda a=amount: submit_invest(a), True)
                for amount in pending.candidates
            ]
            buttons.append(("Cancel", cancel_decision, True))
            prompt_box.show(pending.prompt(), buttons)
        elif isinstance(pending, ChoosePayment) and boost_producer is not None:
            extra = dict(pending.boostable).get(boost_producer, 0)
            prompt_box.show(
                f"Boost this Holding as it bows? +{extra} Gold, then it is destroyed.",
                [
                    ("Boost", lambda: answer_boost(True), True),
                    ("Skip", lambda: answer_boost(False), True),
                ],
            )
        elif pending is not None:
            chosen = field.selection
            boosted = tuple(field.boosted)
            can_confirm = pending.accepts(DecisionResponse(chosen, boosted))
            buttons = [(pending.confirm_label, confirm_decision, can_confirm)]
            if pending.cancellable:
                buttons.append(("Cancel", cancel_decision, True))
            prompt_box.show(pending.prompt(chosen, boosted), buttons)
        else:
            if view.responding_to is not None:
                # A Response Step: say what is being answered, or the Pass button asks the seat to
                # decline something it was never told the name of.
                whose = f"Responses to {view.responding_to}"
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
        present_pending()

    def open_search(search: SearchView) -> None:
        def on_pick(card_id: str) -> None:
            runner.submit([card_id])
            present_pending()

        Dialogs(root, ImageProvider(root)).card_search(search.panes, search.choosable, on_pick)

    def present_pending() -> None:
        """Set the client up for whatever the engine wants next: the dialog or selection mode the
        human's decision is answered through, or a hand-back to the opponent when the move is not
        the human's. Every path that advances the game ends here, since either seat's input can
        leave a decision owed by either seat."""
        nonlocal boost_producer
        boost_producer = None
        pending = runner.pending
        search = runner.search_view()
        if search is not None:
            # The candidates are in a deck or a discard pile, so there is nothing on the board to
            # click; a modal dialog lists the pile instead.
            open_search(search)
            refresh()
            return
        if isinstance(pending, ChooseDistribution):
            # A division is answered by how many go where, not by which cards were picked, so each
            # chosen card carries a spinner rather than only a selection ring.
            field.begin_allocation(pending.candidates, pending.count)
        elif pending is not None and not isinstance(pending, ChooseInvestAmount | Confirm):
            # A payment's candidate producers become selectable and preview as bowed when picked. An
            # Invest amount and a yes/no question are answered by prompt buttons, so neither puts
            # the board into selection mode.
            paying = isinstance(pending, ChoosePayment)
            boostable = [pid for pid, _ in pending.boostable] if paying else ()
            field.begin_selection(pending.candidates, render_bowed=paying, boostable=boostable)
        refresh()
        # An owed decision counts as well as held priority: a card can put a question to the
        # opponent while the human keeps priority, and the engine is paused until it is answered.
        opponent_to_move = runner.opponent_holds_priority or runner.opponent_owes_decision
        if pending is None and runner.loser is None and opponent_to_move:
            # A finished game is excluded because the opponent can hold priority on one while
            # running it moves nothing, which would reschedule this forever.
            #
            # Pause only when the turn itself changes hands, so the board's "Opponent's turn" is
            # readable. The opponent also takes a window inside each of the human's Action phases,
            # and stalling on those would put the delay in the middle of the human's own turn.
            beat = OPPONENT_TURN_DELAY_MS if runner.is_opponent_turn else 0
            root.after(beat, run_opponent)

    def confirm_decision() -> None:
        runner.submit(field.selection, field.boosted)
        field.end_selection()
        present_pending()

    def request_boost(producer_id: str) -> None:
        # A boostable producer was picked to pay: put its boost question in the prompt box.
        nonlocal boost_producer
        boost_producer = producer_id
        refresh()

    def answer_boost(take: bool) -> None:
        nonlocal boost_producer
        producer_id = boost_producer
        boost_producer = None
        if producer_id is not None:
            field.resolve_boost(producer_id, take)  # adds it to the selection, then refreshes

    def submit_invest(amount: str) -> None:
        runner.submit([amount])
        present_pending()

    def submit_answer(choices: tuple[str, ...]) -> None:
        runner.submit(list(choices))
        present_pending()

    def cancel_decision() -> None:
        # Back out of a pending payment: drop the announced Recruit and clear the gold selection.
        runner.cancel()
        field.end_selection()
        present_pending()

    def on_action(action: Action) -> None:
        runner.act(action)
        present_pending()

    def popup_action_menu(items: list[tuple[str, Action]]) -> None:
        """Pop up a left-click action menu at the pointer; each entry performs its action. No-op
        when there is nothing to offer."""
        if not items:
            return
        menu = tk.Menu(root, tearoff=0)
        for label, action in items:
            menu.add_command(label=label, command=lambda chosen=action: on_action(chosen))
        try:
            menu.tk_popup(root.winfo_pointerx(), root.winfo_pointery())
        finally:
            menu.grab_release()

    def on_card_activated(card_id: str) -> None:
        # A left-click opens what the card offers: a face-up province card's Recruit / Dynasty
        # Discard, a hand card's Kharmic, or an in-play card's activated ability. The ensuing
        # target/payment is picked through the board-selection path.
        popup_action_menu(
            runner.province_menu(card_id) + runner.hand_menu(card_id) + runner.ability_menu(card_id)
        )

    def on_board_menu() -> None:
        # A right-click on empty board opens the rulebook abilities. They act on whole zones rather
        # than on a card, so there is no card to left-click for them.
        popup_action_menu(runner.board_menu())

    def undo(_event=None) -> None:
        # Ctrl+Z: back out of an open boost question first, else while paying unbow the last producer
        # tapped for gold, else undo a just-made Dynasty Discard, if nothing else has happened since.
        nonlocal boost_producer
        if boost_producer is not None:
            boost_producer = None
            refresh()
        elif isinstance(runner.pending, ChoosePayment):
            field.undo_last_selection()
        elif runner.undo_last():
            field.state = session.game.table
            field.end_selection()
            refresh()

    def cancel_via_escape(_event=None) -> None:
        # Escape backs out of a cancellable pending decision (a recruit payment); no effect
        # otherwise, leaving the board's own Escape (clear selection) untouched.
        pending = runner.pending
        if pending is not None and pending.cancellable:
            cancel_decision()

    # Re-render (board borders + confirm-button state) as the player toggles candidates.
    field.on_boost_request = request_boost
    field.on_selection_changed = refresh
    field.on_card_activated = on_card_activated
    field.on_board_menu = on_board_menu
    root.bind("<Control-z>", undo)
    root.bind("<Escape>", cancel_via_escape)

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

    decks: dict[str, Path] = {"human": DEMO_DECK_PATH, "opponent": DEMO_DECK_PATH}

    def restart_game() -> None:
        """Start a fresh game on the currently picked decks. Raise on a deck that fails to load so
        the menu can report it."""
        nonlocal session, runner
        state, first_player = build_state_from_deck(
            decks["human"],
            opponent_deck_path=decks["opponent"],
            p1_name="You",
            p2_name="Opponent",
        )
        session = EngineSession.start(state, first_player)
        runner = GameRunner(session, human_seat, _opponent_controls())
        field.state = session.game.table
        field.seat = human_seat
        field.end_selection()
        relayout_panels()
        refresh()

    def _load_into(slot: str, path: str) -> None:
        """Deal ``path`` to ``slot`` and restart. A deck that fails to load leaves the slot as it
        was, so a bad pick does not strand the next restart on it."""
        previous = decks[slot]
        decks[slot] = Path(path)
        try:
            restart_game()
        except Exception:
            decks[slot] = previous
            raise

    field.load_deck_from_file = lambda path: _load_into("human", path)
    field.load_opponent_deck_from_file = lambda path: _load_into("opponent", path)

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
