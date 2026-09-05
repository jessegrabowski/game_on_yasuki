from dataclasses import replace

import pytest

from yasuki_core import ruleset
from yasuki_core.engine.players import PlayerId
from yasuki_core.engine.rules import legality
from yasuki_core.engine.rules.legality import lobby_key
from yasuki_core.engine.rules.actions import Lobby
from yasuki_core.engine.rules.decisions import DecisionResponse
from yasuki_core.engine.rules.flow import lobby, submit
from yasuki_core.engine.rules.state import GameState
from yasuki_core.engine.runner import GameRunner
from yasuki_core.engine.session import EngineSession
from yasuki_core.engine.table import TableState

from tests.yasuki_core.engine.builders import personality, put_in_play


def _game(*, p1_honor: int = 10, p2_honor: int = 5) -> GameState:
    """A two-seat game on P1's turn, with P1 ahead on Family Honor unless a test says otherwise."""
    game = GameState.start(TableState.empty_two_seat(), PlayerId.P1, seed=0)
    game.table.seats[PlayerId.P1].honor = p1_honor
    game.table.seats[PlayerId.P2].honor = p2_honor
    return game


def _lobbies(game: GameState, seat: PlayerId = PlayerId.P1) -> list[Lobby]:
    return [action for action in legality.legal_actions(game, seat) if isinstance(action, Lobby)]


def test_lobby_is_offered_once_however_many_personalities_could_pay_for_it():
    """The ability is one action; which Personality it bows is chosen when it resolves."""
    game = _game()
    put_in_play(game, personality("courtier", personal_honor=2))
    put_in_play(game, personality("champion", personal_honor=1))

    assert _lobbies(game) == [Lobby()]


def test_the_target_decision_offers_every_personality_that_could_pay():
    """ShE datasheet: bow your target unbowed Personality with 1 or more Personal Honor."""
    game = _game()
    put_in_play(game, personality("courtier", personal_honor=2))
    put_in_play(game, personality("champion", personal_honor=1))
    put_in_play(game, personality("peasant", personal_honor=0))

    lobby(game)

    assert set(game.pending.candidates) == {"courtier", "champion"}


def test_lobby_is_not_offered_on_another_seats_turn():
    """ShE datasheet states the condition explicitly: "If it is your turn".

    The rival is given priority in the open round, so the round itself permits them to act. Without
    that, an Open designator would let the non-active seat Lobby on someone else's turn -- which is
    exactly why the datasheet spells the condition out.
    """
    game = _game(p1_honor=5, p2_honor=10)
    put_in_play(game, personality("courtier", owner=PlayerId.P2, personal_honor=2))
    game.round = replace(game.round, priority=PlayerId.P2)
    assert legality.permits(game, PlayerId.P2, ruleset.ACTIVE.lobby_timing), (
        "the round has to permit the rival, or this proves nothing"
    )

    assert _lobbies(game, PlayerId.P2) == []


@pytest.mark.parametrize("rival_honor", [10, 11], ids=["tied", "ahead"])
def test_lobby_needs_strictly_higher_family_honor_than_every_rival(rival_honor):
    """ShE datasheet: higher Family Honor than each other player, so a tie does not qualify."""
    game = _game(p1_honor=10, p2_honor=rival_honor)
    put_in_play(game, personality("courtier", personal_honor=2))

    assert _lobbies(game) == []


def test_lobby_is_not_offered_without_a_personality_to_bow():
    game = _game()

    assert _lobbies(game) == []


def test_a_bowed_personality_cannot_pay_for_lobby():
    game = _game()
    bowed = put_in_play(game, personality("courtier", personal_honor=2))
    bowed.bow()

    assert _lobbies(game) == []


def test_a_personality_with_no_personal_honor_cannot_pay_for_lobby():
    """Zero is the boundary the datasheet draws: 1 or more Personal Honor, not simply any."""
    game = _game()
    put_in_play(game, personality("peasant", personal_honor=0))

    assert _lobbies(game) == []


def test_answering_the_target_bows_the_personality_and_takes_the_favor():
    game = _game()
    put_in_play(game, personality("courtier", personal_honor=2))
    lobby(game)

    submit(game, DecisionResponse(choices=("courtier",)))

    assert game.table.cards_by_id["courtier"].bowed is True
    assert game.favor_holder is PlayerId.P1


def test_taking_lobby_takes_the_favor_from_the_seat_that_held_it():
    """Twenty Festivals CR: one player controls the Favor and changes of control are instantaneous,
    so the rival loses it as this seat gains it."""
    game = _game()
    game.favor_holder = PlayerId.P2
    put_in_play(game, personality("courtier", personal_honor=2))
    lobby(game)

    submit(game, DecisionResponse(choices=("courtier",)))

    assert game.favor_holder is PlayerId.P1


def test_the_board_menu_offers_lobby_once():
    """The Favor belongs to no card, so the empty board is the only place Lobby can be offered."""
    session = EngineSession.start(TableState.empty_two_seat(), PlayerId.P1)
    game = session.game
    game.table.seats[PlayerId.P1].honor = 10
    game.table.seats[PlayerId.P2].honor = 5
    put_in_play(game, personality("courtier", name="Doji Kuwanan", personal_honor=2))
    runner = GameRunner(session, PlayerId.P1)

    assert ("Lobby: bow a Personality to take the Imperial Favor", Lobby()) in runner.board_menu()


def test_taking_lobby_spends_its_once_per_turn_use():
    """ShE datasheet: player abilities may only be taken once per turn per player by default, and
    the Lobby keyword caps a player at one Lobby action per turn besides.

    Asserts the claim rather than that a second Lobby is unavailable: the resolved action closes the
    Action Round on its own, so an offering check here would pass with the cap removed entirely.
    """
    game = _game()
    put_in_play(game, personality("courtier", personal_honor=2))
    lobby(game)

    submit(game, DecisionResponse(choices=("courtier",)))

    assert game.has_used(lobby_key(PlayerId.P1, game.turn))


def test_a_spent_lobby_is_not_offered_again_until_the_next_turn():
    """The usage key is scoped to the turn, so it resets without clearing ``once_per``."""
    game = _game()
    put_in_play(game, personality("courtier", personal_honor=2))
    game.use_once(lobby_key(PlayerId.P1, game.turn))
    assert _lobbies(game) == []

    game.turn += 2  # back round to this seat's next turn

    assert _lobbies(game) == [Lobby()]
