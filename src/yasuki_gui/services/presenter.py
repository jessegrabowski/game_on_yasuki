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
from yasuki_core.engine.rules.projection import GameView, unit_view
from yasuki_core.game_pieces.cards import L5RCard
from yasuki_core.engine.runner import SearchView
from yasuki_gui.services.game_host import GameHost
from yasuki_gui.ui.battle_view import LaneButton, PendingArmy
from yasuki_gui.ui.dialogs import Dialogs
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
    session, so there is no third copy of either here. The one thing it does keep is which units are
    part-way through being assigned: that spans two clicks and belongs to neither.
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
            # Units already sent stay pickable: the lane is where they are, and picking them there
            # is how they are brought home or sent somewhere else.
            field.begin_selection({assignment(token)[0] for token in pending.candidates})
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

    def _pending_armies(self, view: GameView) -> dict[int, PendingArmy]:
        """The units the player has sent to each battlefield but not yet assigned, by battlefield.

        Board state rather than engine state: units are sent from the card menu and the engine is
        told once, so until then this is the only place the intention exists — and the player has
        already decided, so the battle view draws them standing where they were sent.

        Parameters
        ----------
        view : GameView
            The projection the board is being drawn from, read for each unit's Force. The game is
            still read for the cards themselves, which the view indexes by id but does not hand
            back.
        """
        game = self.host.session.game
        waiting: dict[int, list[L5RCard]] = {}
        for card_id, battlefield in self.window.field.assigned_units().items():
            personality = game.table.cards_by_id.get(card_id)
            if personality is not None:
                waiting.setdefault(battlefield, []).append(personality)
        return {
            index: PendingArmy(
                units=tuple(unit_view(game, card) for card in cards),
                # The total resolution would reach, so the lane's Force does not jump when the
                # assignment is answered and the engine starts counting these itself.
                force=sum(view.unit_force.get(card.id, 0) for card in cards),
            )
            for index, cards in waiting.items()
        }

    def _lane_buttons(self) -> dict[int, LaneButton]:
        """What each battlefield offers the player right now.

        Both questions the Attack Phase asks are about a place, so both are answered under the lane
        that place is drawn in. Empty the rest of the time, which is what keeps a button off a lane
        whenever pressing it would not be a legal move.
        """
        pending = self.host.runner.pending
        if isinstance(pending, ChooseBattlefield):
            return {
                int(token): LaneButton(
                    "Fight here", lambda chosen=token: self.submit_answer((chosen,))
                )
                for token in pending.candidates
            }
        if isinstance(pending, AssignUnits):
            # Every battlefield offers the button for as long as the question is open, greyed until
            # units are picked, so where they could go is visible before any are.
            picked = bool(self.window.field.selection)
            return {
                index: LaneButton(
                    "Assign here", lambda at=index: self.assign_units(at), enabled=picked
                )
                for index in range(self._battlefield_count())
            }
        return {}

    def refresh(self) -> None:
        """Redraw the board and rewrite the prompt from the current state, without advancing it."""
        window = self.window
        view = self.host.runner.view()
        window.field.gold = view.gold[view.viewer]
        window.field.render_snapshot(view.table, self.host.human_seat, view.stats)
        window.phase_bar.refresh(view)
        status, buttons = self._prompt(view)
        window.prompt_box.show(status, buttons)
        if view.attack is None:
            window.show_battle(None)
        else:
            window.show_battle(
                view.attack,
                self._pending_armies(view),
                self._lane_buttons(),
                selected=frozenset(window.field.selection),
                stats=view.stats,
            )
        window.opponent_panel.refresh()
        window.human_panel.refresh()

    def _prompt(self, view: GameView) -> tuple[str, list[ButtonSpec]]:
        """What the prompt box should say, and the buttons it should offer, for whatever the engine
        is waiting on."""
        runner = self.host.runner
        pending = runner.pending
        if runner.loser is not None:
            whose = "You lose" if runner.loser is self.host.human_seat else "Opponent loses"
            return f"{whose} ({runner.loss_reason})", []
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
            # Answered by the button under the lane it picks, not from here — the choice is about
            # the battlefields, and they are what the player is looking at when it is asked.
            return pending.prompt(), []
        if isinstance(pending, AssignUnits):
            # Assigning is a process, and the board carries it: units are picked, sent to a
            # battlefield, and the whole map goes over as the one answer the CR's simultaneous
            # assignment calls for.
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

    def _assignment_menu(self) -> list[ButtonSpec]:
        """What the picked units can do right now, each entry saying whether it is available.

        It acts on the selection rather than on the card the menu was opened from, because picking
        is how a group is expressed.
        """
        field = self.window.field
        return [
            (
                "Unassign units",
                self.unassign_units,
                bool(field.selection) and field.selection_zone is not None,
            ),
        ]

    def assign_units(self, battlefield: int) -> None:
        """Send the picked units to ``battlefield``."""
        field = self.window.field
        field.remember_assignment()
        field.assign_units(field.selection, battlefield)
        self.present()

    def unassign_units(self) -> None:
        """Bring the picked units home from the battlefield they were sent to."""
        field = self.window.field
        field.remember_assignment()
        field.unassign_units(field.selection)
        self.present()

    def _battlefield_count(self) -> int:
        """How many battlefields the declared attack has."""
        attack = self.host.session.game.attack
        return len(attack.battlefields)

    def _assignment_prompt(self) -> str:
        """The next thing to do, not a description of the state - this is the step the player has no
        other guide through."""
        field = self.window.field
        if field.selection and field.selection_zone is None:
            picked = len(field.selection)
            return f"{picked} picked at home - press Assign here under the battlefield you want"
        if field.selection:
            picked = len(field.selection)
            return f"{picked} picked at the battlefield - right-click one to recall them"
        if not field.assigned_units():
            return (
                "Click the Personalities you want to attack with, then press a battlefield's button"
            )
        return "Click more Personalities to send, or press Done assigning to fight the battles"

    def submit_assignment(self) -> None:
        """Answer the assignment with every unit that was sent somewhere. Sending nothing keeps the
        whole force home, which the CR allows."""
        placed = self.window.field.assigned_units()
        self.window.field.forget_assignment()
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

        While an assignment is open the card menu is the assignment menu instead — sending units to
        a battlefield and bringing them back is the only thing a Personality does in the Maneuvers
        Segment.
        """
        runner = self.host.runner
        if isinstance(runner.pending, AssignUnits):
            # Right-clicking a card the player has not picked picks it, the way a file manager does:
            # the menu acts on the selection, and a menu that needed an invisible click first would
            # be greyed every time it was opened on the obvious card.
            leader = self.window.field.unit_leader(card_id)
            if leader not in self.window.field.selection:
                self.window.field.toggle_selection(leader)
                self.refresh()
            self.window.popup_at_pointer(self._assignment_menu())
            return
        self._offer(
            runner.province_menu(card_id)
            + runner.hand_menu(card_id)
            + runner.ability_menu(card_id)
            + runner.inheritance_menu(card_id)
        )

    def on_lane_card_clicked(self, card_id: str) -> None:
        """Pick or unpick a unit standing at a battlefield. The board and the lanes share one
        selection, so picking here drops anything picked at home."""
        field = self.window.field
        field.toggle_selection(field.unit_leader(card_id))
        self.refresh()

    def on_board_menu(self) -> None:
        """Offer the rulebook abilities. They act on whole zones rather than on a card, so there is
        no card to left-click for them and a right-click on empty board asks instead."""
        self._offer(self.host.runner.board_menu())

    def undo(self, _event=None) -> None:
        """Ctrl+Z: take back the last step of an assignment, unbow the last producer tapped for gold
        while paying, or undo a just-made Dynasty Discard if nothing has happened since.

        An assignment's steps come back one at a time.
        """
        field = self.window.field
        if isinstance(self.host.runner.pending, AssignUnits):
            if field.undo_assignment():
                self.present()
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
            self.host.runner.submit(DecisionResponse((card_id,)))
            self.present()

        root = self.window.root
        Dialogs(root, ImageProvider(root)).card_search(search.panes, search.choosable, on_pick)
