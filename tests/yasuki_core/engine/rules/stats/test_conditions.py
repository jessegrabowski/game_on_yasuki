from yasuki_core.engine import ops
from yasuki_core.engine.players import PlayerId
from yasuki_core.engine.rules.battle.records import AttackPhase, BattlefieldInfo
from yasuki_core.engine.rules.stats.conditions import condition_holds
from yasuki_core.engine.rules.state import GameState
from yasuki_core.engine.rules.vocabulary.modifiers import Condition
from yasuki_core.engine.table import Location, ZoneKey, ZoneRole
from yasuki_core.game_pieces.constants import AttachmentType

from tests.yasuki_core.engine.builders import (
    attached,
    attachment,
    personality,
    put_in_play,
    two_seat_game,
)

P1, P2 = PlayerId.P1, PlayerId.P2


def _battle() -> GameState:
    """P1 attacks P2's first Province. Both seats have a Personality at the battlefield and one at
    home, and the attacker at the battlefield carries a Follower."""
    game = two_seat_game()
    game.attack = AttackPhase(
        attacker=P1,
        defender=P2,
        battlefields=(BattlefieldInfo(province=ZoneKey(P2, ZoneRole.PROVINCE, 0)),),
        current=0,
    )
    for card_id, owner in (("raider", P1), ("guard", P2)):
        unit = put_in_play(game, personality(card_id, owner=owner))
        ops.set_location(game.table, unit, Location.at_battlefield(0))
    put_in_play(game, personality("reserve", owner=P1))
    put_in_play(game, personality("courtier", owner=P2))
    attached(game, attachment("ashigaru", attachment_type=AttachmentType.FOLLOWER), "raider")
    return game


def test_attacking_holds_for_the_attackers_personality_at_the_battlefield():
    game = _battle()

    assert condition_holds(game, game.table.cards_by_id["raider"], Condition.ATTACKING) is True


def test_attacking_fails_for_the_defender_and_for_anyone_at_home():
    game = _battle()

    for card_id in ("guard", "reserve", "courtier"):
        card = game.table.cards_by_id[card_id]
        assert condition_holds(game, card, Condition.ATTACKING) is False, card_id


def test_attacking_is_about_personalities_and_passes_over_their_followers():
    game = _battle()

    assert condition_holds(game, game.table.cards_by_id["ashigaru"], Condition.ATTACKING) is False


def test_attacking_fails_between_battles():
    game = _battle()
    game.attack.current = None

    assert condition_holds(game, game.table.cards_by_id["raider"], Condition.ATTACKING) is False
