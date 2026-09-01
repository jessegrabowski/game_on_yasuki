import pytest

from yasuki_core.engine.players import PlayerId
from yasuki_core.engine.rules.actions import PlayStrategy, Recruit
from yasuki_core.engine.rules.decisions import ChooseAmount, ChooseInvestAmount, Confirm
from yasuki_core.engine.rules.modifiers import Duration, Modifier, Stat
from yasuki_core.engine.rules.payments import payment_request
from yasuki_core import ruleset
from yasuki_core.engine.rules.state import BattleSegment
from yasuki_core.engine.runner import GameRunner
from yasuki_core.engine.session import EngineSession
from yasuki_core.engine.table import DeckKey, TableState, ZoneKey, ZoneRole, location_of
from yasuki_core.engine.zones import ProvinceZone
from yasuki_core.game_pieces.cards import L5RCard
from yasuki_core.game_pieces.constants import Side
from yasuki_core.game_pieces.prints import ActionPrint, HoldingPrint
from yasuki_gui.layout import divider_y
from yasuki_gui.services.presenter import Presenter
from yasuki_gui.ui.floating_panel import MIN_H
from yasuki_gui.ui.geometry import widget_size
from yasuki_gui.ui.game_window import GameWindow

from yasuki_core.game_pieces.constants import AttachmentType

from tests.yasuki_core.engine.builders import (
    attached,
    attachment,
    dealt_table,
    end_phase,
    personality,
    holding,
    province_card,
    put_in_play,
    register,
)

P1 = PlayerId.P1


class FakeHost:
    """What the presenter reads off a :class:`~yasuki_gui.services.game_host.GameHost`. Real here
    would mean dealing a decklist out of Postgres, and these boards are built card by card rather
    than from whatever a deck happens to hold."""

    def __init__(self, runner: GameRunner):
        self.runner = runner
        self.human_seat = runner.human

    @property
    def session(self) -> EngineSession:
        return self.runner.session


def _grant_board() -> EngineSession:
    """A Dynasty phase where the one Holding on offer is affordable only through a producer's grant.

    Outlying Farms produces 2 and can raise itself to 4, so recruiting the cost-4 target means
    taking that grant — which is what puts the window question in front of the client.
    """
    state = TableState.empty_two_seat()
    state.decks[DeckKey(P1, Side.DYNASTY)].cards = [
        register(
            state, L5RCard.of(HoldingPrint, id="refill", name="R", side=Side.DYNASTY, owner=P1)
        )
    ]
    put_in_play(
        state,
        L5RCard.of(
            HoldingPrint,
            id="of",
            name="Outlying Farms",
            side=Side.DYNASTY,
            owner=P1,
            printed_id="outlying_farms",
            keywords=("Farm",),
            gold_production=2,
        ),
    )
    target = register(
        state,
        L5RCard.of(
            HoldingPrint,
            id="target",
            name="Target",
            side=Side.DYNASTY,
            owner=P1,
            printed_id="plain_holding",
            gold_cost=4,
            gold_production=2,
        ),
    )
    target.turn_face_up()
    province = ProvinceZone(owner=P1)
    province.add(target)
    state.zones[ZoneKey(P1, ZoneRole.PROVINCE, 0)] = province
    session = EngineSession.start(state, P1)
    end_phase(session)  # Action -> Battle
    end_phase(session)  # Battle -> Dynasty
    return session


@pytest.fixture
def paying():
    """A presenter over a game paused on a payment only a producer's own grant can cover, with the
    board already in selection mode — the state the client is in when the player is about to pick a
    producer."""
    session = _grant_board()
    runner = GameRunner(session, P1)
    window = GameWindow(session.game.table, P1)
    presenter = Presenter(FakeHost(runner), window)
    window.field.on_selection_changed = presenter.refresh
    try:
        runner.act(Recruit("target"))
        presenter.present()
        yield presenter, window
    finally:
        window.root.destroy()


@pytest.fixture
def board():
    """A presenter over a game with nothing pending, so a test can put the decision it wants in
    front of it. The runner tests build a request and assign it the same way."""
    session = _grant_board()
    runner = GameRunner(session, P1)
    window = GameWindow(session.game.table, P1)
    presenter = Presenter(FakeHost(runner), window)
    try:
        yield presenter, window, session
    finally:
        window.root.destroy()


def _set_spinner(window, amount: str) -> None:
    """Step the prompt's spinner to ``amount``, the way a click on its arrows would."""
    spinner = window.prompt_box._spinner
    spinner.configure(state="normal")
    spinner.delete(0, "end")
    spinner.insert(0, amount)
    spinner.configure(state="readonly")


def _status(window) -> str:
    return window.prompt_box._status.cget("text")


def _buttons(window) -> list[str]:
    return [button.cget("text") for button in window.prompt_box._buttons]


def _primary_enabled(window) -> bool:
    """Whether the affirmative button — the one the spacebar reaches — can be pressed."""
    return str(window.prompt_box._buttons[0].cget("state")) == "normal"


def test_the_payment_prompt_asks_which_producers_to_bow(paying):
    _, window = paying

    assert "Cancel" in _buttons(window)
    assert window.field.selecting


def test_bowing_a_producer_puts_its_window_question_in_the_prompt_box(paying):
    """The window arrives as an ordinary yes/no question, so the client renders it through the same
    branch as any other — the wording is the card's and the client states none of its own."""
    presenter, window = paying
    window.field.toggle_selection("of")

    presenter.confirm()

    assert _buttons(window) == ["Yes", "No", "Cancel"]
    assert _status(window) == "Give Outlying Farms +2GP? It is destroyed after it bows."
    assert not window.field.selecting  # a question, not a board selection


