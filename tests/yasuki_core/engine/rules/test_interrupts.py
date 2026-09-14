import pytest

from yasuki_core.engine.players import PlayerId
from yasuki_core.engine.replay.game_log import replay
from yasuki_core.engine.rules.abilities.model import Ability
from yasuki_core.engine.rules.abilities.registry import register_ability
from yasuki_core.engine.rules.board.queries import attack_targets
from yasuki_core.engine.rules.effects import Fear, GainHonor
from yasuki_core.engine.rules.state import GameState
from yasuki_core.engine.rules.triggers import resolve_effects
from yasuki_core.engine.rules.turn import action_sequence, sequence
from yasuki_core.engine.rules.turn.structure import (
    END_OF_TURN,
    RESPONSE_TIMINGS,
    ActionRound,
    RoundKind,
)
from yasuki_core.engine.rules.vocabulary.actions import (
    ActionTiming,
    ActivateAbility,
    DeclareAttack,
    KharmicDraw,
    Pass,
    Recruit,
)
from yasuki_core.engine.rules.vocabulary.decisions import (
    ChooseBattlefield,
    ChooseInterrupt,
    DecisionResponse,
    interrupt_token,
)
from yasuki_core.engine.rules.vocabulary.game_events import CardDiscarded
from yasuki_core.engine.rules.vocabulary.segments import BattleSegment
from yasuki_core.engine.session import EngineSession
from yasuki_core.engine.table import TableState, ZoneKey, ZoneRole
from yasuki_core.engine.zones import ProvinceZone
from yasuki_core.game_pieces.cards import L5RCard
from yasuki_core.game_pieces.constants import Side
from yasuki_core.game_pieces.prints import ActionPrint, FatePrint, PersonalityPrint

from tests.yasuki_core.engine.builders import (
    dealt_table,
    end_phase,
    holding,
    pay,
    personality,
    province_card,
    put_in_play,
    register,
    stronghold,
    two_seat_game,
)

P1, P2 = PlayerId.P1, PlayerId.P2
PERSONAL_HONOR = 3
FEAR = 2

register_ability(
    "fear_probe",
    Ability(
        timings=(ActionTiming.BATTLE,),
        label="Battle: Fear",
        cost=lambda game, source: [],
        targets=lambda game, source: attack_targets(game, source),
        effects=lambda game, source, target: [Fear(FEAR, target.id, source.owner)],
    ),
)


def _keyword_card(table: TableState, card_id: str, owner: PlayerId, keyword: str) -> L5RCard:
    card = L5RCard.of(
        FatePrint,
        id=card_id,
        name=f"{keyword} Fate",
        side=Side.FATE,
        owner=owner,
        keywords=(keyword,),
    )
    table.zones[ZoneKey(owner, ZoneRole.HAND)].add(register(table, card))
    return card


def _honor_card(table: TableState, card_id: str, owner: PlayerId) -> L5RCard:
    return _keyword_card(table, card_id, owner, "Honor")


def _courage_card(table: TableState, card_id: str, owner: PlayerId) -> L5RCard:
    return _keyword_card(table, card_id, owner, "Courage")


def _strategy(table: TableState, card_id: str, printed_id: str, owner: PlayerId) -> L5RCard:
    card = L5RCard.of(
        ActionPrint,
        id=card_id,
        name=card_id,
        printed_id=printed_id,
        side=Side.FATE,
        owner=owner,
        gold_cost=0,
    )
    table.zones[ZoneKey(owner, ZoneRole.HAND)].add(register(table, card))
    return card


def _asked(session: EngineSession) -> PlayerId:
    pending = session.game.pending
    assert isinstance(pending, ChooseInterrupt)
    return pending.seat


def _honor(session: EngineSession, seat: PlayerId) -> int:
    return session.game.table.seats[seat].honor


# --- the Honor Interrupt, against a Proclaimed recruit ---


def _proclaim_session(
    honor_cards: dict[PlayerId, int], *, watcher: str | None = None
) -> EngineSession:
    """A session that has just paid for a Proclaimed recruit worth ``PERSONAL_HONOR``, with each
    seat holding the number of Honor cards ``honor_cards`` gives it, and a Holding printed
    ``watcher`` in play for P1 when one is named."""
    table = dealt_table(hand=0)
    put_in_play(table, stronghold(P1, gold_production=8, clan="Crab"))
    if watcher is not None:
        put_in_play(table, holding("P1-watcher", printed_id=watcher))
    samurai = L5RCard.of(
        PersonalityPrint,
        id="P1-samurai",
        name="P1-samurai",
        side=Side.DYNASTY,
        owner=P1,
        force=2,
        chi=2,
        clan="Crab",
        personal_honor=PERSONAL_HONOR,
        gold_cost=0,
        honor_requirement=0,
    )
    samurai.turn_face_up()
    province = ProvinceZone(owner=P1)
    province.add(register(table, samurai))
    table.zones[ZoneKey(P1, ZoneRole.PROVINCE, 0)] = province
    for seat, count in honor_cards.items():
        for index in range(count):
            _honor_card(table, f"{seat.name}-honor{index}", seat)
    session = EngineSession.start(table, P1, seed=4)
    end_phase(session)
    end_phase(session)
    proclaim = next(
        action
        for action in session.legal_actions(P1)
        if isinstance(action, Recruit) and action.proclaim
    )
    session.act(P1, proclaim)
    pay(session, P1)
    return session


