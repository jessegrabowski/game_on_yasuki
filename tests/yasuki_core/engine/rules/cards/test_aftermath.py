from yasuki_core.engine import ops
from yasuki_core.engine.players import PlayerId
from yasuki_core.engine.rules.state import GameState
from yasuki_core.engine.rules.stats.calculation import effective_stat
from yasuki_core.engine.rules.vocabulary import keywords
from yasuki_core.engine.rules.vocabulary.modifiers import Stat
from yasuki_core.engine.table import Location, ZoneKey, ZoneRole
from yasuki_core.engine.zones import ProvinceZone
from yasuki_core.game_pieces.cards import L5RCard
from yasuki_core.game_pieces.constants import AttachmentType, Side
from yasuki_core.game_pieces.prints import ActionPrint

from tests.yasuki_core.engine.builders import (
    attached,
    attachment,
    personality,
    put_in_play,
    register,
    two_seat_game,
)

P1, P2 = PlayerId.P1, PlayerId.P2


def _with_lonely_battlefield() -> GameState:
    game = two_seat_game()
    terrain = put_in_play(
        game,
        L5RCard.of(
            ActionPrint,
            id="lonely",
            name="Lonely Battlefield",
            printed_id="lonely_battlefield",
            side=Side.FATE,
            owner=P1,
            keywords=(keywords.TERRAIN,),
        ),
    )
    ops.set_location(game.table, terrain, Location.at_battlefield(0))
    return game


def _force(game: GameState, card: L5RCard) -> int:
    return effective_stat(game, card, Stat.FORCE)


def test_lonely_battlefield_takes_2_force_from_every_personality_without_followers():
    game = _with_lonely_battlefield()
    alone = put_in_play(game, personality("alone", owner=P2, force=3))
    armed = put_in_play(game, personality("armed", owner=P1, force=3))
    attached(game, attachment("katana", owner=P1), "armed")
    escorted = put_in_play(game, personality("escorted", owner=P2, force=3))
    attached(
        game,
        attachment("ashigaru", owner=P2, attachment_type=AttachmentType.FOLLOWER, force=1),
        "escorted",
    )

    assert _force(game, alone) == 1
    assert _force(game, armed) == 1
    assert _force(game, escorted) == 3


def test_lonely_battlefield_gives_commanders_1_force():
    game = _with_lonely_battlefield()
    alone = put_in_play(
        game, personality("alone", owner=P2, force=3, keywords=(keywords.COMMANDER,))
    )
    escorted = put_in_play(
        game, personality("escorted", owner=P1, force=3, keywords=(keywords.COMMANDER,))
    )
    attached(
        game,
        attachment("ashigaru", owner=P1, attachment_type=AttachmentType.FOLLOWER, force=1),
        "escorted",
    )

    assert _force(game, alone) == 2
    assert _force(game, escorted) == 4


def test_lonely_battlefield_leaves_a_personality_waiting_in_a_province_alone():
    game = _with_lonely_battlefield()
    waiting = register(game.table, personality("waiting", owner=P1, force=3))
    waiting.turn_face_up()
    province = ProvinceZone(owner=P1)
    assert province.add(waiting)
    game.table.zones[ZoneKey(P1, ZoneRole.PROVINCE, 0)] = province

    assert _force(game, waiting) == 3