def test_a_grant_the_payment_cannot_do_without_greys_out_its_no(paying):
    """The Farm is the only way to cover the cost, so declining would strand a payment the seat has
    already committed to. Backing the whole action out is the way out, and it is on offer."""
    presenter, window = paying
    window.field.toggle_selection("of")

    presenter.confirm()

    enabled = [str(button.cget("state")) == "normal" for button in window.prompt_box._buttons]
    assert dict(zip(_buttons(window), enabled)) == {"Yes": True, "No": False, "Cancel": True}


def test_pay_lights_on_a_grant_the_producer_has_not_been_asked_for_yet(paying):
    """The Farm makes 2 against a cost of 4 and can raise itself to 4 in its window. The figure the
    seat reads is what the Farm makes now — promising the higher one would promise Gold it may still
    decline — but Pay is live, because there is a way to finish from here."""
    _, window = paying

    window.field.toggle_selection("of")

    assert _status(window) == "Pay 2 gold for Target"
    assert _primary_enabled(window)


def test_answering_the_window_finishes_the_payment_from_the_client(paying):
    presenter, window = paying
    window.field.toggle_selection("of")
    presenter.confirm()

    presenter.submit_answer(("of",))  # yes

    session = presenter.host.session
    assert session.game.pending is None
    assert session.game.table.cards_by_id["target"] in session.game.table.battlefield.cards


def test_a_yes_no_question_is_asked_by_its_buttons(board):
    """A Confirm's subjects are already settled, so the seat answers the question rather than
    picking cards off the board."""
    presenter, window, session = board
    session.game.pending = Confirm(
        seat=P1, candidates=("of",), question="Destroy the Farm?", resolver="probe"
    )

    presenter.refresh()

    assert _status(window) == "Destroy the Farm?"
    assert _buttons(window) == ["Yes", "No", "Cancel"]


def test_an_invest_decision_offers_a_button_per_affordable_amount(board):
    presenter, window, session = board
    session.game.pending = ChooseInvestAmount(
        seat=P1, candidates=("1", "2", "3"), source_card_id="of"
    )

    presenter.refresh()

    assert _buttons(window) == ["Invest 1", "Invest 2", "Invest 3", "Cancel"]


def test_a_variable_gold_cost_is_named_on_a_spinner_rather_than_a_button_each(board):
    # The amounts run as high as the seat can raise, which is a list no panel this width can hold,
    # so the seat steps a spinner and one button spends what it reads.
    presenter, window, session = board
    session.game.pending = ChooseAmount(
        seat=P1,
        candidates=tuple(str(amount) for amount in range(14)),
        question="How much Gold do you spend on Hired Killer?",
        resolver="hired_killer",
        source_id="killer",
    )

    presenter.refresh()

    assert _status(window) == "How much Gold do you spend on Hired Killer?"
    assert _buttons(window) == ["Spend", "Cancel"]
    assert window.prompt_box.amount() == "0"


def test_spending_answers_with_the_amount_the_spinner_shows():
    # The spinner is the only place the amount exists, so an answer that did not read it would spend
    # Gold the seat never agreed to. Driven through a real Hired Killer because the amount is asked
    # from inside its cost cascade, which is what the answer is spliced back into.
    state = TableState.empty_two_seat()
    put_in_play(state, holding("mine", owner=P1, gold_production=10))
    put_in_play(state, personality("dear", owner=PlayerId.P2, gold_cost=6))
    killer = register(
        state,
        L5RCard.of(
            ActionPrint,
            id="killer",
            name="Hired Killer",
            printed_id="hired_killer",
            side=Side.FATE,
            owner=P1,
        ),
    )
    state.zones[ZoneKey(P1, ZoneRole.HAND)].add(killer)
    session = EngineSession.start(state, P1)
    runner = GameRunner(session, P1)
    window = GameWindow(session.game.table, P1)
    presenter = Presenter(FakeHost(runner), window)
    try:
        presenter.act(PlayStrategy("killer"))
        assert _status(window) == "How much Gold do you spend on Hired Killer?"
        _set_spinner(window, "8")  # his unit costs 6, and the card reaches cost plus two

        _press(presenter, "Spend")

        assert session.game.pending.amount == 8  # the Gold the spinner named, now being charged
    finally:
        window.root.destroy()


def test_a_cost_of_nothing_is_paid_without_asking(board):
    # A payment with nothing owed has one possible answer, so putting it to the seat is a prompt
    # that can only be clicked through.
    presenter, window, session = board
    session.game.pending = payment_request(session.game, P1, 0, "Uncertainty")

    presenter.present()

    assert session.game.pending is None
    assert _buttons(window) != ["Pay", "Cancel"]


def test_a_finished_game_says_who_lost_and_offers_nothing(board):
    presenter, window, session = board
    session.game.lose(P1, "failed Legacy")

    presenter.refresh()

    assert _status(window) == "You lose (failed Legacy)"
    assert _buttons(window) == []


def test_the_opponent_losing_reads_from_the_human_seat(board):
    presenter, window, session = board
    session.game.lose(PlayerId.P2, "failed Legacy")

    presenter.refresh()

    assert _status(window) == "Opponent loses (failed Legacy)"


def test_the_window_wires_every_board_hook_to_the_presenter(board):
    """The bindings are the least-tested surface in the client: the characterization tests call the
    presenter directly, and nothing dispatches a real Tk event, so a hook left unassigned would
    reach nobody and fail nothing."""
    presenter, window, _ = board

    window.bind_to(presenter)

    field = window.field
    assert field.on_selection_changed == presenter.refresh
    assert field.on_card_activated == presenter.on_card_activated
    assert field.on_board_menu == presenter.on_board_menu
    assert field.load_deck_from_file == presenter.load_human_deck
    assert field.load_opponent_deck_from_file == presenter.load_opponent_deck


def test_the_window_binds_undo_and_escape_to_the_presenter(board):
    """Both are keyboard-only, so nothing else in the suite would notice them going unbound."""
    presenter, window, _ = board

    window.bind_to(presenter)

    assert window.root.bind("<Control-z>")
    assert window.root.bind("<Escape>")


