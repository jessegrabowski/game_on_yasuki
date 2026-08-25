import pytest

from yasuki_core.engine.players import PlayerId
from yasuki_core.engine.rules.actions import Recruit
from yasuki_core.engine.rules.decisions import ChooseInvestAmount, Confirm
from yasuki_core.engine.runner import GameRunner
from yasuki_core.engine.session import EngineSession
from yasuki_core.engine.table import DeckKey, TableState, ZoneKey, ZoneRole
from yasuki_core.engine.zones import ProvinceZone
from yasuki_core.game_pieces.cards import L5RCard
from yasuki_core.game_pieces.constants import Side
from yasuki_core.game_pieces.prints import HoldingPrint
from yasuki_gui.services.presenter import Presenter
from yasuki_gui.ui.game_window import GameWindow

from tests.yasuki_core.engine.builders import (
    dealt_table,
    end_phase,
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
    assert (
        _status(window) == "Give Outlying Farms +2 Gold Production? It is destroyed after it bows."
    )
    assert not window.field.selecting  # a question, not a board selection


def test_a_grant_the_payment_cannot_do_without_greys_out_its_no(paying):
    """The Farm is the only way to cover the cost, so declining would strand a payment the seat has
    already committed to. Backing the whole action out is the way out, and it is on offer."""
    presenter, window = paying
    window.field.toggle_selection("of")

    presenter.confirm()

    enabled = [str(button.cget("state")) == "normal" for button in window.prompt_box._buttons]
    assert dict(zip(_buttons(window), enabled)) == {"Yes": True, "No": False, "Cancel": True}


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


def test_the_pay_button_is_dead_until_a_producer_is_picked(two_producers):
    """Spacebar invokes the first button, and a payment is now several rounds. It cannot run away:
    each round starts with nothing picked, and an answer naming nothing is not one the payment
    accepts while it is still short."""
    presenter, window, _ = two_producers

    assert _buttons(window)[0] == "Pay"
    assert not _primary_enabled(window)

    window.field.toggle_selection("a")
    assert _primary_enabled(window)
    presenter.confirm()

    assert not _primary_enabled(window)
