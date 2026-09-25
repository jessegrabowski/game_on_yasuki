from collections.abc import Callable

from yasuki_core.engine.players import PlayerId
from yasuki_core.engine.table import TableState, DeckKey, ZoneKey, ZoneRole
from yasuki_core.engine.zones import ProvinceZone
from yasuki_core.engine.rules.battle.resolution import army_force
from yasuki_core.engine.rules.stats.calculation import effective_stat
from yasuki_core.engine.rules.vocabulary.actions import DeclareAttack, Pass, PlayStrategy, Recruit
from yasuki_core.engine.rules.vocabulary.decisions import (
    ChooseCards,
    DecisionResponse,
    assignment_token,
)
from yasuki_core.engine.rules.vocabulary.modifiers import Stat
from yasuki_core.engine.rules.vocabulary.segments import BattleSegment
from yasuki_core.engine.rules.turn.structure import RoundKind
from yasuki_core.engine.table import location_of
from yasuki_core.engine.session import EngineSession
from yasuki_core.game_pieces.constants import Side
from yasuki_core.game_pieces.cards import L5RCard
from yasuki_core.game_pieces.prints import ActionPrint, HoldingPrint

from tests.yasuki_core.engine.builders import (
    contentious_terrain,
    end_phase,
    pay,
    personality,
    province_card,
    put_in_play,
    register,
    terrain_at,
)

P1 = PlayerId.P1
P2 = PlayerId.P2


def _in_hand(state: TableState, card: L5RCard) -> L5RCard:
    state.zones[ZoneKey(card.owner, ZoneRole.HAND)].add(register(state, card))
    return card


def _fate_discard(table: TableState, seat: PlayerId) -> set[str]:
    return {card.id for card in table.zones[ZoneKey(seat, ZoneRole.FATE_DISCARD)].cards}


def _recruited(session, card_id):
    return session.game.table.cards_by_id[card_id] in session.game.table.battlefield.cards


def _in_combat(*terrains: L5RCard) -> EngineSession:
    """P1's ``a`` attacks P2's ``d`` at P2's first Province, 3F against 3F, with ``terrains`` in
    their owners' hands and P1's ``home`` left at home. Paused as the Combat Segment opens, with
    the Defender holding the first opportunity. P2 keeps a second Province, so taking the first
    does not end the game."""
    state = TableState.empty_two_seat()
    province_card(state, "def-prov0", seat=P2, index=0)
    province_card(state, "def-prov1", seat=P2, index=1)
    province_card(state, "atk-prov0", seat=P1, index=0)
    put_in_play(state, personality("a", owner=P1, force=3))
    put_in_play(state, personality("d", owner=P2, force=3))
    put_in_play(state, personality("home", owner=P1, force=3))
    for terrain in terrains:
        _in_hand(state, terrain)
    session = EngineSession.start(state, P1)
    end_phase(session)
    session.act(P1, DeclareAttack())
    session.submit(P1, DecisionResponse((assignment_token("a", 0),)))
    session.submit(P2, DecisionResponse((assignment_token("d", 0),)))
    session.submit(P1, DecisionResponse(("0",)))
    _pass_while(session, lambda s: s.game.attack.battle_segment is BattleSegment.ENGAGE)
    return session


def _pass_while(session: EngineSession, still: Callable[[EngineSession], bool]) -> None:
    """Pass with whichever seat holds the opportunity while ``still`` holds.

    Bounded, so a battle that fails to advance fails the test instead of hanging it.
    """
    for _ in range(20):
        if not still(session):
            return
        session.act(session.game.round.priority, Pass())
    raise AssertionError("the battle never advanced")


def _play_terrain(session: EngineSession, seat: PlayerId, card_id: str) -> None:
    session.act(seat, PlayStrategy(card_id))
    pay(session, seat)


def test_contentious_terrain_enters_play_at_the_battlefield_in_no_army():
    session = _in_combat(contentious_terrain("ct"))
    session.act(P2, Pass())

    _play_terrain(session, P1, "ct")

    game = session.game
    terrain = game.table.cards_by_id["ct"]
    assert location_of(game.table, terrain).battlefield == 0
    assert (P1, "ct") not in game.attack.battlefields[0].ever_present


def test_contentious_terrain_gives_only_its_players_personalities_there_1_force():
    session = _in_combat(contentious_terrain("ct"))
    session.act(P2, Pass())

    _play_terrain(session, P1, "ct")

    assert army_force(session.game, 0, P1) == 4
    assert army_force(session.game, 0, P2) == 3


def test_contentious_terrain_leaves_its_players_personalities_elsewhere_alone():
    session = _in_combat(contentious_terrain("ct"))
    session.act(P2, Pass())

    _play_terrain(session, P1, "ct")

    home = session.game.table.cards_by_id["home"]
    assert effective_stat(session.game, home, Stat.FORCE) == 3


def test_contentious_terrain_played_by_the_defender_strengthens_the_defending_army():
    session = _in_combat(contentious_terrain("ct", owner=P2))

    _play_terrain(session, P2, "ct")

    assert army_force(session.game, 0, P2) == 4
    assert army_force(session.game, 0, P1) == 3


def test_contentious_terrain_destroys_the_terrain_already_at_the_battlefield():
    session = _in_combat(contentious_terrain("first"), contentious_terrain("second", owner=P2))
    session.act(P2, Pass())
    _play_terrain(session, P1, "first")

    session.act(P2, PlayStrategy("second"))
    pay(session, P2)

    table = session.game.table
    assert "first" in _fate_discard(table, P1)
    assert location_of(table, table.cards_by_id["second"]).battlefield == 0