@pytest.fixture
def two_producers():
    """A presenter on a payment no single producer covers, so it takes two rounds."""
    state = dealt_table()
    put_in_play(state, holding("a", owner=P1, gold_production=2))
    put_in_play(state, holding("b", owner=P1, gold_production=3))
    session = EngineSession.start(state, P1)
    province_card(session.game, "tgt", seat=P1, gold_cost=5)
    end_phase(session)
    end_phase(session)

    runner = GameRunner(session, P1)
    window = GameWindow(session.game.table, P1)
    presenter = Presenter(FakeHost(runner), window)
    window.field.on_selection_changed = presenter.refresh
    try:
        runner.act(Recruit("tgt"))
        presenter.present()
        yield presenter, window, session
    finally:
        window.root.destroy()


def test_a_payment_offers_only_what_is_left_to_bow_each_round(two_producers):
    """Each round is a fresh question, so the board re-derives its candidates rather than carrying
    the last one's. A producer that has already bowed is not on offer again."""
    presenter, window, _ = two_producers

    assert window.field.is_selectable("a") and window.field.is_selectable("b")

    window.field.toggle_selection("a")
    presenter.confirm()

    assert window.field.is_selectable("b")
    assert not window.field.is_selectable("a")  # it has bowed; it is not on offer again


def test_the_payment_prompt_is_exact_once_a_producer_has_bowed(two_producers):
    """Between rounds the figure is what the seat actually still owes, not a projection over cards
    that have not bowed. Clicking previews; confirming makes it true."""
    presenter, window, _ = two_producers

    assert _status(window) == "Pay 5 gold for tgt"
    window.field.toggle_selection("a")
    assert _status(window) == "Pay 3 gold for tgt"  # previewing a's two

    presenter.confirm()

    assert _status(window) == "Pay 3 gold for tgt"  # and now it is the pool talking


def test_a_two_round_payment_completes_from_the_board(two_producers):
    presenter, window, session = two_producers

    window.field.toggle_selection("a")
    presenter.confirm()
    window.field.toggle_selection("b")
    presenter.confirm()

    assert session.game.pending is None
    assert session.game.table.cards_by_id["tgt"] in session.game.table.battlefield.cards


def test_undo_takes_back_a_click_not_a_bow(two_producers):
    """Ctrl+Z during a payment un-picks the producer the seat has clicked. It can never be taking
    back a bow: bowing happens on confirm, which clears the selection with it."""
    presenter, window, session = two_producers
    window.field.toggle_selection("a")

    presenter.undo()

    assert window.field.selection == ()
    assert not session.game.table.cards_by_id["a"].bowed
    assert _status(window) == "Pay 5 gold for tgt"


def test_the_pay_button_lights_only_once_the_picks_cover_the_cost(two_producers):
    """Spacebar invokes the first button, so it must not be live on a payment the seat has not
    finished picking. Two producers at 2 and 3 against a cost of 5: neither alone is enough."""
    presenter, window, _ = two_producers

    assert _buttons(window)[0] == "Pay"
    assert not _primary_enabled(window)

    window.field.toggle_selection("a")
    assert not _primary_enabled(window)  # 2 of 5

    window.field.toggle_selection("b")
    assert _primary_enabled(window)  # 5 of 5

    presenter.confirm()
    assert "Pay" not in _buttons(window)  # paid; there is nothing left to press


def test_picking_both_producers_pays_in_one_click(two_producers):
    """The seat picks its whole payment and presses Pay once. The engine still takes one producer
    per answer, so the board feeds them to it — that is not the player's problem."""
    presenter, window, session = two_producers

    window.field.toggle_selection("a")
    window.field.toggle_selection("b")
    presenter.confirm()

    table = session.game.table
    assert session.game.pending is None
    assert table.cards_by_id["tgt"] in table.battlefield.cards
    assert table.cards_by_id["a"].bowed and table.cards_by_id["b"].bowed


def test_the_remaining_cost_counts_down_as_producers_are_picked(two_producers):
    """Clicking previews the bow: the figure falls by what that producer makes, before anything has
    actually bowed."""
    _, window, _ = two_producers

    assert _status(window) == "Pay 5 gold for tgt"
    window.field.toggle_selection("a")
    assert _status(window) == "Pay 3 gold for tgt"
    window.field.toggle_selection("b")
    assert _status(window) == "Pay 0 gold for tgt"


@pytest.fixture
def farm_and_a_helper():
    """A payment needing Outlying Farms' grant *and* a second producer, so the queue has something
    left in it when the Farm's window interrupts."""
    state = dealt_table()
    put_in_play(state, holding("of", owner=P1, printed_id="outlying_farms", gold_production=2))
    put_in_play(state, holding("small", owner=P1, gold_production=1))
    session = EngineSession.start(state, P1)
    province_card(session.game, "tgt", seat=P1, gold_cost=5)
    end_phase(session)
    end_phase(session)

    runner = GameRunner(session, P1)
    window = GameWindow(session.game.table, P1)
    presenter = Presenter(FakeHost(runner), window)
    window.field.on_selection_changed = presenter.refresh
    try:
        runner.act(Recruit("tgt"))
        presenter.present()
        yield presenter, window, session
    finally:
        window.root.destroy()


def test_a_window_pauses_the_queue_and_answering_it_spends_the_rest(farm_and_a_helper):
    """The seat picks both producers and presses Pay once. The Farm's window stops the queue mid-way
    so the seat can answer it; the producer still queued behind it is spent on the way back."""
    presenter, window, session = farm_and_a_helper
    window.field.toggle_selection("of")
    window.field.toggle_selection("small")

    presenter.confirm()

    assert isinstance(session.game.pending, Confirm)  # paused on the Farm's window
    assert window.field.committed == ("small",)  # and the rest of the payment is still queued

    presenter.submit_answer(("of",))  # yes

    table = session.game.table
    assert session.game.pending is None
    assert table.cards_by_id["tgt"] in table.battlefield.cards
    assert table.cards_by_id["small"].bowed
    assert table.cards_by_id["of"] not in table.battlefield.cards  # it paid its price


