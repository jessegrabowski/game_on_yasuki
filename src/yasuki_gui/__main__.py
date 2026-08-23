import logging
import tkinter as tk
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from numpy.random import Generator

from yasuki_core.engine.rules.actions import Action, Pass
from yasuki_core.engine.rules.decisions import (
    ChooseDistribution,
    ChooseInvestAmount,
    ChoosePayment,
    Confirm,
    DecisionResponse,
)
from yasuki_gui.config import load_hotkeys
from yasuki_gui.services.game_host import GameHost
from yasuki_core.engine.runner import SearchView
from yasuki_gui.session import DEMO_DECK_PATH
from yasuki_gui.ui.dialogs import Dialogs
from yasuki_gui.ui.game_window import GameWindow
from yasuki_gui.ui.images import ImageProvider

logger = logging.getLogger(__name__)

# How long the board lingers on "Opponent's turn" before the opponent's turn auto-runs.
OPPONENT_TURN_DELAY_MS = 700


def _action_button_label(action: Action) -> str:
    """The prompt-box button label for a non-card action. Raise on an unmapped one."""
    if isinstance(action, Pass):
        return "Pass"
    raise ValueError(f"no button label for {type(action).__name__}")


@dataclass(frozen=True, slots=True)
class Client:
    """A built desktop client, handed back so a caller can run it and a test can drive it.

    Scaffolding, and temporary: it exposes the state the entry point shares between its callbacks
    so a caller can reach it, and each field leaves as its real owner arrives.

    Attributes
    ----------
    window : GameWindow
        Every widget the client draws.
    host : GameHost
        The live game — the decks it was dealt from, the session, and the runner driving it. Held
        rather than the runner itself, which a deck load replaces.
    present : callable
        Sets the client up for whatever the engine wants next. Every path that advances the game
        ends here.
    act : callable
        Takes one :class:`Action` on the human's behalf.
    load_human_deck : callable
        Deals the decklist at the given path to the human and restarts the game.
    load_opponent_deck : callable
        Deals the decklist at the given path to the AI opponent and restarts the game.
    confirm : callable
        Answers the pending decision with the board's current selection.
    cancel : callable
        Backs out of the pending decision, when it allows it.
    """

    window: GameWindow
    host: GameHost
    present: Callable[[], None]
    act: Callable[[Action], None]
    load_human_deck: Callable[[str], None]
    load_opponent_deck: Callable[[str], None]
    confirm: Callable[[], None]
    cancel: Callable[[], None]

    def run(self) -> None:
        """Enter the event loop. The client is already built and has presented its opening state."""
        self.window.root.mainloop()


