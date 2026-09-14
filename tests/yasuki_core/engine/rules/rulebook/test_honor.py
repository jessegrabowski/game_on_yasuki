import pytest

from yasuki_core.engine.players import PlayerId
from yasuki_core.engine.replay.game_log import replay
from yasuki_core.engine.rules.effects import GainHonor
from yasuki_core.engine.rules.vocabulary.game_events import CardDiscarded
from yasuki_core.engine.session import EngineSession
from yasuki_core.engine.rules.state import GameState
from yasuki_core.engine.rules.triggers import resolve_effects
from yasuki_core.engine.rules.turn import action_sequence
from yasuki_core.engine.rules.turn.structure import RESPONSE_TIMINGS, ActionRound, RoundKind
from yasuki_core.engine.rules.vocabulary.actions import ActivateAbility, KharmicDraw, Recruit
from yasuki_core.engine.rules.vocabulary.decisions import (
    ChooseHonorInterrupt,
    DecisionResponse,
    honor_interrupt_token,
)
from yasuki_core.engine.table import TableState, ZoneKey, ZoneRole
from yasuki_core.engine.zones import ProvinceZone
from yasuki_core.game_pieces.cards import L5RCard
from yasuki_core.game_pieces.constants import Side
from yasuki_core.game_pieces.prints import FatePrint, PersonalityPrint

from tests.yasuki_core.engine.builders import (
    dealt_table,
    end_phase,
    holding,
    pay,
    put_in_play,
    register,
    stronghold,
    two_seat_game,
)

P1, P2 = PlayerId.P1, PlayerId.P2
PERSONAL_HONOR = 3


def _honor_card(table: TableState, card_id: str, owner: PlayerId) -> L5RCard:
    card = L5RCard.of(
        FatePrint, id=card_id, name="Honor Fate", side=Side.FATE, owner=owner, keywords=("Honor",)
    )
    table.zones[ZoneKey(owner, ZoneRole.HAND)].add(register(table, card))
    return card


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


def _honor(session: EngineSession, seat: PlayerId) -> int:
    return session.game.table.seats[seat].honor


def _asked(session: EngineSession) -> PlayerId:
    pending = session.game.pending
    assert isinstance(pending, ChooseHonorInterrupt)
    return pending.seat


def test_the_opponent_is_offered_the_interrupt_and_the_gain_shrinks():
    session = _proclaim_session({P2: 1})
    pending = session.game.pending
    assert isinstance(pending, ChooseHonorInterrupt)
    assert (pending.seat, pending.honor_seat, pending.amount) == (P2, P1, PERSONAL_HONOR)

    session.submit(P2, DecisionResponse((honor_interrupt_token("P2-honor0", -1),)))

    assert _honor(session, P1) == PERSONAL_HONOR - 1
    assert session.game.pending is None
    discard = session.game.table.zones[ZoneKey(P2, ZoneRole.FATE_DISCARD)]
    assert [card.id for card in discard.cards] == ["P2-honor0"]


def test_passing_leaves_the_gain_whole():
    session = _proclaim_session({P2: 1})

    session.submit(P2, DecisionResponse())

    assert _honor(session, P1) == PERSONAL_HONOR
    assert session.game.pending is None


def test_a_seat_with_no_honor_card_is_not_asked():
    session = _proclaim_session({})

    assert session.game.pending is None
    assert _honor(session, P1) == PERSONAL_HONOR


def test_both_seats_may_interrupt_the_same_change_and_the_deltas_accumulate():
    session = _proclaim_session({P1: 1, P2: 1})
    assert _asked(session) is P1  # the active player is asked first

    session.submit(P1, DecisionResponse((honor_interrupt_token("P1-honor0", -1),)))
    assert _asked(session) is P2
    session.submit(P2, DecisionResponse((honor_interrupt_token("P2-honor0", -1),)))

    assert _honor(session, P1) == PERSONAL_HONOR - 2


def test_a_seat_is_asked_once_per_change():
    session = _proclaim_session({P2: 2})

    session.submit(P2, DecisionResponse((honor_interrupt_token("P2-honor0", 1),)))

    assert session.game.pending is None
    assert _honor(session, P1) == PERSONAL_HONOR + 1


def test_the_interrupted_game_replays_to_the_same_board():
    session = _proclaim_session({P2: 1})
    session.submit(P2, DecisionResponse((honor_interrupt_token("P2-honor0", -1),)))

    rebuilt = replay(session.log)

    assert rebuilt.table.seats[P1].honor == _honor(session, P1)
    assert rebuilt.pending is None and not rebuilt.stack


def _inside_an_action(honor_cards: int = 1) -> GameState:
    """A bare game mid-action, with P2 holding ``honor_cards`` Honor cards."""
    game = two_seat_game()
    for index in range(honor_cards):
        _honor_card(game.table, f"P2-honor{index}", P2)
    game.action = KharmicDraw("the-interrupted-action")
    return game


def test_a_seat_may_interrupt_once_per_action():
    game = _inside_an_action(honor_cards=2)

    resolve_effects(game, [GainHonor(P1, 2), GainHonor(P1, 2)])
    action_sequence.submit(game, DecisionResponse((honor_interrupt_token("P2-honor0", -1),)))

    assert game.pending is None
    assert game.table.seats[P1].honor == 1 + 2


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


def test_the_interrupting_discard_is_announced_to_the_board(reacting):
    session = _proclaim_session({P2: 1}, watcher="discard_probe")
    seen: list[str] = []
    reacting(CardDiscarded, "discard_probe", lambda ctx: seen.append(ctx.event.card_id) or [])

    session.submit(P2, DecisionResponse((honor_interrupt_token("P2-honor0", -1),)))

    assert seen == ["P2-honor0"]


def test_an_abilitys_gain_is_interruptible():
    table = dealt_table(hand=0)
    put_in_play(table, holding("P1-garden", printed_id="poorly_placed_garden"))
    _honor_card(table, "P2-honor0", P2)
    session = EngineSession.start(table, P1, seed=4)

    session.act(P1, ActivateAbility("P1-garden"))

    assert _asked(session) is P2
    session.submit(P2, DecisionResponse((honor_interrupt_token("P2-honor0", 1),)))
    assert _honor(session, P1) == 3


def test_neither_seat_can_back_out_while_the_interrupt_is_open():
    session = _proclaim_session({P2: 1})

    assert not session.abort(P1)
    with pytest.raises(ValueError, match="cannot be canceled"):
        session.cancel(P2)


def test_an_answer_naming_a_card_no_longer_in_hand_is_refused():
    session = _proclaim_session({P2: 1})
    hand = session.game.table.zones[ZoneKey(P2, ZoneRole.HAND)]
    hand.remove(hand.cards[0])

    with pytest.raises(RuntimeError, match="no longer an Honor card"):
        session.submit(P2, DecisionResponse((honor_interrupt_token("P2-honor0", -1),)))
