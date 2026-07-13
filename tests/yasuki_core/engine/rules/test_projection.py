from yasuki_core.engine.players import PlayerId
from yasuki_core.engine.table import TableState, ZoneKey, ZoneRole
from yasuki_core.game_pieces.constants import Side
from yasuki_core.game_pieces.fate import FateCard
from yasuki_core.engine.redaction import HiddenCard
from yasuki_core.engine.rules.state import GameState, Phase
from yasuki_core.engine.rules.decisions import DiscardToHandSize
from yasuki_core.engine.rules.projection import project


def _game() -> GameState:
    return GameState.start(TableState.empty_two_seat(), PlayerId.P1, seed=7)


def test_rules_fields_are_public_to_both_seats():
    game = _game()
    game.phase = Phase.DYNASTY
    game.add_gold(PlayerId.P1, 3)
    game.add_gold(PlayerId.P2, 1)

    for viewer in PlayerId:
        view = project(game, viewer)
        assert view.viewer is viewer
        assert view.turn == 1
        assert view.active is PlayerId.P1
        assert view.phase is Phase.DYNASTY
        assert view.first_player is PlayerId.P1
        # Both seats' gold pools are visible to either viewer.
        assert view.gold == {PlayerId.P1: 3, PlayerId.P2: 1}


def test_pending_decision_reaches_only_the_answerer():
    game = _game()
    request = DiscardToHandSize(PlayerId.P1, ("a", "b", "c"), count=2)
    game.pending = request

    assert project(game, PlayerId.P1).pending == request
    assert project(game, PlayerId.P2).pending is None


def test_table_is_redacted_for_the_viewer():
    game = _game()
    secret = FateCard(id="P1-secret", name="Ambush", side=Side.FATE, owner=PlayerId.P1)
    game.table.cards_by_id[secret.id] = secret
    game.table.zones[ZoneKey(PlayerId.P1, ZoneRole.HAND)].add(secret)

    owner_view = project(game, PlayerId.P1)
    opponent_view = project(game, PlayerId.P2)

    hand_key = ZoneKey(PlayerId.P1, ZoneRole.HAND)
    assert owner_view.table.zones[hand_key].cards[0] is secret
    assert isinstance(opponent_view.table.zones[hand_key].cards[0], HiddenCard)


def test_gold_view_is_decoupled_from_the_live_pool():
    game = _game()
    view = project(game, PlayerId.P1)
    game.add_gold(PlayerId.P1, 5)
    # The projection captured a snapshot; later production does not mutate it.
    assert view.gold[PlayerId.P1] == 0
