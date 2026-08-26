from yasuki_core.engine.rules.actions import Action, DeclareAttack, Pass
from yasuki_core.engine.rules.decisions import (
    AssignUnits,
    ChooseBattlefield,
    ChooseDistribution,
    ChooseInvestAmount,
    ChoosePayment,
    Confirm,
    DecisionResponse,
    assignment,
    assignment_token,
)
from yasuki_core.engine.rules.projection import GameView
from yasuki_core.engine.runner import SearchView
from yasuki_gui.services.game_host import GameHost
from yasuki_gui.ui.dialogs import Dialogs
from yasuki_gui.ui.battle_window import BattleWindow
from yasuki_gui.ui.game_window import GameWindow
from yasuki_gui.ui.images import ImageProvider
from yasuki_gui.ui.prompt_box import ButtonSpec

# How long the board lingers on "Opponent's turn" before the opponent's turn auto-runs.
OPPONENT_TURN_DELAY_MS = 700


# The prompt-box label for each action a seat takes from a button rather than by clicking a card.
# An action absent here is not offered: a Recruit is invoked from the board, and an action with no
# wording has no way to describe itself to the player.
_ACTION_LABELS: dict[type, str] = {
    Pass: "Pass",
    DeclareAttack: "Declare an attack",
}


def _button_actions(actions: list[Action]) -> list[Action]:
    """The actions the prompt box offers, in the order it lists them."""
    return [action for action in actions if type(action) in _ACTION_LABELS]