def test_cancelling_a_payment_forgets_what_was_queued(farm_and_a_helper):
    """Backing out at the window unwinds the announced Recruit, so the picks behind it must not be
    waiting to bow into whatever the seat does next."""
    presenter, window, session = farm_and_a_helper
    window.field.toggle_selection("of")
    window.field.toggle_selection("small")
    presenter.confirm()

    presenter.cancel()

    assert window.field.committed == ()
    table = session.game.table
    assert not table.cards_by_id["small"].bowed
    assert table.cards_by_id["of"] in table.battlefield.cards


def test_a_producer_queued_behind_a_grant_that_covered_the_cost_never_bows():
    """The seat picked more than it turned out to need: the Farm's grant covered the whole cost, so
    the engine stopped asking. What was still queued is spared, and dropped — a pick left waiting
    would bow into whatever the seat paid for next."""
    state = dealt_table()
    put_in_play(state, holding("of", owner=P1, printed_id="outlying_farms", gold_production=2))
    put_in_play(state, holding("spare", owner=P1, gold_production=3))
    session = EngineSession.start(state, P1)
    province_card(session.game, "tgt", seat=P1, gold_cost=4)
    end_phase(session)
    end_phase(session)

    runner = GameRunner(session, P1)
    window = GameWindow(session.game.table, P1)
    presenter = Presenter(FakeHost(runner), window)
    window.field.on_selection_changed = presenter.refresh
    try:
        runner.act(Recruit("tgt"))
        presenter.present()
        window.field.toggle_selection("of")
        window.field.toggle_selection("spare")
        presenter.confirm()
        presenter.submit_answer(("of",))  # yes: the Farm makes 4, which is the whole cost

        table = session.game.table
        assert session.game.pending is None
        assert table.cards_by_id["tgt"] in table.battlefield.cards
        assert not table.cards_by_id["spare"].bowed
        assert window.field.committed == ()
    finally:
        window.root.destroy()


@pytest.fixture
def gold_already_in_the_pool():
    """A presenter on a second purchase the floating pool alone covers, so the payment offers no
    producers at all."""
    state = dealt_table()
    put_in_play(state, holding("big", owner=P1, gold_production=8))
    session = EngineSession.start(state, P1)
    province_card(session.game, "first", seat=P1, gold_cost=3, index=0)
    province_card(session.game, "second", seat=P1, gold_cost=4, index=1)
    end_phase(session)
    end_phase(session)

    runner = GameRunner(session, P1)
    window = GameWindow(session.game.table, P1)
    presenter = Presenter(FakeHost(runner), window)
    window.field.on_selection_changed = presenter.refresh
    try:
        runner.act(Recruit("first"))
        presenter.present()
        window.field.toggle_selection("big")
        presenter.confirm()  # bows the 8-producer for a 3 cost, leaving 5 in the pool
        assert session.game.gold[P1] == 5
        runner.act(Recruit("second"))
        presenter.present()
        yield presenter, window, session
    finally:
        window.root.destroy()


def test_pay_spends_the_floating_pool_when_no_producer_is_on_offer(gold_already_in_the_pool):
    """The payment's only legal answer is to bow nothing, and the board has nothing to queue for it.
    Without an empty answer the seat is stuck on a lit Pay button that never resolves."""
    presenter, _, session = gold_already_in_the_pool

    presenter.confirm()

    table = session.game.table
    assert session.game.pending is None
    assert table.cards_by_id["second"] in table.battlefield.cards
    assert session.game.gold[P1] == 1


def test_a_pool_covered_payment_is_not_answered_until_pay_is_pressed(gold_already_in_the_pool):
    """Presenting must not spend on the seat's behalf: the payment is cancellable, and backing out
    of the Recruit is only possible while it is still pending."""
    presenter, _, session = gold_already_in_the_pool

    presenter.present()

    assert session.game.pending is not None
    assert session.game.gold[P1] == 5


def test_pay_with_nothing_picked_leaves_a_payment_that_still_owes_gold_open(two_producers):
    """The empty answer means "bow nothing", which is only true when the pool covers the cost. A
    payment still short of it must stay open rather than be sent an answer the engine refuses."""
    presenter, _, session = two_producers

    presenter.confirm()

    assert session.game.pending is not None
    assert session.game.gold[P1] == 0


@pytest.fixture
def a_battle():
    """A presenter in the Attack Phase, with a Personality to send and two Provinces to send it at."""
    state = TableState.empty_two_seat()
    for index in range(2):
        province_card(state, f"p2-prov{index}", seat=PlayerId.P2, index=index)
    province_card(state, "p1-prov0", seat=P1, index=0)
    put_in_play(state, personality("hero", owner=P1, force=5))
    session = EngineSession.start(state, P1)
    end_phase(session)

    runner = GameRunner(session, P1)
    window = GameWindow(session.game.table, P1)
    presenter = Presenter(FakeHost(runner), window)
    # The real wiring rather than a hand-picked hook, since the battle is played through several of
    # them now — the board's, and the lane buttons' in the battle view.
    window.bind_to(presenter)
    try:
        presenter.present()
        yield presenter, window, session
    finally:
        window.root.destroy()


def _specs(presenter) -> list:
    """The prompt box's button specs — label, callback and whether it is enabled."""
    return presenter._prompt(presenter.host.runner.view())[1]


def _press(presenter, label: str) -> None:
    """Press the prompt-box button reading ``label``, and present whatever the engine wants next."""
    for text, action, ready in _specs(presenter):
        if text == label:
            assert ready, f"{label!r} is disabled"
            action()
            return
    raise AssertionError(f"no {label!r} button; offered {[spec[0] for spec in _specs(presenter)]}")


