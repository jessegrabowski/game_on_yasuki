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

from tests.yasuki_core.engine.builders import end_phase, put_in_play, register

P1 = PlayerId.P1


class FakeHost:
    """What the presenter reads off a :class:`~yasuki_gui.services.game_host.GameHost`. Real here
    would mean dealing a decklist out of Postgres, and the boost path needs a board built card by
    card rather than whatever a deck happens to hold."""

    def __init__(self, runner: GameRunner):
        self.runner = runner
        self.human_seat = runner.human

    @property
    def session(self) -> EngineSession:
        return self.runner.session


def _boostable_board() -> EngineSession:
    """A Dynasty phase where the one Holding on offer is affordable only by boosting.

    Outlying Farms produces 2 and boosts to 4, so recruiting the cost-4 target means taking the
    boost — which is what makes the client ask the question at all.
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
    """A presenter over a game paused on a boostable payment, with the board already in selection
    mode — the state the client is in when the player is about to pick a producer."""
    session = _boostable_board()
    runner = GameRunner(session, P1)
    host = FakeHost(runner)
    window = GameWindow(session.game.table, P1)
    presenter = Presenter(host, window)
    window.field.on_boost_request = presenter.request_boost
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
    session = _boostable_board()
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


def test_the_payment_prompt_asks_which_producers_to_bow(paying):
    _, window = paying

    assert "Cancel" in _buttons(window)
    assert window.field.selecting


def test_picking_a_boostable_producer_pre_empts_the_payment_prompt(paying):
    """The board suspends the toggle and asks the presenter; the presenter turns that into the
    boost question, naming the extra gold the decision offers rather than a number of its own."""
    _, window = paying

    window.field.toggle_selection("of")

    assert _buttons(window) == ["Boost", "Skip"]
    # Wording and price both come off the decision, so the client states neither of its own.
    assert _status(window) == "Boost this Holding as it bows? +2 Gold, then it is destroyed."


def test_taking_the_boost_resumes_the_payment_with_the_producer_chosen(paying):
    presenter, window = paying
    window.field.toggle_selection("of")

    presenter.answer_boost(True)

    assert window.field.selection == ("of",)
    assert window.field.boosted == frozenset({"of"})
    assert _buttons(window) != ["Boost", "Skip"]


def test_skipping_the_boost_resumes_the_payment_unboosted(paying):
    presenter, window = paying
    window.field.toggle_selection("of")

    presenter.answer_boost(False)

    assert window.field.selection == ("of",)
    assert window.field.boosted == frozenset()


def test_answering_a_question_nobody_asked_does_nothing(paying):
    """``answer_boost`` reads the producer off the board, so a stray call with no question open has
    none to answer rather than a stale one."""
    presenter, window = paying

    presenter.answer_boost(True)

    assert window.field.selection == ()
    assert window.field.boosted == frozenset()


def test_a_yes_no_question_is_asked_by_its_buttons(board):
    """A Confirm's subjects are already settled, so the seat answers the question rather than
    picking cards off the board."""
    presenter, window, session = board
    session.game.pending = Confirm(
        seat=P1, candidates=("of",), question="Destroy the Farm?", resolver="probe"
    )

    presenter.refresh()

    assert _status(window) == "Destroy the Farm?"
    assert _buttons(window) == ["Yes", "No"]


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
    assert field.on_boost_request == presenter.request_boost
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
