import pytest

from yasuki_core.engine.players import PlayerId
from yasuki_core.engine.rules.actions import Recruit
from yasuki_core.engine.rules.decisions import ChooseInvestAmount, Confirm
from yasuki_core.engine.runner import GameRunner
from yasuki_core.engine.session import EngineSession
from yasuki_core.engine.table import DeckKey, TableState, ZoneKey, ZoneRole, location_of
from yasuki_core.engine.zones import ProvinceZone
from yasuki_core.game_pieces.cards import L5RCard
from yasuki_core.game_pieces.constants import Side
from yasuki_core.game_pieces.prints import HoldingPrint
from yasuki_gui.services.presenter import Presenter
from yasuki_gui.ui.game_window import GameWindow

from tests.yasuki_core.engine.builders import (
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


def test_a_finished_game_says_who_lost_and_offers_nothing(board):
    presenter, window, session = board
    session.game.loser = P1

    presenter.refresh()

    assert _status(window) == "You lose (failed Legacy)"
    assert _buttons(window) == []


def test_the_opponent_losing_reads_from_the_human_seat(board):
    presenter, window, session = board
    session.game.loser = PlayerId.P2

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
    window.field.on_selection_changed = presenter.refresh
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
            presenter.present()
            return
    raise AssertionError(f"no {label!r} button; offered {[spec[0] for spec in _specs(presenter)]}")


def _picked(window) -> str:
    """A card in the board's current selection — whichever one the player would right-click."""
    return window.field.selection[0]


def _army_menu(presenter, card_id: str) -> dict[str, bool]:
    """The card menu's entries while an assignment is open, to whether each is available."""
    return {label: enabled for label, _, enabled in presenter._army_menu(card_id)}


def _send_army(presenter, window, card_id: str, battlefield: int) -> None:
    """Assign ``card_id``'s army the way the player does: ask for a Province, click one, confirm."""
    presenter.assign_army(card_id)
    window.field.toggle_selection(presenter._battlefield_tokens()[battlefield])
    _press(presenter, "Attack here")


def test_the_attack_phase_offers_the_declaration_as_a_button(a_battle):
    """Declaring is an action with no card to click, so the prompt box is the only place it can be
    taken from."""
    presenter, _, session = a_battle

    _press(presenter, "Declare an attack")

    assert session.game.attack is not None


def test_the_army_menu_shows_every_step_before_any_is_reachable(a_battle):
    """All four entries are listed and greyed, so the sequence is visible before it can be walked."""
    presenter, _, _ = a_battle
    _press(presenter, "Declare an attack")

    assert _army_menu(presenter, "hero") == {
        "Add to army": False,
        "Remove from army": False,
        "Assign army": False,
        "Unassign army": False,
    }


def test_picking_units_lights_up_gathering_them_into_an_army(a_battle):
    presenter, window, _ = a_battle
    put_in_play(presenter.host.session.game, personality("second", owner=P1, force=3))
    _press(presenter, "Declare an attack")

    window.field.toggle_selection("second")

    assert _army_menu(presenter, "hero")["Add to army"] is True


def test_an_army_is_closed_to_editing_once_it_has_been_sent(a_battle):
    presenter, window, _ = a_battle
    put_in_play(presenter.host.session.game, personality("second", owner=P1, force=3))
    _press(presenter, "Declare an attack")
    window.field.toggle_selection("second")

    presenter.form_army("hero")
    assert window.field.armies == (("second", "hero"),)  # picked first, clicked last
    assert _army_menu(presenter, "hero")["Assign army"] is True

    _send_army(presenter, window, "hero", 1)
    menu = _army_menu(presenter, "hero")
    assert menu["Unassign army"] is True
    assert menu["Assign army"] is False  # a sent army is closed until it is brought home

    presenter.recall_army("hero")
    assert _army_menu(presenter, "hero")["Assign army"] is True


def test_leaving_an_army_disbands_one_it_empties(a_battle):
    presenter, window, _ = a_battle
    _press(presenter, "Declare an attack")
    presenter.form_army("hero")

    presenter.leave_army("hero")

    assert window.field.armies == ()
    assert _army_menu(presenter, "hero")["Remove from army"] is False


def test_two_armies_go_to_two_provinces_in_one_answer(a_battle):
    """The CR has a seat assign simultaneously, so however many armies it gathers, the engine is
    told once."""
    presenter, window, session = a_battle
    put_in_play(session.game, personality("second", owner=P1, force=3))
    _press(presenter, "Declare an attack")
    presenter.form_army("hero")
    _send_army(presenter, window, "hero", 0)
    presenter.form_army("second")
    _send_army(presenter, window, "second", 1)

    _press(presenter, "Done assigning")

    table = session.game.table
    assert location_of(table, table.cards_by_id["hero"]).battlefield == 0
    assert location_of(table, table.cards_by_id["second"]).battlefield == 1


def test_an_army_left_at_home_is_not_assigned(a_battle):
    """Gathering an army is not committing it: only one that was sent somewhere is in the answer."""
    presenter, window, session = a_battle
    _press(presenter, "Declare an attack")
    presenter.form_army("hero")

    _press(presenter, "Done assigning")

    assert location_of(session.game.table, session.game.table.cards_by_id["hero"]).is_home


def test_cancelling_a_province_choice_leaves_the_army_gathered_and_home(a_battle):
    presenter, window, _ = a_battle
    _press(presenter, "Declare an attack")
    presenter.form_army("hero")
    presenter.assign_army("hero")

    _press(presenter, "Cancel")

    assert window.field.armies == (("hero",),)
    assert window.field.battlefield_of_army(0) is None


def test_a_battle_can_be_fought_to_its_end_from_the_board(a_battle):
    """The whole loop: declare, gather, send, assign, then choose where to fight until the phase
    runs out — which is what makes a battle playable rather than merely reachable."""
    presenter, window, session = a_battle
    runner = presenter.host.runner
    _press(presenter, "Declare an attack")
    presenter.form_army("hero")
    _send_army(presenter, window, "hero", 0)
    _press(presenter, "Done assigning")
    runner.run_opponent()
    presenter.present()

    _press(presenter, "Battlefield 1")
    _press(presenter, "Battlefield 2")

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
    presenter.form_army(_picked(window))
    said.append(presenter._prompt(presenter.host.runner.view())[0])
    presenter.assign_army("hero")
    said.append(presenter._prompt(presenter.host.runner.view())[0])

    assert said == [
        "Click the Personalities you want to attack with, then right-click one",
        "1 picked - right-click one to add them to an army",
        "Right-click an army to assign it to a Province",
        "Click one of the Defender's Provinces, then Attack here",
    ]


def test_the_prompt_box_only_confirms_cancels_and_finishes(a_battle):
    """The card menu carries the army work. The prompt box says what to do next and offers the
    three answers that are not about any one card."""
    presenter, window, _ = a_battle
    _press(presenter, "Declare an attack")
    assert [label for label, _, _ in _specs(presenter)] == ["Done assigning"]

    presenter.form_army("hero")
    assert [label for label, _, _ in _specs(presenter)] == ["Done assigning"]

    presenter.assign_army("hero")
    assert [label for label, _, _ in _specs(presenter)] == ["Attack here", "Cancel"]


def test_units_in_the_same_army_share_a_ring_and_different_armies_do_not(a_battle):
    """The ring is the only thing on the board that says which units travel together."""
    presenter, window, session = a_battle
    for name in ("second", "third"):
        put_in_play(session.game, personality(name, owner=P1, force=3))
    _press(presenter, "Declare an attack")
    window.field.toggle_selection("second")
    presenter.form_army("hero")
    presenter.form_army("third")

    rings = {name: window.field._army_ring(name) for name in ("hero", "second", "third")}

    assert rings["hero"] == rings["second"]
    assert rings["third"] not in (None, rings["hero"])


def test_a_unit_in_no_army_has_no_ring(a_battle):
    presenter, window, _ = a_battle
    _press(presenter, "Declare an attack")

    assert window.field._army_ring("hero") is None


def test_the_battle_floats_over_the_board_with_an_attack_and_leaves_with_it(a_battle):
    """It is display only, so it is on the board exactly as long as there is an attack to show."""
    presenter, window, session = a_battle
    assert not window.battle_view.showing

    _press(presenter, "Declare an attack")
    assert window.battle_view.showing

    _press(presenter, "Done assigning")
    presenter.host.runner.run_opponent()
    presenter.present()
    _press(presenter, "Battlefield 1")
    _press(presenter, "Battlefield 2")
    _press(presenter, "Pass")  # the Attack Phase ends, and the battlefields cease to exist

    assert session.game.attack is None
    assert not window.battle_view.showing


def test_the_battle_view_shows_what_has_been_assigned_so_far(a_battle):
    presenter, window, _ = a_battle
    _press(presenter, "Declare an attack")
    presenter.form_army("hero")
    _send_army(presenter, window, "hero", 1)

    canvas = window.battle_view.canvas
    texts = [
        canvas.itemcget(item, "text") for item in canvas.find_all() if canvas.type(item) == "text"
    ]

    assert "sending hero" in texts