def _picked(window) -> str:
    """A card in the board's current selection — whichever one the player would right-click."""
    return window.field.selection[0]


def _menu_on(presenter, window, card_id: str) -> dict[str, bool]:
    """Right-click ``card_id`` and read the menu it offers."""
    offered = []
    window.popup_at_pointer = lambda entries: offered.append(list(entries))
    presenter.on_card_activated(card_id)
    return {label: enabled for label, _, enabled in offered[0]}


def _assignment_menu(presenter) -> dict[str, bool]:
    """The card menu's entries while an assignment is open, to whether each is available."""
    return {label: enabled for label, _, enabled in presenter._assignment_menu()}


def _press_lane(presenter, battlefield: int, label: str) -> None:
    """Press ``battlefield``'s own button, the way the player answers a question about a place now
    that both of them are asked under the lane they are about."""
    buttons = presenter._lane_buttons()
    assert battlefield in buttons, f"battlefield {battlefield} offers no button; {buttons}"
    assert buttons[battlefield].label == label, f"reads {buttons[battlefield].label!r}"
    assert buttons[battlefield].enabled, f"battlefield {battlefield}'s button is greyed"
    buttons[battlefield].press()


def _run_the_opponent(presenter) -> None:
    """Let the AI take every opportunity it holds, so the human is the one being asked next.

    The client does this on a timer the tests do not pump, so a test that presses a button and
    expects the answer back has to hand the opportunity on itself.
    """
    runner = presenter.host.runner
    while runner.opponent_holds_priority or runner.opponent_owes_decision:
        runner.run_opponent()
        presenter.present()


def _fight_at(presenter, battlefield: int) -> None:
    """Fight the battle at ``battlefield`` from its lane, then pass out its segments from the board.

    A battle opens an Action Round per segment before it resolves, and each is passed the way the
    player passes anything: the opponent's opportunity is run, and the human's is the prompt box's
    own Pass button.
    """
    _press_lane(presenter, battlefield, "Fight here")
    runner = presenter.host.runner
    for _ in ruleset.ACTIVE.battle_segments:
        _run_the_opponent(presenter)
        # A seat with no presence at this battlefield is never offered the opportunity, so a
        # segment can close on the opponent's passes alone and leave nothing to press.
        if runner.session.game.attack.battle_segment is not None:
            _press(presenter, "Pass")
    presenter.present()


def _send(presenter, window, card_ids, battlefield: int) -> None:
    """Send units the way the player does: pick them, then press the button under the battlefield."""
    for card_id in card_ids:
        window.field.toggle_selection(card_id)
    _press_lane(presenter, battlefield, "Assign here")


def test_the_attack_phase_offers_the_declaration_as_a_button(a_battle):
    """Declaring is an action with no card to click, so the prompt box is the only place it can be
    taken from."""
    presenter, _, session = a_battle

    _press(presenter, "Declare an attack")

    assert session.game.attack is not None


def test_the_assignment_menu_shows_its_entry_before_it_is_reachable(a_battle):
    """It is listed and greyed, so the way back is visible before there is anything to take."""
    presenter, _, _ = a_battle
    _press(presenter, "Declare an attack")

    assert _assignment_menu(presenter) == {"Unassign units": False}


def test_picking_units_at_home_leaves_unassigning_out_of_reach(a_battle):
    """Sending them is the lane's button; the menu is only for bringing them back."""
    presenter, window, _ = a_battle
    _press(presenter, "Declare an attack")

    window.field.toggle_selection("hero")

    assert _assignment_menu(presenter)["Unassign units"] is False


def test_picking_units_at_a_battlefield_lights_up_bringing_them_back(a_battle):
    presenter, window, _ = a_battle
    _press(presenter, "Declare an attack")
    _send(presenter, window, ["hero"], 1)

    presenter.on_lane_card_clicked("hero")

    assert _assignment_menu(presenter)["Unassign units"] is True


def test_right_clicking_a_unit_picks_it(a_battle):
    """Sending a unit clears the picks, so the menu opened on the unit just sent would be greyed
    every time if right-clicking did not pick what it was opened on."""
    presenter, window, _ = a_battle
    _press(presenter, "Declare an attack")
    _send(presenter, window, ["hero"], 1)
    assert window.field.selection == ()

    offered = _menu_on(presenter, window, "hero")

    assert window.field.selection == ("hero",)
    assert offered["Unassign units"] is True


def test_right_clicking_a_unit_at_home_picks_it_too(a_battle):
    """Right-click means "this one" wherever it is done, so it readies the lanes' buttons as well as
    the menu."""
    presenter, window, _ = a_battle
    _press(presenter, "Declare an attack")
    assert not any(button.enabled for button in presenter._lane_buttons().values())

    _menu_on(presenter, window, "hero")

    assert window.field.selection == ("hero",)
    assert all(button.enabled for button in presenter._lane_buttons().values())


def test_right_clicking_a_unit_already_picked_keeps_the_rest_of_the_picks(a_battle):
    """Otherwise opening the menu on one of several picked units would throw the others away."""
    presenter, window, session = a_battle
    put_in_play(session.game, personality("second", owner=P1, force=3))
    _press(presenter, "Declare an attack")
    _send(presenter, window, ["hero", "second"], 1)
    presenter.on_lane_card_clicked("hero")
    presenter.on_lane_card_clicked("second")

    _menu_on(presenter, window, "hero")

    assert set(window.field.selection) == {"hero", "second"}


def test_clicking_a_follower_picks_the_unit_it_belongs_to(a_battle):
    """A unit answers as one card. A Follower is not an assignment candidate, so a click that named
    it would select nothing at all and leave every menu entry greyed."""
    presenter, window, session = a_battle
    attached(
        session.game,
        attachment("banner", attachment_type=AttachmentType.FOLLOWER, force=2, owner=P1),
        "hero",
    )
    _press(presenter, "Declare an attack")
    _send(presenter, window, ["hero"], 1)

    presenter.on_lane_card_clicked("banner")

    assert window.field.selection == ("hero",)
    assert _assignment_menu(presenter)["Unassign units"] is True


