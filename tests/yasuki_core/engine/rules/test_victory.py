import pytest

from yasuki_core import ruleset
from yasuki_core.engine.players import PlayerId
from yasuki_core.engine.rules.log import replay
from yasuki_core.engine.rules.victory import VictoryRule
from yasuki_core.engine.session import EngineSession
from yasuki_core.engine.table import DeckKey, TableState
from yasuki_core.game_pieces.constants import Side

from tests.yasuki_core.engine.builders import end_turn, fate_card, register

P1, P2 = PlayerId.P1, PlayerId.P2
HONOR_VICTORY_AT = ruleset.ACTIVE.honor_victory_at
DISHONOR_LOSS_AT = ruleset.ACTIVE.dishonor_loss_at


def _table() -> TableState:
    """A bare two-seat table with enough fate cards for several turns to end on their draws."""
    state = TableState.empty_two_seat()
    for seat in PlayerId:
        state.decks[DeckKey(seat, Side.FATE)].cards = [
            register(state, fate_card(f"{seat.name}-fd{i}", seat)) for i in range(4)
        ]
    return state


def _game() -> EngineSession:
    return EngineSession.start(_table(), P1)


def test_starting_a_turn_on_the_threshold_wins_an_honor_victory():
    session = _game()
    session.game.table.seats[P2].honor = HONOR_VICTORY_AT

    end_turn(session)  # P1's turn ends, P2's begins

    assert session.game.winner is P2
    assert session.game.win_reason == f"Honor Victory on {HONOR_VICTORY_AT} Family Honor"
    assert session.game.loser is None  # won outright; nobody lost
    assert session.game.game_over is True


def test_a_point_short_of_the_threshold_does_not_win():
    session = _game()
    session.game.table.seats[P2].honor = HONOR_VICTORY_AT - 1

    end_turn(session)

    assert session.game.game_over is False


def test_honor_reached_and_lost_within_a_turn_wins_nothing():
    """The CR wins on the Honor a seat *starts* its turn with, so a seat that climbs past the
    threshold during its turn and falls back before the next one has won nothing."""
    session = _game()
    session.game.table.seats[P1].honor = HONOR_VICTORY_AT + 5  # climbs past it during P1's turn

    end_turn(session)  # P2's turn begins, and P2 is nowhere near the threshold
    session.game.table.seats[P1].honor = HONOR_VICTORY_AT - 1  # and P1 falls back during it
    end_turn(session)  # P1's turn begins a point short

    assert session.game.game_over is False
    assert session.game.turn == 3


def test_a_seat_excused_the_honor_victory_starts_the_same_turn_and_does_not_win():
    """Kaede Sensei reads "You permanently will not win an Honor Victory"; dropping the rule from
    that seat alone is how the engine holds it."""
    session = _game()
    session.game.table.seats[P2].honor = HONOR_VICTORY_AT
    session.game.active_rules[P2] = session.game.active_rules[P2] - {VictoryRule.HONOR_VICTORY}

    end_turn(session)

    assert session.game.game_over is False
    assert session.game.turn == 2  # the turn started normally rather than being cut short


def test_ending_a_turn_at_the_dishonor_threshold_loses_and_wins_the_other_seat_the_game():
    session = _game()
    session.game.table.seats[P1].honor = DISHONOR_LOSS_AT

    end_turn(session)

    assert session.game.loser is P1
    assert session.game.loss_reason == f"{DISHONOR_LOSS_AT} Family Honor"
    assert session.game.winner is P2
    assert session.game.win_reason == "Dishonor Victory"


def test_a_point_above_the_dishonor_threshold_survives():
    session = _game()
    session.game.table.seats[P1].honor = DISHONOR_LOSS_AT + 1

    end_turn(session)

    assert session.game.game_over is False


def test_only_the_seat_whose_turn_is_ending_is_checked_for_dishonor():
    """A seat driven below the threshold on its opponent's turn has its own turn to climb out of
    it, because the CR checks a player at the end of *his or her* turn."""
    session = _game()
    session.game.table.seats[P2].honor = DISHONOR_LOSS_AT - 5

    end_turn(session)  # P1's turn ends with P2 far below the threshold

    assert session.game.game_over is False
    assert session.game.active is P2


def test_a_seat_excused_dishonor_ends_its_turn_below_the_threshold_and_plays_on():
    """The Hidden Catacombs of the Scorpion reads "You will not lose, or be eliminated, by
    Dishonor"."""
    session = _game()
    session.game.table.seats[P1].honor = DISHONOR_LOSS_AT - 10
    session.game.active_rules[P1] = session.game.active_rules[P1] - {VictoryRule.DISHONOR_LOSS}

    end_turn(session)

    assert session.game.game_over is False


def test_the_dishonor_loss_is_taken_before_the_opponent_could_win_on_honor():
    """Both fire at the same boundary. The loss is the end of the turn that is finishing and the
    Honor Victory the start of the one beginning, so a seat cannot be handed a turn it has already
    won when the game ended before that turn existed."""
    session = _game()
    session.game.table.seats[P1].honor = DISHONOR_LOSS_AT
    session.game.table.seats[P2].honor = HONOR_VICTORY_AT

    end_turn(session)

    assert session.game.winner is P2
    assert session.game.win_reason == "Dishonor Victory"  # not the Honor Victory it also had
    assert session.game.turn == 1  # P2's turn never began


@pytest.mark.parametrize("losing, surviving", [(P1, P2), (P2, P1)])
def test_a_loss_awards_the_last_player_left_the_victory_it_names(losing, surviving):
    """The CR states Military and Dishonor Victory from the survivor's side — one player loses, and
    the one remaining player has thereby won. Either seat can be the one that goes."""
    session = _game()

    session.game.lose(losing, "no Provinces remaining", "Military Victory")

    assert (session.game.loser, session.game.loss_reason) == (losing, "no Provinces remaining")
    assert (session.game.winner, session.game.win_reason) == (surviving, "Military Victory")


def test_the_first_turn_of_the_game_can_be_won_on_honor():
    """The game's opening turn is a turn like any other, and it reaches the check by a different
    route than every later one — through the game-start pass rather than the end of a turn."""
    state = _table()
    state.seats[P1].honor = HONOR_VICTORY_AT

    session = EngineSession.start(state, P1)

    assert session.game.winner is P1
    assert session.game.turn == 1


def test_an_honor_victory_replays_to_the_same_ending():
    """The tape carries inputs rather than outcomes, so the win has to be re-derived from the same
    board on the way back — a check that fires off the turn boundary must fire during replay too."""
    state = _table()
    state.seats[P2].honor = HONOR_VICTORY_AT  # in the snapshot, so the tape carries it
    session = EngineSession.start(state, P1)
    end_turn(session)

    rebuilt = replay(session.log)

    assert (rebuilt.winner, rebuilt.win_reason) == (session.game.winner, session.game.win_reason)
    assert rebuilt.table == session.game.table