def test_the_opponent_is_offered_the_honor_interrupt_and_the_gain_shrinks():
    session = _proclaim_session({P2: 1})
    pending = session.game.pending
    assert isinstance(pending, ChooseInterrupt)
    assert (pending.seat, pending.effect) == (P2, GainHonor(P1, PERSONAL_HONOR))

    session.submit(P2, DecisionResponse((interrupt_token("P2-honor0", -1),)))

    assert _honor(session, P1) == PERSONAL_HONOR - 1
    assert session.game.pending is None
    discard = session.game.table.zones[ZoneKey(P2, ZoneRole.FATE_DISCARD)]
    assert [card.id for card in discard.cards] == ["P2-honor0"]


def test_passing_leaves_the_gain_whole():
    session = _proclaim_session({P2: 1})

    session.submit(P2, DecisionResponse())

    assert _honor(session, P1) == PERSONAL_HONOR
    assert session.game.pending is None


def test_a_seat_with_nothing_to_interrupt_with_is_not_asked():
    session = _proclaim_session({})

    assert session.game.pending is None
    assert _honor(session, P1) == PERSONAL_HONOR


def test_both_seats_may_interrupt_the_same_change_and_the_deltas_accumulate():
    session = _proclaim_session({P1: 1, P2: 1})
    assert _asked(session) is P1  # the active player is asked first

    session.submit(P1, DecisionResponse((interrupt_token("P1-honor0", -1),)))
    assert _asked(session) is P2
    session.submit(P2, DecisionResponse((interrupt_token("P2-honor0", -1),)))

    assert _honor(session, P1) == PERSONAL_HONOR - 2


def test_the_honor_interrupt_is_once_per_action_for_a_seat():
    session = _proclaim_session({P2: 2})

    session.submit(P2, DecisionResponse((interrupt_token("P2-honor0", 1),)))

    assert session.game.pending is None
    assert _honor(session, P1) == PERSONAL_HONOR + 1


def test_the_interrupting_discard_is_announced_to_the_board(reacting):
    session = _proclaim_session({P2: 1}, watcher="discard_probe")
    seen: list[str] = []
    reacting(CardDiscarded, "discard_probe", lambda ctx: seen.append(ctx.event.card_id) or [])

    session.submit(P2, DecisionResponse((interrupt_token("P2-honor0", -1),)))

    assert seen == ["P2-honor0"]


def test_an_abilitys_gain_is_interruptible():
    table = dealt_table(hand=0)
    put_in_play(table, holding("P1-garden", printed_id="poorly_placed_garden"))
    _honor_card(table, "P2-honor0", P2)
    session = EngineSession.start(table, P1, seed=4)

    session.act(P1, ActivateAbility("P1-garden"))

    assert _asked(session) is P2
    session.submit(P2, DecisionResponse((interrupt_token("P2-honor0", 1),)))
    assert _honor(session, P1) == 3


def test_neither_seat_can_back_out_while_the_interrupt_is_open():
    session = _proclaim_session({P2: 1})

    assert not session.abort(P1)
    with pytest.raises(ValueError, match="cannot be canceled"):
        session.cancel(P2)


def test_the_honor_game_replays_to_the_same_board():
    session = _proclaim_session({P2: 1})
    session.submit(P2, DecisionResponse((interrupt_token("P2-honor0", -1),)))

    rebuilt = replay(session.log)

    assert rebuilt.table.seats[P1].honor == _honor(session, P1)
    assert rebuilt.pending is None and not rebuilt.stack


def test_an_answer_naming_a_card_no_longer_in_hand_is_refused():
    session = _proclaim_session({P2: 1})
    hand = session.game.table.zones[ZoneKey(P2, ZoneRole.HAND)]
    hand.remove(hand.cards[0])

    with pytest.raises(RuntimeError, match="no longer"):
        session.submit(P2, DecisionResponse((interrupt_token("P2-honor0", -1),)))


# --- the Courage Interrupt, against a Fear in the Combat Segment ---

ATTACKER, DEFENDER = P1, P2


