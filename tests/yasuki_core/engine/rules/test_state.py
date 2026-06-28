from yasuki_core.engine.players import PlayerId
from yasuki_core.engine.table import TableState
from yasuki_core.engine.rules.state import GameState, Phase


def _game(seed: int = 0) -> GameState:
    return GameState.start(TableState.empty_two_seat(), PlayerId.P1, seed=seed)


def test_start_opens_first_players_action_phase_with_empty_pools():
    game = _game(seed=42)

    assert game.turn == 1
    assert game.active is game.first_player is PlayerId.P1
    assert game.phase is Phase.ACTION
    assert game.gold == {PlayerId.P1: 0, PlayerId.P2: 0}
    assert game.favor_holder is None
    assert game.once_per == set()
    assert game.seed == 42


def test_gold_accumulates_then_clears_per_phase():
    game = _game()
    game.add_gold(PlayerId.P1, 2)
    game.add_gold(PlayerId.P1, 3)
    assert game.gold[PlayerId.P1] == 5

    game.clear_gold()
    assert game.gold == {PlayerId.P1: 0, PlayerId.P2: 0}


def test_spend_gold_deducts_only_when_the_pool_covers_it():
    game = _game()
    game.add_gold(PlayerId.P1, 4)

    assert game.spend_gold(PlayerId.P1, 3) is True
    assert game.gold[PlayerId.P1] == 1

    # Overspend is refused and leaves the pool untouched.
    assert game.spend_gold(PlayerId.P1, 2) is False
    assert game.gold[PlayerId.P1] == 1

    # Spending the exact remainder is allowed and drains the pool.
    assert game.spend_gold(PlayerId.P1, 1) is True
    assert game.gold[PlayerId.P1] == 0


def test_use_once_is_claimed_exactly_once():
    game = _game()

    assert game.has_used("inheritance") is False
    assert game.use_once("inheritance") is True
    assert game.has_used("inheritance") is True
    # A second claim is refused; a different key is independent.
    assert game.use_once("inheritance") is False
    assert game.use_once("proclaim") is True