def test_a_selection_belongs_to_one_place_at_a_time(a_battle):
    """Picking somewhere else drops the old picks rather than mixing two places in one answer."""
    presenter, window, session = a_battle
    put_in_play(session.game, personality("second", owner=P1, force=3))
    _press(presenter, "Declare an attack")
    _send(presenter, window, ["hero"], 1)
    presenter.on_lane_card_clicked("hero")
    assert window.field.selection == ("hero",)

    window.field.toggle_selection("second")

    assert window.field.selection == ("second",)
    assert window.field.selection_zone is None


def test_picking_at_one_battlefield_drops_picks_at_another(a_battle):
    """Two battlefields are as different as home and a battlefield: an answer names one place."""
    presenter, window, session = a_battle
    put_in_play(session.game, personality("second", owner=P1, force=3))
    _press(presenter, "Declare an attack")
    _send(presenter, window, ["hero"], 0)
    _send(presenter, window, ["second"], 1)
    presenter.on_lane_card_clicked("hero")
    assert window.field.selection_zone == 0

    presenter.on_lane_card_clicked("second")

    assert window.field.selection == ("second",)
    assert window.field.selection_zone == 1


def test_changing_the_picks_while_choosing_a_battlefield_sends_the_new_ones(a_battle):
    """The board stays pickable while the destination is being chosen, so what it highlights has to
    be what gets sent."""
    presenter, window, session = a_battle
    put_in_play(session.game, personality("second", owner=P1, force=3))
    _press(presenter, "Declare an attack")
    window.field.toggle_selection("hero")

    window.field.toggle_selection("second")
    _press_lane(presenter, 1, "Assign here")

    assert window.field.assigned_units() == {"hero": 1, "second": 1}


def test_several_units_go_to_a_battlefield_in_one_step(a_battle):
    presenter, window, session = a_battle
    put_in_play(session.game, personality("second", owner=P1, force=3))
    _press(presenter, "Declare an attack")

    _send(presenter, window, ["hero", "second"], 1)

    assert window.field.assigned_units() == {"hero": 1, "second": 1}


def test_unassigning_brings_back_every_unit_picked_at_that_battlefield(a_battle):
    presenter, window, session = a_battle
    put_in_play(session.game, personality("second", owner=P1, force=3))
    _press(presenter, "Declare an attack")
    _send(presenter, window, ["hero", "second"], 1)
    presenter.on_lane_card_clicked("hero")
    presenter.on_lane_card_clicked("second")

    presenter.unassign_units()

    assert window.field.assigned_units() == {}


def test_sending_a_unit_somewhere_else_moves_it(a_battle):
    """There is no army to leave first — where a unit stands is the whole of the model."""
    presenter, window, _ = a_battle
    _press(presenter, "Declare an attack")
    _send(presenter, window, ["hero"], 0)

    _send(presenter, window, ["hero"], 1)

    assert window.field.assigned_units() == {"hero": 1}


def test_two_armies_go_to_two_provinces_in_one_answer(a_battle):
    """The CR has a seat assign simultaneously, so however many armies it gathers, the engine is
    told once."""
    presenter, window, session = a_battle
    put_in_play(session.game, personality("second", owner=P1, force=3))
    _press(presenter, "Declare an attack")
    _send(presenter, window, ["hero"], 0)
    _send(presenter, window, ["second"], 1)

    _press(presenter, "Done assigning")

    table = session.game.table
    assert location_of(table, table.cards_by_id["hero"]).battlefield == 0
    assert location_of(table, table.cards_by_id["second"]).battlefield == 1


def test_a_unit_left_at_home_is_not_assigned(a_battle):
    """Picking a unit is not committing it: only one that was sent somewhere is in the answer."""
    presenter, window, session = a_battle
    _press(presenter, "Declare an attack")
    window.field.toggle_selection("hero")

    _press(presenter, "Done assigning")

    assert location_of(session.game.table, session.game.table.cards_by_id["hero"]).is_home


def test_the_assign_buttons_go_away_once_the_assignment_is_answered(a_battle):
    """They are the gesture for a question that is over; what the lanes offer next is the battle."""
    presenter, window, _ = a_battle
    _press(presenter, "Declare an attack")
    _send(presenter, window, ["hero"], 0)

    _press(presenter, "Done assigning")
    presenter.host.runner.run_opponent()
    presenter.present()

    assert [button.label for button in presenter._lane_buttons().values()] == [
        "Fight here",
        "Fight here",
    ]


def test_the_prompt_names_the_battle_segment_and_the_battlefield(a_battle):
    """A battle's segments are the only place the seat is asked to act inside another segment, so
    the heading has to name the one being fought — "Fight Battles" is true of every battle in the
    phase and tells the player nothing about the one in front of them."""
    presenter, window, session = a_battle
    runner = presenter.host.runner
    _press(presenter, "Declare an attack")
    _send(presenter, window, ["hero"], 1)
    _press(presenter, "Done assigning")
    _run_the_opponent(presenter)
    _press_lane(presenter, 1, "Fight here")

    said = []
    for _ in range(len(ruleset.ACTIVE.battle_segments)):
        _run_the_opponent(presenter)
        said.append(presenter._prompt(runner.view())[0])
        _press(presenter, "Pass")

    assert said == [
        "Your Engage Segment at Battlefield 2",
        "Your Combat Segment at Battlefield 2",
    ]