def _fear_announced(
    courage_cards: dict[PlayerId, int], *, strategies: tuple[tuple[str, str, PlayerId], ...] = ()
) -> EngineSession:
    """A session in which the Attacker has just aimed Fear ``FEAR`` at the Defender's 2F guard in
    the Combat Segment, with each seat holding the Courage cards ``courage_cards`` gives it and
    the ``(card_id, printed_id, owner)`` Strategies ``strategies`` names."""
    state = TableState.empty_two_seat()
    province_card(state, "atk-prov0", seat=ATTACKER, index=0)
    province_card(state, "def-prov0", seat=DEFENDER, index=0)
    put_in_play(state, personality("raider", owner=ATTACKER, printed_id="fear_probe", force=3))
    put_in_play(state, personality("guard", owner=DEFENDER, force=2))
    for seat, count in courage_cards.items():
        for index in range(count):
            _courage_card(state, f"{seat.name}-courage{index}", seat)
    for card_id, printed_id, owner in strategies:
        _strategy(state, card_id, printed_id, owner)
    session = EngineSession.start(state, ATTACKER)
    end_phase(session)
    session.act(ATTACKER, DeclareAttack())
    session.submit(ATTACKER, DecisionResponse(("raider@0",)))
    session.submit(DEFENDER, DecisionResponse(("guard@0",)))
    choice = session.game.pending
    assert isinstance(choice, ChooseBattlefield)
    session.submit(choice.seat, DecisionResponse(("0",)))
    attack = session.game.attack
    assert attack is not None
    while attack.battle_segment is not BattleSegment.COMBAT:
        session.act(session.game.round.priority, Pass())
    session.act(DEFENDER, Pass())  # the segment opens on the Defender
    session.act(ATTACKER, ActivateAbility("raider"))
    session.submit(ATTACKER, DecisionResponse(("guard",)))
    return session


def _guard_bowed(session: EngineSession) -> bool:
    return session.game.table.cards_by_id["guard"].bowed


def test_the_defender_is_offered_the_courage_interrupt_and_a_reduction_saves_the_target():
    session = _fear_announced({DEFENDER: 1})
    assert _asked(session) is DEFENDER

    session.submit(DEFENDER, DecisionResponse((interrupt_token("P2-courage0", -2),)))

    assert not _guard_bowed(session)
    assert session.game.pending is None


def test_passing_lets_the_fear_resolve_at_full_strength():
    session = _fear_announced({DEFENDER: 1})

    session.submit(DEFENDER, DecisionResponse())

    assert _guard_bowed(session)


def test_a_seat_that_interrupted_with_courage_is_asked_again_until_it_passes():
    session = _fear_announced({DEFENDER: 2})

    session.submit(DEFENDER, DecisionResponse((interrupt_token("P2-courage0", -2),)))
    assert _asked(session) is DEFENDER
    session.submit(DEFENDER, DecisionResponse((interrupt_token("P2-courage1", 2),)))

    assert session.game.pending is None  # no Courage card left to offer
    assert _guard_bowed(session)  # -2 then +2 leaves Fear 2 against a 2F guard


def test_the_attacker_is_asked_first_and_may_raise_its_own_fear():
    session = _fear_announced({ATTACKER: 1, DEFENDER: 1})
    assert _asked(session) is ATTACKER

    session.submit(ATTACKER, DecisionResponse((interrupt_token("P1-courage0", 2),)))
    assert _asked(session) is DEFENDER
    session.submit(DEFENDER, DecisionResponse((interrupt_token("P2-courage0", -2),)))

    assert _guard_bowed(session)  # 2 + 2 - 2 = 2 reaches the 2F guard


def test_the_courage_game_replays_to_the_same_board():
    session = _fear_announced({DEFENDER: 1})
    session.submit(DEFENDER, DecisionResponse((interrupt_token("P2-courage0", -2),)))

    rebuilt = replay(session.log)

    assert rebuilt.table.cards_by_id["guard"].bowed == _guard_bowed(session)
    assert rebuilt.pending is None and not rebuilt.stack


# --- when the step does not open ---


def _inside_an_action() -> GameState:
    game = two_seat_game()
    _honor_card(game.table, "P2-honor0", P2)
    game.action = KharmicDraw("the-interrupted-action")
    return game


def test_a_change_outside_an_action_asks_nobody():
    game = _inside_an_action()
    game.action = None

    resolve_effects(game, [GainHonor(P1, 2)])

    assert game.pending is None
    assert game.table.seats[P1].honor == 2


def test_a_change_during_a_response_step_asks_nobody():
    game = _inside_an_action()
    game.round = ActionRound(timings=RESPONSE_TIMINGS, priority=P1, kind=RoundKind.RESPONSE)

    resolve_effects(game, [GainHonor(P1, 2)])

    assert game.pending is None


def test_a_change_that_is_not_interruptible_asks_nobody():
    game = _inside_an_action()

    resolve_effects(game, [GainHonor(P1, 2, interruptible=False)])

    assert game.pending is None


def test_a_delayed_change_at_the_end_of_the_turn_asks_nobody():
    game = GameState.start(dealt_table(hand=0), P1)
    _honor_card(game.table, "P2-honor0", P2)
    game.action = KharmicDraw("the-turns-last-action")
    game.delayed.append((END_OF_TURN, GainHonor(P1, -2)))

    for _ in range(3):
        sequence.advance(game)

    assert game.pending is None
    assert game.table.seats[P1].honor == -2


def test_a_seat_may_take_the_honor_interrupt_once_per_action():
    game = _inside_an_action()
    _honor_card(game.table, "P2-honor1", P2)

    resolve_effects(game, [GainHonor(P1, 2), GainHonor(P1, 2)])
    action_sequence.submit(game, DecisionResponse((interrupt_token("P2-honor0", -1),)))

    assert game.pending is None
    assert game.table.seats[P1].honor == 1 + 2
