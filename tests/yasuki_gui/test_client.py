import pytest
from numpy.random import default_rng

from yasuki_core.engine.players import PlayerId
from yasuki_core.engine.rules.actions import Cycle, Pass
from yasuki_core.game_pieces.prints import StrongholdPrint

import yasuki_gui.services.presenter as presenter_mod
from yasuki_gui.__main__ import build_client
from yasuki_gui.services.presenter import Presenter
from yasuki_gui.session import DEMO_DECK_PATH

from tests.yasuki_core.db_guard import requires_db

# Every test here builds a client, and building one deals the chosen decks out of Postgres. Without
# it the deal degrades to the placeholder deck, where both seats tie on Family Honor and turn order
# is never resolved — so these would not fail honestly, they would assert against a different game.
pytestmark = requires_db

# Turn order goes to the higher Family Honor, so a pairing that differs on it decides who leads
# outright. The bundled Spider deck opens at -2 and the Crane deck at 5; a mirror match ties and
# draws for it, which is right for a game and useless for a test.
LOW_HONOR = DEMO_DECK_PATH
HIGH_HONOR = DEMO_DECK_PATH.parent / "crane_starter.yaml"


def _build(monkeypatch, *, human_leads: bool) -> Presenter:
    """A client dealt so the human leads or does not, never entered into its event loop.

    The opponent hand-off is scheduled with ``root.after``, so a test pumps the event queue to let
    it run; the delay is zeroed so pumping is instant rather than a real 700ms wait.
    """
    monkeypatch.setattr(presenter_mod, "OPPONENT_TURN_DELAY_MS", 0)
    return build_client(
        human_deck=HIGH_HONOR if human_leads else LOW_HONOR,
        opponent_deck=LOW_HONOR if human_leads else HIGH_HONOR,
        rng=default_rng(7),
    )


@pytest.fixture
def client(monkeypatch):
    built = _build(monkeypatch, human_leads=True)
    try:
        yield built
    finally:
        built.window.root.destroy()


def _status(client: Presenter) -> str:
    return client.window.prompt_box._status.cget("text")


def _buttons(client: Presenter) -> list[str]:
    return [button.cget("text") for button in client.window.prompt_box._buttons]


def _pump(client: Presenter, steps: int = 200) -> None:
    """Run queued Tk callbacks until the human has something to do, or ``steps`` have passed."""
    for _ in range(steps):
        client.window.root.update()
        if client.host.runner.legal_actions():
            return


def test_the_higher_honor_deck_takes_the_first_turn(client):
    runner = client.host.runner

    assert runner.session.game.first_player is runner.human


def test_the_human_is_offered_a_pass_on_its_own_turn(client):
    assert _status(client) == "Your Action Phase"
    assert _buttons(client) == ["Pass"]


def test_a_game_the_opponent_leads_hands_over_and_comes_back(monkeypatch):
    """The soft lock fixed in #127: with the AI leading, the client runs the opponent rather than
    leaving the human an empty prompt and nothing to click."""
    ai_first = _build(monkeypatch, human_leads=False)
    try:
        runner = ai_first.host.runner
        assert runner.session.game.first_player is not runner.human

        _pump(ai_first)

        assert ai_first.host.runner.legal_actions()
        assert "Pass" in _buttons(ai_first)
    finally:
        ai_first.window.root.destroy()


def test_passing_advances_the_phase(client):
    before = client.host.runner.view().phase
    client.act(Pass())
    _pump(client)

    assert client.host.runner.view().phase is not before


def _stronghold_name(client: Presenter, seat) -> str:
    game = client.host.session.game
    return next(
        card.name
        for card in game.table.battlefield.cards
        if card.owner is seat and isinstance(card.printed, StrongholdPrint)
    )


def test_loading_a_deck_restarts_the_game_on_it(client):
    """A new session is not enough — it has to be dealt from the deck that was picked, which the
    opponent's Stronghold is the cheapest way to see."""
    opponent = PlayerId.P2 if client.host.runner.human is PlayerId.P1 else PlayerId.P1
    before = _stronghold_name(client, opponent)

    client.load_opponent_deck(str(HIGH_HONOR))

    assert _stronghold_name(client, opponent) != before
    # The board has to be re-pointed at the new game, not left rendering the old one.
    assert client.window.field.state is client.host.session.game.table


def test_a_deck_that_fails_to_load_leaves_the_game_running(client):
    before = client.host.session.game

    with pytest.raises(FileNotFoundError):
        client.load_opponent_deck(str(DEMO_DECK_PATH.parent / "no_such_deck.yaml"))

    assert client.host.session.game is before


def test_an_action_that_raises_a_decision_puts_the_board_into_selection(client):
    """Cycle is the human's first-turn Limited action and it asks which Province cards to bury, so
    it is the cheapest way to reach a pending decision from a fresh game."""
    assert Cycle() in client.host.runner.legal_actions()

    client.act(Cycle())

    pending = client.host.runner.pending
    assert pending is not None
    assert _status(client) == pending.prompt()
    assert client.window.field.selecting


def test_backing_out_of_a_decision_leaves_the_board_alone(client):
    client.act(Cycle())
    assert client.host.runner.pending is not None

    client.cancel()

    assert client.host.runner.pending is None
    assert not client.window.field.selecting


def test_backing_out_leaves_the_board_on_the_table_the_engine_kept(client):
    """Cancelling rewinds the tape and replays it onto a fresh table. A board still pointed at the
    old one renders a game nobody is playing — the honor readout freezes where it stood while the
    engine goes on without it."""
    client.act(Cycle())

    client.cancel()

    assert client.window.field.state is client.host.session.game.table


def test_the_honor_readout_follows_the_engine_after_a_cancel(client):
    """The readout reads whichever source is rendering, so it keeps up with the engine even when
    the board is left holding a table the engine has replaced."""
    seat = client.window.field.seat
    client.act(Cycle())
    client.cancel()

    client.host.session.game.table.seats[seat].honor += 5
    client.present()

    shown = client.window.human_panel._honor_text.get()
    assert shown == f"Honor {client.host.session.game.table.seats[seat].honor}"


def test_the_honor_readout_ignores_a_board_left_on_a_stale_table(client):
    """During play the engine owns honor, so the readout reads whatever is rendering rather than
    the sandbox table the board carries. Reading the table instead makes the counter freeze the
    moment anything hands the board a copy the engine has moved on from."""
    seat = client.window.field.seat
    client.host.session.game.table.seats[seat].honor = 9
    client.present()
    client.window.field.state.seats[seat].honor = 999  # a table the engine is no longer using

    client.window.human_panel.refresh()

    assert client.window.human_panel._honor_text.get() == "Honor 9"


def test_confirming_a_decision_resolves_it(client):
    client.act(Cycle())
    pending = client.host.runner.pending
    client.window.field.toggle_selection(pending.candidates[0])

    client.confirm()

    assert client.host.runner.pending is None
    assert not client.window.field.selecting


def test_the_opening_board_renders_the_game_that_was_dealt(client):
    assert client.window.field.state is client.host.session.game.table