def test_both_battle_segments_are_passed_from_the_prompt_box(a_battle):
    """The seat's opportunity inside a battle is offered where every other opportunity is. Passing
    both segments is what carries the battle to its resolution, so a segment that offered nothing
    would strand the phase."""
    presenter, window, session = a_battle
    _press(presenter, "Declare an attack")
    _send(presenter, window, ["hero"], 0)
    _press(presenter, "Done assigning")
    _run_the_opponent(presenter)
    _press_lane(presenter, 0, "Fight here")
    _run_the_opponent(presenter)

    assert [label for label, _, _ in _specs(presenter)] == ["Pass"]
    _press(presenter, "Pass")
    _run_the_opponent(presenter)

    assert session.game.attack.battle_segment is BattleSegment.COMBAT
    _press(presenter, "Pass")
    _run_the_opponent(presenter)

    assert session.game.attack.fought == frozenset({0})


def test_a_battle_can_be_fought_to_its_end_from_the_board(a_battle):
    """The whole loop: declare, gather, send, assign, then choose where to fight until the phase
    runs out — which is what makes a battle playable rather than merely reachable."""
    presenter, window, session = a_battle
    runner = presenter.host.runner
    _press(presenter, "Declare an attack")
    _send(presenter, window, ["hero"], 0)
    _press(presenter, "Done assigning")
    runner.run_opponent()
    presenter.present()

    _fight_at(presenter, 0)
    _fight_at(presenter, 1)

    assert session.game.attack.fought == frozenset({0, 1})
    assert session.game.table.cards_by_id["hero"].bowed  # After Resolution bows the attackers


def test_the_prompt_box_names_the_next_step_at_every_point(a_battle):
    """The board carries the interaction, so the prompt box has to carry the instructions — a player
    who does not already know the flow has nothing else to read."""
    presenter, window, _ = a_battle
    _press(presenter, "Declare an attack")
    said = [presenter._prompt(presenter.host.runner.view())[0]]

    window.field.toggle_selection("hero")
    said.append(presenter._prompt(presenter.host.runner.view())[0])
    _press_lane(presenter, 0, "Assign here")
    said.append(presenter._prompt(presenter.host.runner.view())[0])

    assert said == [
        "Click the Personalities you want to attack with, then press a battlefield's button",
        "1 picked at home - press Assign here under the battlefield you want",
        "Click more Personalities to send, or press Done assigning to fight the battles",
    ]


def test_the_prompt_box_only_says_what_to_do_and_finishes(a_battle):
    """The lanes carry the assigning. The prompt box says what to do next and offers the one answer
    that is not about any battlefield."""
    presenter, window, _ = a_battle
    _press(presenter, "Declare an attack")
    assert [label for label, _, _ in _specs(presenter)] == ["Done assigning"]

    window.field.toggle_selection("hero")

    assert [label for label, _, _ in _specs(presenter)] == ["Done assigning"]


def test_every_battlefield_offers_its_button_for_as_long_as_the_question_is_open(a_battle):
    """Where units could go is visible before any are picked, so the player is not hunting for the
    gesture that sends them."""
    presenter, window, _ = a_battle
    _press(presenter, "Declare an attack")

    greyed = presenter._lane_buttons()
    assert [button.label for button in greyed.values()] == ["Assign here", "Assign here"]
    assert not any(button.enabled for button in greyed.values())

    window.field.toggle_selection("hero")

    assert all(button.enabled for button in presenter._lane_buttons().values())


def test_losing_the_last_Province_says_so_rather_than_naming_the_wrong_rule(a_battle):
    """Every loss used to be announced as a failed Legacy, so a seat overrun said the one thing that
    had not happened to it."""
    presenter, _, session = a_battle
    session.game.lose(PlayerId.P2, "no Provinces remaining")

    status, buttons = presenter._prompt(presenter.host.runner.view())

    assert status == "Opponent loses (no Provinces remaining)"
    assert buttons == []


def test_undo_takes_back_the_last_step_of_an_assignment(a_battle):
    """Setting up an attack is scratch work — nothing reaches the engine until the whole map is
    answered — so each step comes back one at a time."""
    presenter, window, session = a_battle
    put_in_play(session.game, personality("second", owner=P1, force=3))
    _press(presenter, "Declare an attack")
    _send(presenter, window, ["hero"], 0)
    _send(presenter, window, ["second"], 1)
    assert window.field.assigned_units() == {"hero": 0, "second": 1}

    presenter.undo()

    assert window.field.assigned_units() == {"hero": 0}


def test_undo_brings_a_sent_unit_back_home(a_battle):
    presenter, window, _ = a_battle
    _press(presenter, "Declare an attack")
    _send(presenter, window, ["hero"], 1)
    assert window.field.assigned_units() == {"hero": 1}

    presenter.undo()

    assert window.field.assigned_units() == {}


def test_undo_puts_an_unassigned_unit_back_at_its_battlefield(a_battle):
    """Unassigning is a step like any other; the symmetric case to undoing a send."""
    presenter, window, _ = a_battle
    _press(presenter, "Declare an attack")
    _send(presenter, window, ["hero"], 1)
    presenter.on_lane_card_clicked("hero")
    presenter.unassign_units()
    assert window.field.assigned_units() == {}

    presenter.undo()

    assert window.field.assigned_units() == {"hero": 1}


def test_undo_walks_back_one_step_at_a_time(a_battle):
    """Each step is its own entry, so a history that only remembered the last one would take the
    player straight to the start."""
    presenter, window, session = a_battle
    put_in_play(session.game, personality("second", owner=P1, force=3))
    _press(presenter, "Declare an attack")
    _send(presenter, window, ["hero"], 0)
    _send(presenter, window, ["second"], 1)

    presenter.undo()
    assert window.field.assigned_units() == {"hero": 0}  # the second send is taken back

    presenter.undo()
    assert window.field.assigned_units() == {}  # then the first


def test_undo_at_the_start_of_an_assignment_does_nothing(a_battle):
    presenter, window, _ = a_battle
    _press(presenter, "Declare an attack")

    presenter.undo()

    assert window.field.assigned_units() == {}


