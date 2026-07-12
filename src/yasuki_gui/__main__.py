import logging
import tkinter as tk

from yasuki_core.engine.players import PlayerId
from yasuki_core.engine.table import DeckKey
from yasuki_core.engine.rules.actions import Action, Pass
from yasuki_core.engine.rules.decisions import (
    BanishForLegacy,
    ChooseAbilityTarget,
    ChooseCards,
    ChooseInvestAmount,
    ChooseLegacyCard,
    ChoosePayment,
    DecisionRequest,
    DecisionResponse,
    DiscardToHandSize,
    PlaceLegacy,
)
from collections.abc import Iterable
from yasuki_core.engine.session import EngineSession
from yasuki_gui import theme
from yasuki_gui.config import DEBUG_MODE as GUI_DEBUG_MODE, load_hotkeys
from yasuki_gui.field_view import FieldView
from yasuki_gui.rules_runner import GameRunner
from yasuki_gui.session import DEMO_DECK_PATH, build_demo_state, build_state_from_deck
from yasuki_gui.ui.dialogs import Dialogs
from yasuki_gui.ui.images import ImageProvider
from yasuki_gui.ui.info_box import PlayerInfoBox
from yasuki_gui.ui.menus import build_menubar
from yasuki_gui.ui.phase_bar import PhaseBar
from yasuki_gui.ui.prompt_box import PromptBox

logger = logging.getLogger(__name__)

LOCAL_DEBUG_OVERRIDE = False

# How long the board lingers on "Opponent's turn" before the opponent's (AI-less) turn auto-runs.
OPPONENT_TURN_DELAY_MS = 700


def _describe_decision(
    request: DecisionRequest, chosen: Iterable[str], boosted: Iterable[str] = ()
) -> tuple[str, str]:
    """A pending decision's prompt text and confirm-button label, given the cards chosen so far (and,
    paying, the producers boosted). Raise on an unmapped decision so a new request type can't ship
    without its prompt."""
    if isinstance(request, DiscardToHandSize):
        return f"discard {request.count} card(s)", "Discard"
    if isinstance(request, ChoosePayment):
        yields = dict(request.produced)
        boost = dict(request.boostable)
        boosted_set = set(boosted)
        covered = request.available + sum(
            yields[card_id] + (boost[card_id] if card_id in boosted_set else 0)
            for card_id in chosen
        )
        remaining = max(0, request.amount - covered)
        return f"Pay {remaining} gold for {request.label}", "Pay"
    if isinstance(request, BanishForLegacy):
        return "Banish a card from hand to search for a Legacy card", "Banish"
    if isinstance(request, PlaceLegacy):
        return "Choose a province to place the Legacy card, discarding the card there", "Place"
    if isinstance(request, ChooseAbilityTarget):
        return "Choose a target for the ability", "Confirm"
    if isinstance(request, ChooseCards):
        if request.minimum == 0:
            return f"Choose up to {request.maximum} card(s)", "Confirm"
        return f"Choose {request.minimum} to {request.maximum} card(s)", "Confirm"
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
        elif isinstance(pending, ChooseLegacyCard):
            # Answered by the search dialog (opened in after_human_action), not the board.
            prompt_box.show("Search your deck for a Legacy card", [])
        elif isinstance(pending, ChooseInvestAmount):
            # An amount, not a board card — answered by one button per affordable amount.
            buttons = [
                (f"Invest {amount}", lambda a=amount: submit_invest(a), True)
                for amount in pending.candidates
            ]
            buttons.append(("Cancel", cancel_decision, True))
            prompt_box.show("Choose how much to Invest", buttons)
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
            chosen = tuple(field.selection)
            boosted = tuple(field.boosted)
            prompt, button_label = _describe_decision(pending, chosen, boosted)
            can_confirm = pending.accepts(DecisionResponse(chosen, boosted))
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

    def open_legacy_search(pending: ChooseLegacyCard) -> None:
        # The search runs over the deck (and face-down provinces), off the board, so a modal search
        # dialog presents the whole pool; only the Legacy cards in it are choosable.
        pool = runner.legacy_search_pool()
        choosable = set(pending.candidates)

        def on_pick(card_id: str) -> None:
            runner.submit([card_id])
            after_human_action()

        Dialogs(root, ImageProvider(root)).card_search(pool, choosable, "Dynasty deck", on_pick)

    def after_human_action() -> None:
        nonlocal boost_producer
        boost_producer = None
        pending = runner.pending
        if isinstance(pending, ChooseLegacyCard):
            open_legacy_search(pending)
            refresh()
            return
        if pending is not None and not isinstance(pending, ChooseInvestAmount):
            # A payment's candidate producers become selectable and preview as bowed when picked; an
            # Invest amount is answered by prompt buttons, so it takes no board selection.
            paying = isinstance(pending, ChoosePayment)
            boostable = [pid for pid, _ in pending.boostable] if paying else ()
            field.begin_selection(pending.candidates, render_bowed=paying, boostable=boostable)
        refresh()
        if pending is None and runner.is_opponent_turn:
            # The board already shows "Opponent's turn"; run it after a beat so the hand-off shows.
            root.after(OPPONENT_TURN_DELAY_MS, run_opponent)

    def confirm_decision() -> None:
        runner.submit(field.selection, field.boosted)
        field.end_selection()
        after_human_action()

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
        after_human_action()

    def cancel_decision() -> None:
        # Back out of a pending payment: drop the announced Recruit and clear the gold selection.
        runner.cancel()
        field.end_selection()
        after_human_action()

    def on_action(action: Action) -> None:
        runner.act(action)
        after_human_action()

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
        # Discard, or an in-play card's activated ability. The ensuing target/payment is picked
        # through the board-selection path.
        popup_action_menu(runner.province_menu(card_id) + runner.ability_menu(card_id))

    def on_deck_activated(deck_key: DeckKey) -> None:
        # A left-click on the human's dynasty deck opens the Legacy rulebook ability, which searches
        # that deck.
        popup_action_menu(runner.deck_menu(deck_key))

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
    root.bind("<Control-z>", undo)
    root.bind("<Escape>", cancel_via_escape)

    phase_bar = PhaseBar(content)
    phase_bar.pack(side="bottom", fill="x")
    field.pack(side="top", fill="both", expand=True)
    field.configure_hotkeys(hotkeys)

    # The left column runs opponent / prompt / you, top to bottom.
    opponent_panel = PlayerInfoBox(sidebar, field, PlayerId.P2)
    human_panel = PlayerInfoBox(sidebar, field, PlayerId.P1, on_deck_activated=on_deck_activated)
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

    def load_deck_from_path(path: str) -> None:
        """Start a fresh game with the human on the picked deck; the opponent keeps the default.
        Raise on a deck that fails to load so the menu can report it."""
        nonlocal session, runner, human_seat
        state, human_seat = build_state_from_deck(path, opponent_deck_path=DEMO_DECK_PATH)
        session = EngineSession.start(state, human_seat)
        runner = GameRunner(session, human_seat)
        field.state = session.game.table
        field.seat = human_seat
        field.end_selection()
        relayout_panels()
        refresh()

    field.load_deck_from_file = load_deck_from_path

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