class Presenter:
    """Turns what the engine wants next into what the player sees, and the player's answers back
    into engine calls.

    What the board is waiting on lives on the board and what the game is waiting on lives in the
    session, so there is no third copy of either here. The one thing it does keep is which army is
    part-way through being assigned: that spans two clicks and belongs to neither.
    """

    def __init__(self, host: GameHost, window: GameWindow) -> None:
        self.host = host
        self.window = window
        # Which army is waiting on a Province, or None. The one piece of state the presenter
        # keeps: it spans two clicks and belongs to neither the board nor the engine.
        self._assigning: int | None = None
        # Open only while an attack is, and closed with it. Display only — nothing is answered
        # here, so losing it costs the player nothing.
        self._battle_window: BattleWindow | None = None

    def present(self) -> None:
        """Set the client up for whatever the engine wants next: the dialog or selection mode the
        human's decision is answered through, or a hand-back to the opponent when the move is not
        the human's. Every path that advances the game ends here, since either seat's input can
        leave a decision owed by either seat."""
        runner, field = self.host.runner, self.window.field
        self._spend_committed()
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
        elif isinstance(pending, AssignUnits):
            if self._assigning is None:
                field.begin_selection(
                    {assignment(token)[0] for token in pending.candidates}
                    - set(field.assigned_units())
                )
        elif pending is not None and not isinstance(
            pending, ChooseInvestAmount | Confirm | ChooseBattlefield
        ):
            # A payment's candidate producers become selectable and preview as bowed when picked. An
            # Invest amount and a yes/no question are answered by prompt buttons, so neither puts
            # the board into selection mode.
            field.begin_selection(
                pending.candidates, render_bowed=isinstance(pending, ChoosePayment)
            )
        else:
            field.end_selection()
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

    def _show_battle(self, view: GameView) -> None:
        """Open the battle window while an attack is in progress, and close it when one ends."""
        if view.attack is None:
            if self._battle_window is not None:
                self._battle_window.destroy()
                self._battle_window = None
            return
        if self._battle_window is None:
            self._battle_window = BattleWindow(self.window.root)
        self._battle_window.refresh(view.attack, self._pending_armies())

    def _pending_armies(self) -> dict[int, tuple[str, ...]]:
        """The units the player has sent to each battlefield but not yet assigned, by battlefield.

        Board state rather than engine state: an army is sent from the card menu and the engine is
        told once, so until then this is the only place the intention exists.
        """
        field = self.window.field
        waiting: dict[int, list[str]] = {}
        for card_id, battlefield in field.assigned_units().items():
            card = field.state.cards_by_id.get(card_id) if field.state is not None else None
            waiting.setdefault(battlefield, []).append(card.name if card is not None else card_id)
        return {index: tuple(names) for index, names in waiting.items()}

    def refresh(self) -> None:
        """Redraw the board and rewrite the prompt from the current state, without advancing it."""
        window = self.window
        view = self.host.runner.view()
        window.field.gold = view.gold[view.viewer]
        window.field.render_snapshot(view.table, self.host.human_seat)
        window.phase_bar.refresh(view)
        status, buttons = self._prompt(view)
        window.prompt_box.show(status, buttons)
        self._show_battle(view)
        window.opponent_panel.refresh()
        window.human_panel.refresh()

    def _prompt(self, view: GameView) -> tuple[str, list[ButtonSpec]]:
        """What the prompt box should say, and the buttons it should offer, for whatever the engine
        is waiting on."""
        runner = self.host.runner
        pending = runner.pending
        if runner.loser is not None:
            lost = runner.loser is self.host.human_seat
            return ("You lose (failed Legacy)" if lost else "Opponent loses (failed Legacy)"), []
        if pending is not None and runner.search_view() is not None:
            # Answered by the search dialog (opened in present), not the board.
            return pending.prompt(), []
        if isinstance(pending, Confirm):
            # A question, not a selection: the subjects are already settled, so the seat answers it
            # rather than picking them off the board. No is greyed when the question refuses it,
            # which leaves cancelling as the way out of an option the seat is committed to.
            buttons: list[ButtonSpec] = [
                ("Yes", lambda asked=pending: self.submit_answer(asked.candidates), True),
                ("No", lambda: self.submit_answer(()), pending.accepts(DecisionResponse())),
            ]
            if pending.cancellable:
                buttons.append(("Cancel", self.cancel, True))
            return pending.prompt(), buttons
        if isinstance(pending, ChooseBattlefield):
            # A battlefield is a place rather than a card, so it is picked from a button.
            return pending.prompt(), [
                (f"Battlefield {int(index) + 1}", lambda i=index: self.submit_answer((i,)), True)
                for index in pending.candidates
            ]
        if isinstance(pending, AssignUnits):
            # Assigning is a process, and the board carries it: units are gathered into an army
            # from the card menu, the army is sent to a Province, and the whole map goes over as
            # the one answer the CR's simultaneous assignment calls for.
            field = self.window.field
            if self._assigning is not None:
                return "Click one of the Defender's Provinces, then Attack here", [
                    ("Attack here", self.send_army, bool(field.selection)),
                    ("Cancel", self.cancel_army_assignment, True),
                ]
            return self._assignment_prompt(), [("Done assigning", self.submit_assignment, True)]
        if isinstance(pending, ChooseInvestAmount):
            # An amount, not a board card — answered by one button per affordable amount.
            amounts: list[ButtonSpec] = [
                (f"Invest {amount}", lambda a=amount: self.submit_invest(a), True)
                for amount in pending.candidates
            ]
            return pending.prompt(), [*amounts, ("Cancel", self.cancel, True)]
        if pending is not None:
            answer = self._board_answer()
            # A payment is picked whole and answered one producer at a time, so what makes it
            # finishable is whether the picks cover the cost — not whether this is one legal answer.
            ready = (
                pending.covers_cost(answer)
                if isinstance(pending, ChoosePayment)
                else pending.accepts(answer)
            )
            board_buttons: list[ButtonSpec] = [(pending.confirm_label, self.confirm, ready)]
            if pending.cancellable:
                board_buttons.append(("Cancel", self.cancel, True))
            return pending.prompt(answer), board_buttons
        if view.responding_to is not None:
            # A Response Step: say what is being answered, or the Pass button asks the seat to
            # decline something it was never told the name of.
            whose = f"Responses to {view.responding_to}"
        else:
            whose = "Your turn" if view.active is view.viewer else "Opponent's turn"
        # Pass and Declare are buttons; a Recruit is invoked by clicking a holding on the board.
        return whose, [
            (_ACTION_LABELS[type(action)], lambda chosen=action: self.act(chosen), True)
            for action in _button_actions(runner.legal_actions())
        ]

    def act(self, action: Action) -> None:
        """Take ``action`` on the human's behalf."""
        self.host.runner.act(action)
        self.present()

    def confirm(self) -> None:
        """Answer the pending decision with the board's current selection.

        A payment is queued rather than sent: the seat picks every producer it means to bow in one
        go, and :meth:`_spend_committed` feeds them to the engine one answer at a time. A payment the
        pool already covers offers no producers, so there is nothing to queue and it is answered
        here, with the empty answer that bows nothing.
        """
        pending = self.host.runner.pending
        if isinstance(pending, ChoosePayment):
            self.window.field.commit_selection()
            # Guarded rather than unconditional: a payment that still owes gold and has no producer
            # picked stays open for the seat to pick one.
            if not self.window.field.committed and pending.accepts(DecisionResponse()):
                self.host.runner.submit(DecisionResponse())
            self.present()
            return
        self.host.runner.submit(self._board_answer())
        self.window.field.end_selection()
        self.present()

    def _spend_committed(self) -> None:
        """Bow the producers the seat has queued, one answer each, until the payment stops asking.

        It stops early whenever a producer's own window interrupts, so the seat answers that and the
        rest of the queue is spent on the way back through. Anything still queued once the payment
        is over is dropped — only a question can pause a payment, so anything else pending means the
        payment this queue belonged to has finished.
        """
        runner, field = self.host.runner, self.window.field
        while field.committed and isinstance(runner.pending, ChoosePayment):
            producer = field.take_committed()
            # A queued producer can stop being on offer: another's price destroyed it, or the cost
            # was already covered and this is a different payment's request.
            if producer in runner.pending.candidates:
                runner.submit(DecisionResponse((producer,)))
        if not isinstance(runner.pending, Confirm):
            field.drop_committed()

    def cancel(self) -> None:
        """Back out of a pending payment: drop the announced Recruit and clear the gold selection."""
        self.host.runner.cancel()
        self.window.field.drop_committed()
        self.window.field.end_selection()
        self.present()

    def _army_menu(self, card_id: str) -> list[ButtonSpec]:
        """What ``card_id`` can do about armies right now, each entry saying whether it is available.

        Every entry is shown whatever its state, so the four steps of assigning read as a sequence
        the player can see the shape of before any of it is reachable.
        """
        field = self.window.field
        army = field.army_of(card_id)
        sent = army is not None and field.battlefield_of_army(army) is not None
        return [
            ("Add to army", lambda: self.form_army(card_id), bool(field.selection) and not sent),
            ("Remove from army", lambda: self.leave_army(card_id), army is not None and not sent),
            (
                "Assign army",
                lambda: self.assign_army(card_id),
                army is not None and not sent,
            ),
            ("Unassign army", lambda: self.recall_army(card_id), sent),
        ]

    def form_army(self, card_id: str) -> None:
        """Bring the board's selection into ``card_id``'s army, forming one if it has none."""
        field = self.window.field
        army = field.army_of(card_id)
        if army is None:
            # A list, and the clicked card last: a set would order the army by string hash, which
            # varies between runs and would show the same picks in a different order each time.
            picked = list(field.selection)
            field.form_army(picked + ([card_id] if card_id not in picked else []))
        else:
            field.join_army(army, field.selection)
        self.present()

    def leave_army(self, card_id: str) -> None:
        """Take ``card_id`` out of its army."""
        self.window.field.leave_army(card_id)
        self.present()

    def recall_army(self, card_id: str) -> None:
        """Bring ``card_id``'s army home, leaving it grouped."""
        field = self.window.field
        army = field.army_of(card_id)
        if army is not None:
            field.recall_army(army)
        self.present()

    def assign_army(self, card_id: str) -> None:
        """Ask which Province ``card_id``'s army attacks, by making the Provinces clickable."""
        army = self.window.field.army_of(card_id)
        if army is None:
            return
        self._assigning = army
        self.window.field.begin_selection(self._battlefield_tokens())
        self.refresh()

    def send_army(self) -> None:
        """Send the army being assigned to the Province the board has selected."""
        field, army = self.window.field, self._assigning
        chosen = field.selection
        self._assigning = None
        field.end_selection()
        if army is not None and chosen:
            field.send_army(army, self._battlefield_tokens().index(chosen[0]))
        self.present()

    def cancel_army_assignment(self) -> None:
        """Back out of choosing a Province, leaving the army grouped and at home."""
        self._assigning = None
        self.window.field.end_selection()
        self.present()

    def _battlefield_tokens(self) -> tuple[str, ...]:
        """The Defender's Province slots, in battlefield order — what a battlefield is drawn as."""
        attack = self.host.session.game.attack
        return tuple(info.province.token for info in attack.battlefields)

    def _assignment_prompt(self) -> str:
        """The next thing to do, not a description of the state - this is the step the player has no
        other guide through."""
        field = self.window.field
        if field.selection:
            return f"{len(field.selection)} picked - right-click one to add them to an army"
        if not field.armies:
            return "Click the Personalities you want to attack with, then right-click one"
        if any(field.battlefield_of_army(i) is None for i in range(len(field.armies))):
            return "Right-click an army to assign it to a Province"
        return "Every army is assigned - press Done assigning to fight the battles"

    def submit_assignment(self) -> None:
        """Answer the assignment with every army that was sent somewhere. An army left at home is
        not assigned, and no armies at all keeps the whole force home, which the CR allows."""
        placed = self.window.field.assigned_units()
        self.window.field.disband_armies()
        self.submit_answer(
            tuple(assignment_token(card_id, index) for card_id, index in placed.items())
        )

    def submit_answer(self, choices: tuple[str, ...]) -> None:
        """Answer a yes/no question with the cards it settled on, or nothing for no."""
        self.host.runner.submit(DecisionResponse(choices))
        self.present()

    def submit_invest(self, amount: str) -> None:
        """Answer an Invest decision with the amount the seat picked."""
        self.host.runner.submit(DecisionResponse((amount,)))
        self.present()

    def _board_answer(self) -> DecisionResponse:
        """The board's selection, as the answer to whatever decision is open."""
        return DecisionResponse(self.window.field.selection)

    def run_opponent(self) -> None:
        """Let the AI take its move, then present whatever the engine wants next."""
        self.host.runner.run_opponent()
        self.present()

    def on_card_activated(self, card_id: str) -> None:
        """Offer what a left-clicked card can do: a face-up Province card's Recruit or Dynasty
        Discard, a hand card's Kharmic, an in-play card's ability, or the Inheritance flip. The
        target or payment that follows is picked through the board-selection path.

        While an assignment is open the card menu is the army menu instead — grouping units and
        sending them is the only thing a Personality does in the Maneuvers Segment.
        """
        runner = self.host.runner
        if isinstance(runner.pending, AssignUnits):
            self.window.popup_at_pointer(self._army_menu(card_id))
            return
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
        """Ctrl+Z: unbow the last producer tapped for gold while paying, else undo a just-made
        Dynasty Discard if nothing has happened since."""
        field = self.window.field
        if isinstance(self.host.runner.pending, ChoosePayment):
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
            self.host.runner.submit(DecisionResponse((card_id,)))
            self.present()

        root = self.window.root
        Dialogs(root, ImageProvider(root)).card_search(search.panes, search.choosable, on_pick)
