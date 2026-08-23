from yasuki_core.engine.rules.actions import Action, Pass
from yasuki_core.engine.rules.decisions import (
    ChooseDistribution,
    ChooseInvestAmount,
    ChoosePayment,
    Confirm,
    DecisionResponse,
)
from yasuki_core.engine.rules.projection import GameView
from yasuki_core.engine.runner import SearchView
from yasuki_gui.services.game_host import GameHost
from yasuki_gui.ui.dialogs import Dialogs
from yasuki_gui.ui.game_window import GameWindow
from yasuki_gui.ui.images import ImageProvider
from yasuki_gui.ui.prompt_box import ButtonSpec

# How long the board lingers on "Opponent's turn" before the opponent's turn auto-runs.
OPPONENT_TURN_DELAY_MS = 700


def _action_button_label(action: Action) -> str:
    """The prompt-box button label for a non-card action. Raise on an unmapped one."""
    if isinstance(action, Pass):
        return "Pass"
    raise ValueError(f"no button label for {type(action).__name__}")


class Presenter:
    """Turns what the engine wants next into what the player sees, and the player's answers back
    into engine calls.

    Holds no state of its own. What the board is waiting on lives on the board and what the game is
    waiting on lives in the session, so there is no third copy here to fall out of step with either.
    """

    def __init__(self, host: GameHost, window: GameWindow) -> None:
        self.host = host
        self.window = window

    def present(self) -> None:
        """Set the client up for whatever the engine wants next: the dialog or selection mode the
        human's decision is answered through, or a hand-back to the opponent when the move is not
        the human's. Every path that advances the game ends here, since either seat's input can
        leave a decision owed by either seat."""
        runner, field = self.host.runner, self.window.field
        # A presentation starts with no question of its own open, whatever the last one left.
        field.cancel_boost()
        pending = runner.pending
        search = runner.search_view()
        if search is not None:
            # The candidates are in a deck or a discard pile, so there is nothing on the board to
            # click; a modal dialog lists the pile instead.
            self._open_search(search)
            self.refresh()
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
        self.refresh()
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
            self.window.root.after(beat, self.run_opponent)

    def refresh(self) -> None:
        """Redraw the board and rewrite the prompt from the current state, without advancing it."""
        window = self.window
        view = self.host.runner.view()
        window.field.gold = view.gold[view.viewer]
        window.field.render_snapshot(view.table, self.host.human_seat)
        window.phase_bar.refresh(view)
        status, buttons = self._prompt(view)
        window.prompt_box.show(status, buttons)
        window.opponent_panel.refresh()
        window.human_panel.refresh()

    def _prompt(self, view: GameView) -> tuple[str, list[ButtonSpec]]:
        """What the prompt box should say, and the buttons it should offer, for whatever the engine
        is waiting on."""
        runner, field = self.host.runner, self.window.field
        pending = runner.pending
        if runner.loser is not None:
            lost = runner.loser is self.host.human_seat
            return ("You lose (failed Legacy)" if lost else "Opponent loses (failed Legacy)"), []
        if pending is not None and runner.search_view() is not None:
            # Answered by the search dialog (opened in present), not the board.
            return pending.prompt(), []
        if isinstance(pending, Confirm):
            # A question, not a selection: the subjects are already settled, so the seat answers it
            # rather than picking them off the board.
            return pending.prompt(), [
                ("Yes", lambda asked=pending: self.submit_answer(asked.candidates), True),
                ("No", lambda: self.submit_answer(()), True),
            ]
        if isinstance(pending, ChooseInvestAmount):
            # An amount, not a board card — answered by one button per affordable amount.
            amounts: list[ButtonSpec] = [
                (f"Invest {amount}", lambda a=amount: self.submit_invest(a), True)
                for amount in pending.candidates
            ]
            return pending.prompt(), [*amounts, ("Cancel", self.cancel, True)]
        if isinstance(pending, ChoosePayment) and field.pending_boost is not None:
            extra = dict(pending.boostable).get(field.pending_boost, 0)
            return f"Boost this Holding as it bows? +{extra} Gold, then it is destroyed.", [
                ("Boost", lambda: self.answer_boost(True), True),
                ("Skip", lambda: self.answer_boost(False), True),
            ]
        if pending is not None:
            chosen = field.selection
            boosted = tuple(field.boosted)
            can_confirm = pending.accepts(DecisionResponse(chosen, boosted))
            buttons: list[ButtonSpec] = [(pending.confirm_label, self.confirm, can_confirm)]
            if pending.cancellable:
                buttons.append(("Cancel", self.cancel, True))
            return pending.prompt(chosen, boosted), buttons
        if view.responding_to is not None:
            # A Response Step: say what is being answered, or the Pass button asks the seat to
            # decline something it was never told the name of.
            whose = f"Responses to {view.responding_to}"
        else:
            whose = "Your turn" if view.active is view.viewer else "Opponent's turn"
        # Pass is a button; a Recruit is invoked by clicking a holding on the board.
        return whose, [
            (_action_button_label(action), lambda chosen=action: self.act(chosen), True)
            for action in runner.legal_actions()
            if isinstance(action, Pass)
        ]

    def act(self, action: Action) -> None:
        """Take ``action`` on the human's behalf."""
        self.host.runner.act(action)
        self.present()

    def confirm(self) -> None:
        """Answer the pending decision with the board's current selection."""
        field = self.window.field
        self.host.runner.submit(field.selection, field.boosted)
        field.end_selection()
        self.present()

    def cancel(self) -> None:
        """Back out of a pending payment: drop the announced Recruit and clear the gold selection."""
        self.host.runner.cancel()
        self.window.field.end_selection()
        self.present()

    def submit_answer(self, choices: tuple[str, ...]) -> None:
        """Answer a yes/no question with the cards it settled on, or nothing for no."""
        self.host.runner.submit(list(choices))
        self.present()

    def submit_invest(self, amount: str) -> None:
        """Answer an Invest decision with the amount the seat picked."""
        self.host.runner.submit([amount])
        self.present()

    def request_boost(self, _producer_id: str) -> None:
        """Put the board's open boost question in the prompt box. The board records which producer
        it stopped on, so the id the hook passes is read from there rather than from here."""
        self.refresh()

    def answer_boost(self, take: bool) -> None:
        """Take or skip the boost on the producer the board is waiting on, which then enters the
        selection."""
        producer_id = self.window.field.pending_boost
        if producer_id is not None:
            # Adds it to the selection, then refreshes through on_selection_changed.
            self.window.field.resolve_boost(producer_id, take)

    def run_opponent(self) -> None:
        """Let the AI take its move, then present whatever the engine wants next."""
        self.host.runner.run_opponent()
        self.present()

    def on_card_activated(self, card_id: str) -> None:
        """Offer what a left-clicked card can do: a face-up Province card's Recruit or Dynasty
        Discard, a hand card's Kharmic, an in-play card's ability, or the Inheritance flip. The
        target or payment that follows is picked through the board-selection path."""
        runner = self.host.runner
        self._offer(
            runner.province_menu(card_id)
            + runner.hand_menu(card_id)
            + runner.ability_menu(card_id)
            + runner.inheritance_menu(card_id)
        )

    def on_board_menu(self) -> None:
        """Offer the rulebook abilities. They act on whole zones rather than on a card, so there is
        no card to left-click for them and a right-click on empty board asks instead."""
        self._offer(self.host.runner.board_menu())

    def undo(self, _event=None) -> None:
        """Ctrl+Z: back out of an open boost question, else unbow the last producer tapped for gold
        while paying, else undo a just-made Dynasty Discard if nothing has happened since."""
        field = self.window.field
        if field.pending_boost is not None:
            field.cancel_boost()
            self.refresh()
        elif isinstance(self.host.runner.pending, ChoosePayment):
            field.undo_last_selection()
        elif self.host.runner.undo_last():
            field.state = self.host.session.game.table
            field.end_selection()
            self.refresh()

    def cancel_via_escape(self, _event=None) -> None:
        """Escape backs out of a cancellable pending decision, and does nothing otherwise — which
        leaves the board's own Escape, clearing the selection, alone."""
        pending = self.host.runner.pending
        if pending is not None and pending.cancellable:
            self.cancel()

    def load_human_deck(self, path: str) -> None:
        """Deal the decklist at ``path`` to the human and show the game it starts."""
        self.host.load_human_deck(path)
        self.present_new_game()

    def load_opponent_deck(self, path: str) -> None:
        """Deal the decklist at ``path`` to the AI opponent and show the game it starts."""
        self.host.load_opponent_deck(path)
        self.present_new_game()

    def present_new_game(self) -> None:
        """Render the game the host has just dealt. Every deck load ends here."""
        field = self.window.field
        field.state = self.host.session.game.table
        field.seat = self.host.human_seat
        field.end_selection()
        self.window.relayout_panels()
        self.present()

    def _offer(self, items: list[tuple[str, Action]]) -> None:
        """Put a click's available actions in a pointer menu, each entry taking its own action."""
        self.window.popup_at_pointer(
            (label, lambda chosen=action: self.act(chosen)) for label, action in items
        )

    def _open_search(self, search: SearchView) -> None:
        """Open the modal pile-search dialog and submit whichever card is picked."""

        def on_pick(card_id: str) -> None:
            self.host.runner.submit([card_id])
            self.present()

        root = self.window.root
        Dialogs(root, ImageProvider(root)).card_search(search.panes, search.choosable, on_pick)
