import pytest

from yasuki_core.engine.players import PlayerId
from yasuki_core.engine.rules import triggers
from yasuki_core.engine.rules.events import Revealed, TurnStarted
from yasuki_core.engine.rules.flow import begin_game

from tests.yasuki_core.engine.builders import holding, province_card, put_in_play, two_seat_game

P1 = PlayerId.P1


@pytest.fixture
def reacting():
    """Register triggers for one test and clear them afterwards.

    `_TRIGGERS` is module-global and appends, so a leaked registration fires in every later test in
    the process. The fixture owns that hygiene; each test still writes its own reaction inline.
    """
    registered: list[tuple[type, str]] = []

    def _register(event: type, printed_id: str, trigger):
        triggers.on(event, printed_id)(trigger)
        registered.append((event, printed_id))

    yield _register
    for event, printed_id in registered:
        triggers._TRIGGERS[event].pop(printed_id, None)


def _watching_game():
    """A two-seat game with a card in play whose printed id carries the tests' probe triggers."""
    game = two_seat_game()
    put_in_play(game, holding("P1-eyes", owner=P1, printed_id="reveal_probe"))
    return game


def test_the_turn_start_sweep_raises_revealed_for_each_card_it_turns(reacting):
    seen = []
    reacting(Revealed, "reveal_probe", lambda ctx: seen.append(ctx.event.card_id) or [])
    game = _watching_game()
    province_card(game, "P1-a", seat=P1, face_up=False, index=0)
    province_card(game, "P1-b", seat=P1, face_up=False, index=1)

    begin_game(game)

    assert sorted(seen) == ["P1-a", "P1-b"]


def test_a_card_already_face_up_is_not_revealed_again(reacting):
    # The event names the turn, not the state, so a card the sweep leaves alone raises nothing —
    # otherwise every subscriber would fire again on each of the owner's turns.
    seen = []
    reacting(Revealed, "reveal_probe", lambda ctx: seen.append(ctx.event.card_id) or [])
    game = _watching_game()
    province_card(game, "P1-open", seat=P1, face_up=True, index=0)

    begin_game(game)

    assert seen == []


def test_the_sweep_reveals_only_the_active_seat_s_provinces(reacting):
    seen = []
    reacting(Revealed, "reveal_probe", lambda ctx: seen.append(ctx.event.card_id) or [])
    game = _watching_game()
    province_card(game, "P1-mine", seat=P1, face_up=False, index=0)
    province_card(game, "P2-theirs", seat=PlayerId.P2, face_up=False, index=0)

    begin_game(game)

    assert seen == ["P1-mine"]


def test_every_reveal_resolves_before_the_turn_has_started(reacting):
    # A reaction to the reveal acts during the sweep, so it must not see a board where the turn is
    # already under way — and the last card turned still precedes the turn starting.
    order = []
    reacting(Revealed, "reveal_probe", lambda ctx: order.append("revealed") or [])
    reacting(TurnStarted, "reveal_probe", lambda ctx: order.append("turn-started") or [])
    game = _watching_game()
    province_card(game, "P1-a", seat=P1, face_up=False, index=0)
    province_card(game, "P1-b", seat=P1, face_up=False, index=1)

    begin_game(game)

    assert order == ["revealed", "revealed", "turn-started"]