def build_client(
    *,
    human_deck: Path = DEMO_DECK_PATH,
    opponent_deck: Path = DEMO_DECK_PATH,
    rng: Generator | None = None,
) -> Client:
    """Build the client and hand it back unrun.

    Parameters
    ----------
    human_deck : pathlib.Path, optional
        The decklist dealt to the human. Default the bundled deck.
    opponent_deck : pathlib.Path, optional
        The decklist dealt to the AI opponent. Default the bundled deck, a mirror match.
    rng : numpy.random.Generator, optional
        Deals every game this client starts, including the ones a deck load restarts. Default None,
        which deals from system entropy — what a game wants, where a repeated opening is a defect.
    """
    # The human always sits at P1; who takes the first turn is decided by Family Honor at deal.
    host = GameHost(human_deck, opponent_deck, rng=rng)
    window = GameWindow(host.session.game.table, host.human_seat)

    # The producer awaiting a boost answer mid-payment, or None; its prompt pre-empts the payment.
    boost_producer: str | None = None

    def refresh() -> None:
        view = host.runner.view()
        window.field.gold = view.gold[view.viewer]
        window.field.render_snapshot(view.table, host.human_seat)
        window.phase_bar.refresh(view)
        pending = host.runner.pending
        if host.runner.loser is not None:
            lost = host.runner.loser is host.human_seat
            window.prompt_box.show(
                "You lose (failed Legacy)" if lost else "Opponent loses (failed Legacy)", []
            )
        elif pending is not None and host.runner.search_view() is not None:
            # Answered by the search dialog (opened in present_pending), not the board.
            window.prompt_box.show(pending.prompt(), [])
        elif isinstance(pending, Confirm):
            # A question, not a selection: the subjects are already settled, so the seat answers it
            # rather than picking them off the board.
            window.prompt_box.show(
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
            window.prompt_box.show(pending.prompt(), buttons)
        elif isinstance(pending, ChoosePayment) and boost_producer is not None:
            extra = dict(pending.boostable).get(boost_producer, 0)
            window.prompt_box.show(
                f"Boost this Holding as it bows? +{extra} Gold, then it is destroyed.",
                [
                    ("Boost", lambda: answer_boost(True), True),
                    ("Skip", lambda: answer_boost(False), True),
                ],
            )
        elif pending is not None:
            chosen = window.field.selection
            boosted = tuple(window.field.boosted)
            can_confirm = pending.accepts(DecisionResponse(chosen, boosted))
            buttons = [(pending.confirm_label, confirm_decision, can_confirm)]
            if pending.cancellable:
                buttons.append(("Cancel", cancel_decision, True))
            window.prompt_box.show(pending.prompt(chosen, boosted), buttons)
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
                for action in host.runner.legal_actions()
                if isinstance(action, Pass)
            ]
            window.prompt_box.show(whose, buttons)
        window.opponent_panel.refresh()
        window.human_panel.refresh()

    def run_opponent() -> None:
        host.runner.run_opponent()
        present_pending()

    def open_search(search: SearchView) -> None:
        def on_pick(card_id: str) -> None:
            host.runner.submit([card_id])
            present_pending()

        Dialogs(window.root, ImageProvider(window.root)).card_search(
            search.panes, search.choosable, on_pick
        )

    def present_pending() -> None:
        """Set the client up for whatever the engine wants next: the dialog or selection mode the
        human's decision is answered through, or a hand-back to the opponent when the move is not
        the human's. Every path that advances the game ends here, since either seat's input can
        leave a decision owed by either seat."""
        nonlocal boost_producer
        boost_producer = None
        pending = host.runner.pending
        search = host.runner.search_view()
        if search is not None:
            # The candidates are in a deck or a discard pile, so there is nothing on the board to
            # click; a modal dialog lists the pile instead.
            open_search(search)
            refresh()
            return
        if isinstance(pending, ChooseDistribution):
            # A division is answered by how many go where, not by which cards were picked, so each
            # chosen card carries a spinner rather than only a selection ring.
            window.field.begin_allocation(pending.candidates, pending.count)
        elif pending is not None and not isinstance(pending, ChooseInvestAmount | Confirm):
            # A payment's candidate producers become selectable and preview as bowed when picked. An
            # Invest amount and a yes/no question are answered by prompt buttons, so neither puts
            # the board into selection mode.
            paying = isinstance(pending, ChoosePayment)
            boostable = [pid for pid, _ in pending.boostable] if paying else ()
            window.field.begin_selection(
                pending.candidates, render_bowed=paying, boostable=boostable
            )
        refresh()
        # An owed decision counts as well as held priority: a card can put a question to the
        # opponent while the human keeps priority, and the engine is paused until it is answered.
        opponent_to_move = host.runner.opponent_holds_priority or host.runner.opponent_owes_decision
        if pending is None and host.runner.loser is None and opponent_to_move:
            # A finished game is excluded because the opponent can hold priority on one while
            # running it moves nothing, which would reschedule this forever.
            #
            # Pause only when the turn itself changes hands, so the board's "Opponent's turn" is
            # readable. The opponent also takes a window inside each of the human's Action phases,
            # and stalling on those would put the delay in the middle of the human's own turn.
            beat = OPPONENT_TURN_DELAY_MS if host.runner.is_opponent_turn else 0
            window.root.after(beat, run_opponent)

    def confirm_decision() -> None:
        host.runner.submit(window.field.selection, window.field.boosted)
        window.field.end_selection()
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
            window.field.resolve_boost(
                producer_id, take
            )  # adds it to the selection, then refreshes

    def submit_invest(amount: str) -> None:
        host.runner.submit([amount])
        present_pending()

    def submit_answer(choices: tuple[str, ...]) -> None:
        host.runner.submit(list(choices))
        present_pending()

    def cancel_decision() -> None:
        # Back out of a pending payment: drop the announced Recruit and clear the gold selection.
        host.runner.cancel()
        window.field.end_selection()
        present_pending()

    def on_action(action: Action) -> None:
        host.runner.act(action)
        present_pending()

    def popup_action_menu(items: list[tuple[str, Action]]) -> None:
        """Pop up a left-click action menu at the pointer; each entry performs its action. No-op
        when there is nothing to offer."""
        if not items:
            return
        menu = tk.Menu(window.root, tearoff=0)
        for label, action in items:
            menu.add_command(label=label, command=lambda chosen=action: on_action(chosen))
        try:
            menu.tk_popup(window.root.winfo_pointerx(), window.root.winfo_pointery())
        finally:
            menu.grab_release()

    def on_card_activated(card_id: str) -> None:
        # A left-click opens what the card offers: a face-up province card's Recruit / Dynasty
        # Discard, a hand card's Kharmic, or an in-play card's activated ability. The ensuing
        # target/payment is picked through the board-selection path.
        popup_action_menu(
            host.runner.province_menu(card_id)
            + host.runner.hand_menu(card_id)
            + host.runner.ability_menu(card_id)
            + host.runner.inheritance_menu(card_id)
        )

    def on_board_menu() -> None:
        # A right-click on empty board opens the rulebook abilities. They act on whole zones rather
        # than on a card, so there is no card to left-click for them.
        popup_action_menu(host.runner.board_menu())

    def undo(_event=None) -> None:
        # Ctrl+Z: back out of an open boost question first, else while paying unbow the last producer
        # tapped for gold, else undo a just-made Dynasty Discard, if nothing else has happened since.
        nonlocal boost_producer
        if boost_producer is not None:
            boost_producer = None
            refresh()
        elif isinstance(host.runner.pending, ChoosePayment):
            window.field.undo_last_selection()
        elif host.runner.undo_last():
            window.field.state = host.session.game.table
            window.field.end_selection()
            refresh()

    def cancel_via_escape(_event=None) -> None:
        # Escape backs out of a cancellable pending decision (a recruit payment); no effect
        # otherwise, leaving the board's own Escape (clear selection) untouched.
        pending = host.runner.pending
        if pending is not None and pending.cancellable:
            cancel_decision()

    # Re-render (board borders + confirm-button state) as the player toggles candidates.
    window.field.on_boost_request = request_boost
    window.field.on_selection_changed = refresh
    window.field.on_card_activated = on_card_activated
    window.field.on_board_menu = on_board_menu
    window.root.bind("<Control-z>", undo)
    window.root.bind("<Escape>", cancel_via_escape)
    window.field.configure_hotkeys(load_hotkeys())

    def show_new_game() -> None:
        """Render the game the host just dealt. Every deck load ends here."""
        window.field.state = host.session.game.table
        window.field.seat = host.human_seat
        window.field.end_selection()
        window.relayout_panels()
        present_pending()

    def load_human_deck(path: str) -> None:
        host.load_human_deck(path)
        show_new_game()

    def load_opponent_deck(path: str) -> None:
        host.load_opponent_deck(path)
        show_new_game()

    window.field.load_deck_from_file = load_human_deck
    window.field.load_opponent_deck_from_file = load_opponent_deck

    # Renders the opening board and hands over to the opponent, which is what moves a game
    # whose first turn is not the human's.
    present_pending()

    return Client(
        window=window,
        host=host,
        present=present_pending,
        act=on_action,
        load_human_deck=load_human_deck,
        load_opponent_deck=load_opponent_deck,
        confirm=confirm_decision,
        cancel=cancel_decision,
    )


def main() -> None:
    build_client().run()


if __name__ == "__main__":
    main()