def test_an_answered_assignment_is_no_longer_the_players_to_take_back(a_battle):
    """Once the map is answered the Defender assigns against it, so the steps that built it stop
    being scratch work."""
    presenter, window, _ = a_battle
    _press(presenter, "Declare an attack")
    _send(presenter, window, ["hero"], 1)

    _press(presenter, "Done assigning")
    presenter.undo()

    assert window.field.assigned_units() == {}
    assert window.field._assignment_history == []


def test_the_battle_opens_clear_of_the_half_the_player_is_seated_at(a_battle):
    """Assigning means reading your own units at home and pressing a button in the panel, so a panel
    that opens over your half puts the two halves of one task on top of each other."""
    presenter, window, _ = a_battle

    _press(presenter, "Declare an attack")

    placed = window.battle_view.place_info()
    _, board_h = widget_size(window.field)
    assert int(placed["y"]) == 0
    # The opponent's half, unless that half is shorter than a panel can usefully be — a board too
    # small to dock in is one where the panel has to overrun to stay worth showing at all.
    assert int(placed["height"]) == max(divider_y(board_h), MIN_H)


def test_the_battle_floats_over_the_board_with_an_attack_and_leaves_with_it(a_battle):
    """It is display only, so it is on the board exactly as long as there is an attack to show."""
    presenter, window, session = a_battle
    assert not window.battle_view.showing

    _press(presenter, "Declare an attack")
    assert window.battle_view.showing

    _press(presenter, "Done assigning")
    presenter.host.runner.run_opponent()
    presenter.present()
    _fight_at(presenter, 0)
    _fight_at(presenter, 1)
    _press(presenter, "Pass")  # the Attack Phase ends, and the battlefields cease to exist

    assert session.game.attack is None
    assert not window.battle_view.showing


def test_a_unit_sent_to_a_battlefield_stands_there_before_the_engine_is_told(a_battle):
    """The player has decided; the engine hearing about it on Done assigning is bookkeeping they
    should not have to watch for."""
    presenter, window, _ = a_battle
    _press(presenter, "Declare an attack")
    _send(presenter, window, ["hero"], 1)

    canvas = window.battle_view.canvas
    tags = {tag for item in canvas.find_all() for tag in canvas.gettags(item)}

    assert "battle:hero" in tags


def test_a_unit_sent_to_a_battlefield_leaves_the_board(a_battle):
    """It is drawn in the lane now, and drawing it in both places would say it is in two."""
    presenter, window, _ = a_battle
    _press(presenter, "Declare an attack")
    _send(presenter, window, ["hero"], 1)

    assert not window.field._at_home("hero")


def _stat_stamps(canvas, card_id: str) -> set[str]:
    """The numbers stamped on ``card_id``'s sprite."""
    return {
        canvas.itemcget(item, "text")
        for item in canvas.find_withtag(f"{card_id}:stat")
        if canvas.type(item) == "text"
    }


def test_a_card_on_the_board_is_stamped_with_the_force_the_engine_would_use(a_battle):
    """Not the printed number. A granted modifier that the board does not report leaves the player
    adding up an army from figures the engine disagrees with."""
    presenter, window, session = a_battle
    session.game.modifiers.append(
        Modifier("test", "hero", Stat.FORCE, 4, Duration.UNTIL_END_OF_TURN)
    )

    presenter.present()

    assert "9" in _stat_stamps(window.field, "card:hero")  # printed 5, granted +4


def test_a_unit_in_a_lane_is_stamped_with_the_same_number(a_battle):
    """The lane draws the same sprites the board does, and a unit whose Force reads one way at home
    and another at the battlefield is worse than one that reports neither."""
    presenter, window, session = a_battle
    session.game.modifiers.append(
        Modifier("test", "hero", Stat.FORCE, 4, Duration.UNTIL_END_OF_TURN)
    )
    _press(presenter, "Declare an attack")

    _send(presenter, window, ["hero"], 1)

    assert "9" in _stat_stamps(window.battle_view.canvas, "battle:hero")


def test_the_force_a_lane_shows_does_not_move_when_the_assignment_is_answered(a_battle):
    """The player sees the total the moment they send the army; the engine being told is bookkeeping,
    and a figure that jumps at that point reads as something having changed.

    The Personality carries a Follower, so a total taken off his printed Force rather than his
    unit's is a different number and this notices.
    """
    presenter, window, session = a_battle
    attached(
        session.game,
        attachment("banner", attachment_type=AttachmentType.FOLLOWER, force=4, owner=P1),
        "hero",
    )
    _press(presenter, "Declare an attack")
    _send(presenter, window, ["hero"], 1)
    while_pending = presenter._pending_armies(presenter.host.runner.view())[1].force

    _press(presenter, "Done assigning")

    view = presenter.host.runner.view()
    assert while_pending == 9  # the Personality's 5 and his Follower's 4
    assert view.attack.battlefields[1].attacking_force == while_pending


def test_a_unit_sent_to_a_battlefield_takes_its_followers_off_the_board(a_battle):
    """Only the Personality is named in an assignment, so a board that asks each card whether it was
    sent leaves his Followers behind — drawn at home while the same cards are drawn in the lane."""
    presenter, window, session = a_battle
    attached(
        session.game,
        attachment("banner", attachment_type=AttachmentType.FOLLOWER, force=2, owner=P1),
        "hero",
    )
    _press(presenter, "Declare an attack")

    _send(presenter, window, ["hero"], 1)

    assert not window.field._at_home("hero")
    assert not window.field._at_home("banner")


def test_a_unit_sent_to_a_battlefield_can_still_be_unassigned(a_battle):
    """The lane is the only place it is drawn, so the menu the board gave it has to be reachable
    from there or the player has no way back."""
    presenter, window, _ = a_battle
    _press(presenter, "Declare an attack")
    _send(presenter, window, ["hero"], 1)

    presenter.on_lane_card_clicked("hero")
    presenter.unassign_units()

    assert window.field._at_home("hero")
    assert window.field.assigned_units() == {}
