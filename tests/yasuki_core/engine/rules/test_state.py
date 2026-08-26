from yasuki_core.engine.players import PlayerId
from yasuki_core.engine.table import TableState
from yasuki_core.engine.rules.state import GameState, Phase, rules_at_start
from yasuki_core.engine.rules.decisions import DiscardToHandSize
from yasuki_core.engine.rules.victory import VictoryRule

from tests.yasuki_core.engine.builders import province_card


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
    assert game.pending is None
    assert game.awaiting_decision is False


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


def test_awaiting_decision_tracks_the_pending_request():
    game = _game()
    game.pending = DiscardToHandSize(PlayerId.P1, ("c1",), count=1)
    assert game.awaiting_decision is True


def test_use_once_is_claimed_exactly_once():
    game = _game()

    assert game.has_used("inheritance") is False
    assert game.use_once("inheritance") is True
    assert game.has_used("inheritance") is True
    # A second claim is refused; a different key is independent.
    assert game.use_once("inheritance") is False
    assert game.use_once("proclaim") is True


def test_a_seat_dealt_provinces_can_lose_them_all():
    state = TableState.empty_two_seat()
    province_card(state, "prov", seat=PlayerId.P1, index=0)

    assert VictoryRule.MILITARY_LOSS in rules_at_start(state, PlayerId.P1)


def test_a_seat_dealt_no_provinces_is_not_held_to_the_military_loss():
    # Otherwise a board built card by card loses on the first check, before it has been dealt a
    # game to lose — and after dealing, "never had any" and "lost them all" look identical.
    state = TableState.empty_two_seat()
    province_card(state, "prov", seat=PlayerId.P1, index=0)

    assert VictoryRule.MILITARY_LOSS not in rules_at_start(state, PlayerId.P2)


def test_a_started_game_records_the_rules_each_seat_plays_under():
    state = TableState.empty_two_seat()
    province_card(state, "prov", seat=PlayerId.P1, index=0)

    game = GameState.start(state, PlayerId.P1)

    assert set(game.active_rules) == set(PlayerId)
    assert game.active_rules[PlayerId.P1] == rules_at_start(state, PlayerId.P1)