def test_contentious_terrain_asks_which_terrain_to_destroy_when_there_are_several():
    session = _in_combat(contentious_terrain("ct"))
    table = session.game.table
    for card_id in ("left", "right"):
        terrain_at(table, card_id, battlefield=0, owner=P2)

    session.act(P2, Pass())
    session.act(P1, PlayStrategy("ct"))
    pay(session, P1)
    assert isinstance(session.game.pending, ChooseCards)
    session.submit(P1, DecisionResponse(("right",)))

    assert location_of(table, table.cards_by_id["left"]).battlefield == 0
    assert "right" in _fate_discard(table, P2)
    assert location_of(table, table.cards_by_id["ct"]).battlefield == 0


def test_contentious_terrain_is_discarded_once_its_battle_ends():
    session = _in_combat(contentious_terrain("ct"))
    session.act(P2, Pass())
    _play_terrain(session, P1, "ct")

    _pass_while(session, lambda s: s.game.attack is not None and s.game.attack.current == 0)

    table = session.game.table
    assert "ct" in _fate_discard(table, P1)
    assert effective_stat(session.game, table.cards_by_id["a"], Stat.FORCE) == 3


def test_a_producers_yield_at_resolution_still_depends_on_what_it_pays_for():
    """Jade Works yields +2 only when paying for a Jade card. Payment resolution recomputes each
    producer's yield, so it has to recompute it against the same target the offer quoted."""
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
            id="jw",
            name="Jade Works",
            side=Side.DYNASTY,
            owner=P1,
            printed_id="jade_works",
            gold_production=2,
        ),
    )
    target = register(
        state,
        L5RCard.of(
            HoldingPrint,
            id="jade",
            name="Jade Thing",
            side=Side.DYNASTY,
            owner=P1,
            gold_cost=4,
            keywords=("Jade",),
        ),
    )
    target.turn_face_up()
    province = ProvinceZone(owner=P1)
    province.add(target)
    state.zones[ZoneKey(P1, ZoneRole.PROVINCE, 0)] = province

    session = EngineSession.start(state, P1)
    end_phase(session)
    end_phase(session)
    session.act(P1, Recruit("jade"))
    # The offer quotes 4, base 2 plus the Jade bonus, and bowing it alone must cover the cost.
    pay(session, P1)

    # 4 produced (2 base + 2 Jade bonus) less the 4 spent. Recomputing without the target would
    # yield 2 and leave the seat short, which asserting on the recruit alone would not notice.
    assert session.game.gold[P1] == 0
    assert _recruited(session, "jade")


def _rallying_cry(owner: PlayerId) -> L5RCard:
    return L5RCard.of(
        ActionPrint,
        id=f"cry-{owner.name}",
        name="Rallying Cry",
        printed_id="rallying_cry",
        side=Side.FATE,
        owner=owner,
        gold_cost=0,
    )


def _battle_resolved_holding_the_cry(*, held_by: PlayerId) -> EngineSession:
    """P1 attacks P2's first Province with ``a`` against ``d`` and wins it, paused in the Response
    Step after the resolution with Rallying Cry in ``held_by``'s hand. P2 keeps a second Province,
    so the win does not end the game."""
    state = TableState.empty_two_seat()
    province_card(state, "def-prov0", seat=P2, index=0)
    province_card(state, "def-prov1", seat=P2, index=1)
    province_card(state, "atk-prov0", seat=P1, index=0)
    put_in_play(state, personality("a", owner=P1, force=4))
    put_in_play(state, personality("d", owner=P2, force=2))
    _in_hand(state, _rallying_cry(held_by))
    session = EngineSession.start(state, P1)
    end_phase(session)
    session.act(P1, DeclareAttack())
    session.submit(P1, DecisionResponse((assignment_token("a", 0),)))
    session.submit(P2, DecisionResponse((assignment_token("d", 0),)))
    session.submit(P1, DecisionResponse(("0",)))
    while session.game.round.kind is RoundKind.BATTLE_SEGMENT:
        session.act(session.game.round.priority, Pass())
    return session


def test_rallying_cry_is_offered_in_the_response_step_after_the_resolution():
    session = _battle_resolved_holding_the_cry(held_by=P1)

    assert session.game.round.kind is RoundKind.RESPONSE
    assert PlayStrategy("cry-P1") in session.legal_actions(P1)


def test_rallying_cry_keeps_the_players_units_standing_through_after_resolution():
    session = _battle_resolved_holding_the_cry(held_by=P1)

    session.act(P1, PlayStrategy("cry-P1"))
    session.submit(P1, DecisionResponse(()))
    while session.game.round.kind is RoundKind.RESPONSE:
        session.act(session.game.round.priority, Pass())

    hero = session.game.table.cards_by_id["a"]
    assert not hero.bowed
    assert location_of(session.game.table, hero).is_home


def test_rallying_cry_is_not_offered_to_a_player_with_no_unit_at_the_battlefield():
    session = _battle_resolved_holding_the_cry(held_by=P2)

    # The Defender's unit was destroyed, so there is nothing of P2's at the battlefield to spare.
    assert PlayStrategy("cry-P2") not in session.legal_actions(P2)
