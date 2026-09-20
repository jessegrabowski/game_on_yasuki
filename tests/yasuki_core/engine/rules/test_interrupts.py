from dataclasses import replace

import pytest

from yasuki_core.engine.players import PlayerId
from yasuki_core.engine.replay.game_log import replay
from yasuki_core.engine.rules import interrupts, legality
from yasuki_core.engine.rules.abilities.activation import ResolveAbility, defer_ability
from yasuki_core.engine.rules.abilities.model import (
    Ability,
    CardLocation,
    Interrupt,
    Interruption,
    itself,
)
from yasuki_core.engine.rules.abilities.registry import (
    ability_for,
    register_ability,
    register_interrupt,
)
from yasuki_core.engine.rules.board.queries import attack_targets, owned_personalities
from yasuki_core.engine.rules.effects import (
    Bow,
    Choose,
    Destroy,
    Discard,
    Effect,
    Fear,
    GainHonor,
    Negated,
    Straighten,
    Then,
)
from yasuki_core.engine.rules.state import GameState
from yasuki_core.engine.rules.triggers import (
    choice_resolver,
    resolve_action_effects,
    resolve_effects,
)
from yasuki_core.engine.rules.turn import action_sequence, sequence
from yasuki_core.engine.rules.turn.structure import (
    END_OF_TURN,
    INTERRUPT_TIMINGS,
    RESPONSE_TIMINGS,
    ActionRound,
    RoundKind,
)
from yasuki_core.engine.rules.vocabulary.actions import (
    DiscardToInterrupt,
    PlayInterrupt,
    ActionTiming,
    ActivateAbility,
    DeclareAttack,
    KharmicDraw,
    Pass,
    Recruit,
)
from yasuki_core.engine.rules.vocabulary.decisions import (
    ChooseBattlefield,
    ChooseCards,
    ChooseInterruptAdjustment,
    ChooseInterruptEffect,
    ChooseInterruptTarget,
    ChoosePayment,
    DecisionResponse,
)
from yasuki_core.engine.rules.vocabulary.game_events import CardDiscarded, Destroyed, Straightened
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


register_ability(
    "fear_then_honor_probe",
    Ability(
        timings=(ActionTiming.BATTLE,),
        label="Battle: Fear, then gain Honor",
        cost=lambda game, source: [],
        targets=lambda game, source: attack_targets(game, source),
        effects=lambda game, source, target: [
            Fear(FEAR, target.id, source.owner),
            GainHonor(source.owner, 1),
        ],
    ),
)


register_ability(
    "honor_cost_probe",
    Ability(
        timings=(ActionTiming.OPEN,),
        label="Open: lose 1 Honor to gain 2 Honor",
        cost=lambda game, source: [GainHonor(source.owner, -1)],
        targets=itself,
        effects=lambda game, source, target: [GainHonor(source.owner, 2)],
        hits_every_target=True,
    ),
)


register_ability(
    "two_gains_probe",
    Ability(
        timings=(ActionTiming.OPEN,),
        label="Open: gain 2 Honor, then 3 Honor",
        cost=lambda game, source: [],
        targets=itself,
        effects=lambda game, source, target: [
            GainHonor(source.owner, 2),
            GainHonor(source.owner, 3),
        ],
        hits_every_target=True,
    ),
)


register_ability(
    "board_reading_probe",
    Ability(
        timings=(ActionTiming.OPEN,),
        label="Open: gain 1 Honor, then 1 more, or 5 once above zero",
        cost=lambda game, source: [],
        targets=itself,
        effects=lambda game, source, target: [
            GainHonor(source.owner, 1),
            GainHonor(source.owner, 1 if game.table.seats[source.owner].honor == 0 else 5),
        ],
    ),
)


register_ability(
    "unstoppable_probe",
    Ability(
        timings=(ActionTiming.OPEN,),
        label="Unstoppable Open: gain 2 Honor",
        cost=lambda game, source: [],
        targets=itself,
        effects=lambda game, source, target: [GainHonor(source.owner, 2)],
        hits_every_target=True,
        unstoppable=True,
    ),
)


register_interrupt(
    "negate_action_probe",
    Interrupt(
        label="Interrupt: negate the action's effects",
        answers=Effect,
        interrupt=lambda game, source, effect: Interruption(Negated(effect)),
        answers_every=True,
    ),
)


register_interrupt(
    "province_event_probe",
    Interrupt(
        label="Interrupt: discard this Event from play to gain 1 Honor as the action bows a card",
        answers=Bow,
        interrupt=lambda game, source, effect: Interruption(
            effect, effects=(GainHonor(source.owner, 1),)
        ),
        located_at=(CardLocation.PROVINCE,),
        cost=lambda game, source: [Discard(source.id, source.owner)],
    ),
)


register_interrupt(
    "interrupt_probe",
    Interrupt(
        label="Interrupt: gain 1 Honor, leave the effect alone",
        answers=Fear,
        interrupt=lambda game, source, effect: Interruption(
            effect, effects=(GainHonor(source.owner, 1),)
        ),
    ),
)


register_interrupt(
    "negate_fear_probe",
    Interrupt(
        label="Interrupt: negate the action's Fear",
        answers=Fear,
        interrupt=lambda game, source, effect: Interruption(Negated(effect)),
    ),
)


register_interrupt(
    "bow_interrupt_probe",
    Interrupt(
        label="Interrupt: gain 1 Honor as the action bows a card",
        answers=Bow,
        interrupt=lambda game, source, effect: Interruption(
            effect, effects=(GainHonor(source.owner, 1),)
        ),
    ),
)


register_ability(
    "bow_then_destroy_probe",
    Ability(
        timings=(ActionTiming.OPEN,),
        label="Open: bow a target enemy unbowed Personality, then destroy it",
        cost=lambda game, source: [],
        targets=lambda game, source: [
            card.id
            for seat in game.table.seats
            if seat is not source.owner
            for card in owned_personalities(game, seat)
            if not card.bowed
        ],
        effects=lambda game, source, target: [
            Bow(target.id),
            Then((Destroy(target.id, source.owner),)),
        ],
    ),
)


register_interrupt(
    "substitute_probe",
    Interrupt(
        label="Interrupt: the action targets your other Personality instead, if legal",
        answers=ResolveAbility,
        interrupt=lambda game, source, targeting, target: Interruption(
            replace(targeting, target_id=target.id, effects=None)
        ),
        targets=lambda game, source, targeting: interrupts.legal_substitutes(
            game, targeting, [card.id for card in owned_personalities(game, source.owner)]
        ),
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


def _strategy(
    table: TableState, card_id: str, printed_id: str, owner: PlayerId, gold_cost: int = 0
) -> L5RCard:
    card = L5RCard.of(
        ActionPrint,
        id=card_id,
        name=card_id,
        printed_id=printed_id,
        side=Side.FATE,
        owner=owner,
        gold_cost=gold_cost,
    )
    table.zones[ZoneKey(owner, ZoneRole.HAND)].add(register(table, card))
    return card


HONOR_UP, HONOR_DOWN = ("honor", "Increase by 1"), ("honor", "Reduce by 1")
COURAGE_UP, COURAGE_DOWN = ("courage", "+2 strength"), ("courage", "-2 strength")


def _discard_to_interrupt(
    session: EngineSession, seat: PlayerId, card_id: str, adjustment: tuple[str, str]
) -> None:
    """Take a rulebook Interrupt: the action naming the card, then the adjustment it asks for."""
    key, wording = adjustment
    session.act(seat, DiscardToInterrupt(card_id, key))
    session.submit(seat, DecisionResponse((wording,)))


def _discard_to_interrupt_in(game: GameState, card_id: str, adjustment: tuple[str, str]) -> None:
    key, wording = adjustment
    action_sequence.perform(game, DiscardToInterrupt(card_id, key))
    action_sequence.submit(game, DecisionResponse((wording,)))


def _asked(session: EngineSession) -> PlayerId:
    """The seat the open Interrupt step is offering to."""
    return _asked_seat(session.game)


def _honor(session: EngineSession, seat: PlayerId) -> int:
    return session.game.table.seats[seat].honor


# --- the Honor Interrupt, against a Proclaimed recruit ---


def _proclaim_session(
    honor_cards: dict[PlayerId, int], *, watcher: str | None = None
) -> EngineSession:
    """A session that has just paid for a Proclaimed recruit worth ``PERSONAL_HONOR``."""
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
    assert _asked(session) is P2
    assert session.legal_actions(P2) == [Pass(), DiscardToInterrupt("P2-honor0", "honor")]
    assert session.project(P2).interrupting == "the Recruit of P1-samurai"

    _discard_to_interrupt(session, P2, "P2-honor0", HONOR_DOWN)

    assert _honor(session, P1) == PERSONAL_HONOR - 1
    assert session.game.pending is None
    discard = session.game.table.zones[ZoneKey(P2, ZoneRole.FATE_DISCARD)]
    assert [card.id for card in discard.cards] == ["P2-honor0"]


def test_naming_the_card_asks_for_the_adjustment_before_anything_moves():
    session = _proclaim_session({P2: 1})

    session.act(P2, DiscardToInterrupt("P2-honor0", "honor"))

    pending = session.game.pending
    assert isinstance(pending, ChooseInterruptAdjustment)
    assert (pending.seat, pending.candidates) == (P2, ("Increase by 1", "Reduce by 1"))
    assert pending.prompt() == f"P1 gains {PERSONAL_HONOR} honor. Increase or reduce it by 1?"
    assert session.game.table.zones[ZoneKey(P2, ZoneRole.FATE_DISCARD)].cards == []


def test_backing_out_of_the_adjustment_reopens_the_offer():
    # Naming the card moved nothing, so the seat may change its mind up to the adjustment, and
    # only that step comes back: the interrupted action stays where it was.
    session = _proclaim_session({P2: 1})
    session.act(P2, DiscardToInterrupt("P2-honor0", "honor"))

    session.cancel(P2)

    assert session.game.pending is None and _asked(session) is P2
    assert DiscardToInterrupt("P2-honor0", "honor") in session.legal_actions(P2)
    assert _honor(session, P1) == 0
    _discard_to_interrupt(session, P2, "P2-honor0", HONOR_DOWN)
    assert _honor(session, P1) == PERSONAL_HONOR - 1


def test_passing_leaves_the_gain_whole():
    session = _proclaim_session({P2: 1})

    session.act(P2, Pass())

    assert _honor(session, P1) == PERSONAL_HONOR
    assert session.game.pending is None


def test_a_seat_with_nothing_to_interrupt_with_is_not_asked():
    session = _proclaim_session({})

    assert session.game.pending is None
    assert _honor(session, P1) == PERSONAL_HONOR


def test_both_seats_may_interrupt_the_same_change_and_the_deltas_accumulate():
    session = _proclaim_session({P1: 1, P2: 1})
    assert _asked(session) is P1  # the active player is asked first

    _discard_to_interrupt(session, P1, "P1-honor0", HONOR_DOWN)
    assert _asked(session) is P2
    _discard_to_interrupt(session, P2, "P2-honor0", HONOR_DOWN)

    assert _honor(session, P1) == PERSONAL_HONOR - 2


def test_the_honor_interrupt_is_once_per_action_for_a_seat():
    session = _proclaim_session({P2: 2})

    _discard_to_interrupt(session, P2, "P2-honor0", HONOR_UP)

    assert session.game.pending is None
    assert _honor(session, P1) == PERSONAL_HONOR + 1


def test_the_interrupting_discard_is_announced_to_the_board(reacting):
    session = _proclaim_session({P2: 1}, watcher="discard_probe")
    seen: list[str] = []
    reacting(CardDiscarded, "discard_probe", lambda ctx: seen.append(ctx.event.card_id) or [])

    _discard_to_interrupt(session, P2, "P2-honor0", HONOR_DOWN)

    assert seen == ["P2-honor0"]


def test_an_abilitys_gain_is_interruptible():
    table = dealt_table(hand=0)
    put_in_play(table, holding("P1-garden", printed_id="poorly_placed_garden"))
    _honor_card(table, "P2-honor0", P2)
    session = EngineSession.start(table, P1, seed=4)

    session.act(P1, ActivateAbility("P1-garden"))

    assert _asked(session) is P2
    _discard_to_interrupt(session, P2, "P2-honor0", HONOR_UP)
    assert _honor(session, P1) == 3


def test_neither_seat_can_back_out_while_the_interrupt_step_is_open():
    # The step is a round with no decision pending: there is nothing to cancel, and the action
    # held beneath it is not the interrupting seat's to unwind.
    session = _proclaim_session({P2: 1})

    assert not session.can_cancel(P1) and not session.can_cancel(P2)
    assert not session.abort(P1) and not session.abort(P2)


def test_the_honor_game_replays_to_the_same_board():
    session = _proclaim_session({P2: 1})
    _discard_to_interrupt(session, P2, "P2-honor0", HONOR_DOWN)

    rebuilt = replay(session.log)

    assert rebuilt.table.seats[P1].honor == _honor(session, P1)
    assert rebuilt.pending is None and not rebuilt.stack


def test_an_answer_naming_a_card_no_longer_in_hand_is_refused():
    session = _proclaim_session({P2: 1})
    hand = session.game.table.zones[ZoneKey(P2, ZoneRole.HAND)]
    hand.remove(hand.cards[0])

    with pytest.raises(ValueError, match="not legal"):
        _discard_to_interrupt(session, P2, "P2-honor0", HONOR_DOWN)


# --- the Courage Interrupt, against a Fear in the Combat Segment ---

ATTACKER, DEFENDER = P1, P2


def _fear_announced(
    courage_cards: dict[PlayerId, int],
    *,
    strategies: tuple[tuple[str, str, PlayerId], ...] = (),
    probe: str = "fear_probe",
    watcher: str | None = None,
) -> EngineSession:
    """A session in which the Attacker has just aimed Fear ``FEAR`` at the Defender's 2F guard in
    the Combat Segment. ``strategies`` are ``(card_id, printed_id, owner)`` triples."""
    state = TableState.empty_two_seat()
    province_card(state, "atk-prov0", seat=ATTACKER, index=0)
    province_card(state, "def-prov0", seat=DEFENDER, index=0)
    if watcher is not None:
        put_in_play(state, holding("atk-watcher", printed_id=watcher))
    put_in_play(state, personality("raider", owner=ATTACKER, printed_id=probe, force=3))
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

    _discard_to_interrupt(session, DEFENDER, "P2-courage0", COURAGE_DOWN)

    assert not _guard_bowed(session)
    assert session.game.pending is None


def test_passing_lets_the_fear_resolve_at_full_strength():
    session = _fear_announced({DEFENDER: 1})

    session.act(DEFENDER, Pass())

    assert _guard_bowed(session)


def test_a_seat_that_interrupted_with_courage_is_asked_again_until_it_passes():
    session = _fear_announced({DEFENDER: 2})

    _discard_to_interrupt(session, DEFENDER, "P2-courage0", COURAGE_DOWN)
    assert _asked(session) is DEFENDER
    _discard_to_interrupt(session, DEFENDER, "P2-courage1", COURAGE_UP)

    assert session.game.pending is None  # no Courage card left to offer
    assert _guard_bowed(session)  # -2 then +2 leaves Fear 2 against a 2F guard


def test_the_attacker_is_asked_first_and_may_raise_its_own_fear():
    session = _fear_announced({ATTACKER: 1, DEFENDER: 1})
    assert _asked(session) is ATTACKER

    _discard_to_interrupt(session, ATTACKER, "P1-courage0", COURAGE_UP)
    assert _asked(session) is DEFENDER
    _discard_to_interrupt(session, DEFENDER, "P2-courage0", COURAGE_DOWN)

    assert _guard_bowed(session)  # 2 + 2 - 2 = 2 reaches the 2F guard


def test_a_step_with_a_pending_adjustment_replays_to_the_same_board():
    # The first Courage discard is bound to the Fear and not yet applied when the window reopens
    # for the second, so the modification itself has to survive a replay.
    session = _fear_announced({DEFENDER: 2})
    _discard_to_interrupt(session, DEFENDER, "P2-courage0", COURAGE_DOWN)
    assert _asked(session) is DEFENDER
    assert session.game.modifications

    assert replay(session.log) == session.game


def test_the_courage_game_replays_to_the_same_board():
    session = _fear_announced({DEFENDER: 1})
    _discard_to_interrupt(session, DEFENDER, "P2-courage0", COURAGE_DOWN)

    rebuilt = replay(session.log)

    assert rebuilt.table.cards_by_id["guard"].bowed == _guard_bowed(session)
    assert rebuilt.pending is None and not rebuilt.stack


OKURA = ("okura", "okura_is_released", DEFENDER)
NEGATOR = ("negator", "negate_fear_probe", DEFENDER)


def test_a_negated_effect_resolves_as_nothing_and_the_action_goes_on():
    session = _fear_announced({}, strategies=(NEGATOR,), probe="fear_then_honor_probe")

    session.act(DEFENDER, PlayInterrupt("negator"))
    pay(session, DEFENDER)

    assert not _guard_bowed(session)
    assert session.game.pending is None
    assert _event_names(session) == ["CardDiscarded", "HonorChanged"]


def test_a_negated_attack_leaves_its_outcome_unreached():
    # The Fear's Bow arrives as the attack's follow-on effect, so negating the Fear negates the
    # comparison and no Bow is ever raised for anyone to answer.
    session = _fear_announced({ATTACKER: 1, DEFENDER: 1}, strategies=(NEGATOR,))
    session.act(ATTACKER, Pass())

    session.act(DEFENDER, PlayInterrupt("negator"))
    pay(session, DEFENDER)

    assert not _guard_bowed(session)
    assert session.game.pending is None
    assert "HonorChanged" not in _event_names(session)


def _event_names(session: EngineSession) -> list[str]:
    return [type(event).__name__ for event in session.game.action_events]


def test_a_rulebook_discard_rejoins_the_cascade_where_the_fear_stood():
    session = _fear_announced({DEFENDER: 1}, probe="fear_then_honor_probe")

    _discard_to_interrupt(session, DEFENDER, "P2-courage0", COURAGE_UP)

    assert _event_names(session) == ["CardDiscarded", "HonorChanged"]


def test_a_played_interrupt_rejoins_the_cascade_where_the_fear_stood(reacting):
    session = _fear_announced(
        {}, strategies=(OKURA,), probe="fear_then_honor_probe", watcher="destroyed_probe"
    )
    honor_seen: list[int] = []
    reacting(
        Destroyed, "destroyed_probe", lambda ctx: honor_seen.append(_honor(session, ATTACKER)) or []
    )

    session.act(DEFENDER, PlayInterrupt("okura"))
    pay(session, DEFENDER)

    # The replacement splices in where the Fear stood, so the ability's next effect applies before
    # a reaction to what the replacement did fires, the same as after a rulebook discard.
    assert _event_names(session) == ["CardDiscarded", "Destroyed", "HonorChanged"]
    assert honor_seen == [1]


def test_a_played_interrupts_own_effects_resolve_before_its_discard():
    session = _fear_announced(
        {}, strategies=(("probe", "interrupt_probe", DEFENDER),), probe="fear_then_honor_probe"
    )

    session.act(DEFENDER, PlayInterrupt("probe"))
    pay(session, DEFENDER)

    # The Strategy's own effect, then its discard, then the interrupted ability's next effect.
    assert [
        (type(event).__name__, getattr(event, "seat", None)) for event in session.game.action_events
    ] == [
        ("HonorChanged", DEFENDER),
        ("CardDiscarded", None),
        ("HonorChanged", ATTACKER),
    ]


# --- when the step does not open ---


def _inside_an_action() -> GameState:
    game = two_seat_game()
    _honor_card(game.table, "P2-honor0", P2)
    game.action = KharmicDraw("the-interrupted-action")
    return game


def test_every_effect_inside_an_action_opens_the_step_when_a_card_answers_it():
    """The datasheet's Interrupt answers any of the action's effects, so a Strategy answering Bow
    is offered while a Bow waits, and the Bow resolves once the seat declines."""
    game = _inside_an_action()
    farm = put_in_play(game, holding("P1-farm"))
    _strategy(game.table, "P2-probe", "bow_interrupt_probe", P2)

    resolve_action_effects(game, [Bow(farm.id)])

    assert _asked_seat(game) is P2
    assert legality.legal_actions(game, P2) == [Pass(), PlayInterrupt("P2-probe")]
    assert not farm.bowed

    action_sequence.perform(game, Pass())
    assert game.pending is None
    assert farm.bowed


def test_an_effect_nothing_answers_passes_through_the_step_untouched():
    game = _inside_an_action()
    farm = put_in_play(game, holding("P1-farm"))

    resolve_effects(game, [Bow(farm.id)])

    assert game.pending is None
    assert farm.bowed


def test_a_seat_that_passed_is_asked_again_once_another_seat_interrupts():
    # The step is an action round (CR, Interrupt Actions), so a pass holds only until someone
    # acts: P1 passed on the gain, P2 reduced it, and P1 may now answer the reduced gain.
    game = _inside_an_action()
    _honor_card(game.table, "P1-honor0", P1)

    resolve_action_effects(game, [GainHonor(P1, 2)])
    assert _asked_seat(game) is P1
    action_sequence.perform(game, Pass())
    assert _asked_seat(game) is P2
    _discard_to_interrupt_in(game, "P2-honor0", HONOR_DOWN)

    assert _asked_seat(game) is P1
    _discard_to_interrupt_in(game, "P1-honor0", HONOR_UP)

    assert game.pending is None
    assert game.table.seats[P1].honor == 2


def _asked_seat(game: GameState) -> PlayerId:
    assert game.round.kind is RoundKind.INTERRUPT
    return game.round.priority


def test_a_change_that_is_not_the_actions_own_asks_nobody():
    game = _inside_an_action()

    resolve_effects(game, [GainHonor(P1, 2)])

    assert game.pending is None
    assert game.table.seats[P1].honor == 2


def test_a_change_during_a_response_step_asks_nobody():
    game = _inside_an_action()
    game.round = ActionRound(timings=RESPONSE_TIMINGS, priority=P1, kind=RoundKind.RESPONSE)

    resolve_action_effects(game, [GainHonor(P1, 2)])

    assert game.pending is None


def test_a_traits_effect_during_an_action_asks_nobody(reacting):
    # The action straightens the card; "after this card straightens, gain 2 Honor" is the trait's
    # gain, not the action's, so the Honor Interrupt is not offered against it.
    game = _inside_an_action()
    farm = put_in_play(game, holding("P1-h", printed_id="trait_gain_probe"))
    farm.bow()
    reacting(Straightened, "trait_gain_probe", lambda ctx: [GainHonor(P1, 2)])

    resolve_action_effects(game, [Straighten(farm.id)])

    assert game.pending is None
    assert game.table.seats[P1].honor == 2


def test_a_cost_is_not_open_to_the_interrupt_step_but_the_effect_is():
    # A cost is paid in step B and the action's effects resolve in step E (CR, Action Sequence),
    # and the Honor Interrupt answers "the action's" gains and losses (ShE datasheet).
    game = _inside_an_action()
    source = put_in_play(game, holding("P1-h", printed_id="honor_cost_probe"))
    ability = ability_for(game, source)
    assert ability is not None

    defer_ability(game, source, ability)
    assert game.pending is None
    assert game.table.seats[P1].honor == -1

    sequence.run_stack(game)
    assert _asked_seat(game) is P2


def test_a_then_among_the_actions_effects_is_still_the_actions():
    game = _inside_an_action()

    resolve_action_effects(game, [Then((GainHonor(P1, 2),))])
    sequence.run_stack(game)

    assert _asked_seat(game) is P2


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

    resolve_action_effects(game, [GainHonor(P1, 2), GainHonor(P1, 2)])
    _discard_to_interrupt_in(game, "P2-honor0", HONOR_DOWN)

    assert game.pending is None
    assert game.table.seats[P1].honor == 1 + 2


def test_an_unknown_rulebook_interrupt_is_a_key_error():
    with pytest.raises(KeyError):
        interrupts.rulebook_interrupt("valor")


def test_the_offer_names_the_card_and_the_player_as_the_seat_reads_them():
    # The log describes an effect by id, which is what a replay needs and not what a player is
    # asked about: the offer and the adjustment question both name the board as the seat sees it.
    game = two_seat_game()
    game.table.seats[P1].name = "Ada"
    target = put_in_play(game, personality("P2-d3", owner=P2, name="Shiba Guard", force=2))

    assert GainHonor(P1, 2).narrate(game) == "Ada gains 2 honor"
    assert Fear(2, target.id, P1).narrate(game) == "Fear 2 on Shiba Guard"
    assert Fear(2, target.id, P1).describe() == "fear 2 on P2-d3"


def test_a_change_of_zero_asks_nobody():
    game = _inside_an_action()

    resolve_action_effects(game, [GainHonor(P1, 0)])

    assert game.pending is None


def test_interrupts_from_both_seats_net_against_the_change_and_never_reverse_it():
    game = _inside_an_action()
    _honor_card(game.table, "P1-honor0", P1)

    resolve_action_effects(game, [GainHonor(P1, 1)])
    _discard_to_interrupt_in(game, "P1-honor0", HONOR_DOWN)
    _discard_to_interrupt_in(game, "P2-honor0", HONOR_UP)

    assert game.pending is None
    assert game.table.seats[P1].honor == 1  # -1 then +1 net to nothing, not a gain turned loss


# --- a targeted Interrupt that substitutes the action's target ---


def _substitution_game(*, stand_in_bowed: bool = False) -> GameState:
    """P2's ability is about to resolve against P1's victim, with P1 holding the substitute probe
    and a second Personality to point the action at."""
    game = two_seat_game()
    source = put_in_play(game, holding("P2-src", owner=P2, printed_id="bow_then_destroy_probe"))
    put_in_play(game, personality("P1-victim"))
    stand_in = put_in_play(game, personality("P1-stand-in"))
    if stand_in_bowed:
        stand_in.bow()
    _strategy(game.table, "P1-sub", "substitute_probe", P1)
    game.action = ActivateAbility(source.id)
    game.action_seat = P2
    return game


TARGETING = ResolveAbility("P2-src", "P1-victim")


def _on_the_table(game: GameState) -> set[str]:
    return {card.id for card in game.table.battlefield.cards}


def test_the_actions_targeting_is_held_at_the_step_ahead_of_what_it_does():
    game = _substitution_game()

    resolve_action_effects(game, [TARGETING])

    assert _asked_seat(game) is P1
    assert legality.legal_actions(game, P1) == [Pass(), PlayInterrupt("P1-sub")]
    assert [effect.describe() for effect in interrupts.foreseen_now(game)] == [
        "P2-src targets P1-victim",
        "bow P1-victim",
        "destroy P1-victim",
    ]
    assert not game.table.cards_by_id["P1-victim"].bowed
    assert game.action_targets == ()


def test_naming_a_targeted_interrupt_asks_for_its_target_before_anything_moves():
    game = _substitution_game()
    resolve_action_effects(game, [TARGETING])

    action_sequence.perform(game, PlayInterrupt("P1-sub"))

    request = game.pending
    assert isinstance(request, ChooseInterruptTarget)
    assert request.seat is P1 and request.candidates == ("P1-stand-in",)
    assert request.card_id == "P1-sub"
    assert not game.table.cards_by_id["P1-victim"].bowed
    assert "P1-sub" in {card.id for card in game.table.zones[ZoneKey(P1, ZoneRole.HAND)].cards}


def test_substituting_the_target_resolves_the_whole_ability_against_the_stand_in():
    game = _substitution_game()
    resolve_action_effects(game, [TARGETING])

    action_sequence.perform(game, PlayInterrupt("P1-sub"))
    action_sequence.submit(game, DecisionResponse(("P1-stand-in",)))
    action_sequence.submit(game, DecisionResponse(()))  # the cost of zero
    sequence.run_stack(game)

    assert game.pending is None
    assert "P1-victim" in _on_the_table(game) and not game.table.cards_by_id["P1-victim"].bowed
    assert "P1-stand-in" not in _on_the_table(game)
    assert game.action_targets == ("P1-stand-in",)


def test_a_stand_in_the_action_could_not_target_is_not_offered():
    # "If legal": a bowed Personality is no target for an ability naming an unbowed one, and with
    # no legal stand-in the Interrupt itself is not offered.
    game = _substitution_game(stand_in_bowed=True)

    resolve_action_effects(game, [TARGETING])
    sequence.run_stack(game)

    assert game.pending is None
    assert "P1-victim" not in _on_the_table(game)


def _substitution_session() -> EngineSession:
    """P2 has announced the probe against P1's victim through a session, so the tape holds the
    action a cancel unwinds to."""
    table = _substitution_game().table
    session = EngineSession.start(table, P2)
    session.act(P2, ActivateAbility("P2-src"))
    session.submit(P2, DecisionResponse(("P1-victim",)))
    assert _asked(session) is P1
    return session


def test_backing_out_of_the_target_question_unwinds_the_interrupt():
    session = _substitution_session()
    session.act(P1, PlayInterrupt("P1-sub"))
    assert isinstance(session.game.pending, ChooseInterruptTarget)

    assert session.can_cancel(P1)
    session.cancel(P1)

    assert session.game.pending is None and _asked(session) is P1
    assert PlayInterrupt("P1-sub") in session.legal_actions(P1)


def test_backing_out_of_the_interrupts_payment_unwinds_the_interrupt():
    # The Interrupt is an action of its own on the tape, so a cancel at its payment takes back
    # the Interrupt and leaves P2's action standing beneath the step.
    session = _substitution_session()
    session.act(P1, PlayInterrupt("P1-sub"))
    session.submit(P1, DecisionResponse(("P1-stand-in",)))
    assert isinstance(session.game.pending, ChoosePayment)

    assert session.can_cancel(P1)
    session.cancel(P1)

    assert session.game.pending is None and _asked(session) is P1
    assert session.game.action == ActivateAbility("P2-src")
    assert PlayInterrupt("P1-sub") in session.legal_actions(P1)


def test_the_substitution_replays_to_the_same_board():
    session = _substitution_session()
    session.act(P1, PlayInterrupt("P1-sub"))
    session.submit(P1, DecisionResponse(("P1-stand-in",)))
    pay(session, P1)
    assert session.game.pending is None

    rebuilt = replay(session.log)

    assert rebuilt == session.game
    assert "P1-victim" in _on_the_table(rebuilt)
    assert "P1-stand-in" not in _on_the_table(rebuilt)


def test_an_answer_naming_a_stand_in_no_longer_legal_is_refused():
    game = _substitution_game()
    resolve_action_effects(game, [TARGETING])
    action_sequence.perform(game, PlayInterrupt("P1-sub"))
    game.table.cards_by_id["P1-stand-in"].bow()

    with pytest.raises(RuntimeError, match="no longer"):
        action_sequence.submit(game, DecisionResponse(("P1-stand-in",)))


# --- the window opens once, before anything resolves ---


def test_the_step_opens_before_the_first_effect_and_offers_the_whole_action():
    game = _inside_an_action()
    farm = put_in_play(game, holding("P1-farm"))
    _strategy(game.table, "P2-probe", "bow_interrupt_probe", P2)

    resolve_action_effects(game, [GainHonor(P1, 2), Bow(farm.id)])

    assert _asked_seat(game) is P2
    assert legality.legal_actions(game, P2) == [
        Pass(),
        DiscardToInterrupt("P2-honor0", "honor"),
        PlayInterrupt("P2-probe"),
    ]
    assert game.table.seats[P1].honor == 0 and not farm.bowed


def test_a_seat_that_passes_at_the_step_is_not_asked_again_as_the_effects_resolve():
    game = _inside_an_action()
    farm = put_in_play(game, holding("P1-farm"))
    _strategy(game.table, "P2-probe", "bow_interrupt_probe", P2)
    resolve_action_effects(game, [GainHonor(P1, 2), Bow(farm.id)])

    action_sequence.perform(game, Pass())

    assert game.pending is None
    assert game.table.seats[P1].honor == 2 and farm.bowed


def test_a_modification_binds_to_the_effect_named_and_not_the_next_of_its_kind():
    game = _inside_an_action()
    _honor_card(game.table, "P2-honor1", P2)

    resolve_action_effects(game, [GainHonor(P1, 2), GainHonor(P1, 3)])
    action_sequence.perform(game, DiscardToInterrupt("P2-honor0", "honor"))
    which = game.pending
    assert isinstance(which, ChooseInterruptEffect)
    assert which.candidates == ("P1 gains 2 honor", "P1 gains 3 honor")
    action_sequence.submit(game, DecisionResponse(("P1 gains 3 honor",)))
    action_sequence.submit(game, DecisionResponse(("Reduce by 1",)))

    assert game.pending is None
    assert game.table.seats[P1].honor == 2 + 2


def test_backing_out_of_which_effect_unwinds_the_interrupt():
    game = two_seat_game()
    put_in_play(game, holding("P1-h", printed_id="two_gains_probe"))
    _honor_card(game.table, "P2-honor0", P2)
    session = EngineSession.start(game.table, P1)
    session.act(P1, ActivateAbility("P1-h"))
    session.act(P2, DiscardToInterrupt("P2-honor0", "honor"))
    assert isinstance(session.game.pending, ChooseInterruptEffect)

    assert session.can_cancel(P2)
    session.cancel(P2)

    assert session.game.pending is None and _asked(session) is P2


def test_a_deferred_step_of_the_action_opens_no_second_interrupt_step():
    game = _inside_an_action()

    resolve_action_effects(game, [GainHonor(P1, 1), Then((GainHonor(P1, 2),))])
    assert _asked_seat(game) is P2
    action_sequence.perform(game, Pass())
    sequence.run_stack(game)

    assert game.pending is None
    assert game.table.seats[P1].honor == 3


def test_the_forecast_reads_through_an_attacks_outcome_and_a_deferred_step():
    game = _inside_an_action()
    guard = put_in_play(game, personality("P1-guard", force=2))
    farm = put_in_play(game, holding("P1-farm"))

    foreseen = interrupts.forecast(
        game, (Fear(FEAR, guard.id, P2), Then((Bow(farm.id),)), GainHonor(P1, 0))
    )

    assert foreseen == (Fear(FEAR, guard.id, P2), Bow(guard.id), Bow(farm.id))


def test_the_forecast_shows_no_outcome_for_an_attack_that_cannot_reach():
    game = _inside_an_action()
    guard = put_in_play(game, personality("P1-guard", force=5))

    assert interrupts.forecast(game, (Fear(FEAR, guard.id, P2),)) == (Fear(FEAR, guard.id, P2),)


def test_an_interrupt_bound_to_an_effect_the_action_never_produces_is_spent_with_the_action():
    # P2 answers the Bow behind the Fear, then makes the Fear miss with Courage: the Bow never
    # comes up, and the modification does not outlive the action to answer a later Bow.
    session = _fear_announced(
        {DEFENDER: 1}, strategies=(("probe", "bow_interrupt_probe", DEFENDER),)
    )
    session.act(DEFENDER, PlayInterrupt("probe"))
    pay(session, DEFENDER)
    assert session.game.modifications
    _discard_to_interrupt(session, DEFENDER, "P2-courage0", COURAGE_DOWN)

    assert session.game.pending is None
    assert not _guard_bowed(session)
    assert session.game.modifications == []


def test_an_abilitys_effects_are_built_once_so_a_modification_finds_what_it_answered():
    # The probe's second gain reads the board. Built at resolution it would read the first gain
    # and become 5, and the Honor discard bound to "gain 1" would find only the first.
    game = two_seat_game()
    put_in_play(game, holding("P1-h", printed_id="board_reading_probe"))
    _honor_card(game.table, "P2-honor0", P2)
    session = EngineSession.start(game.table, P1)
    session.act(P1, ActivateAbility("P1-h"))
    session.submit(P1, DecisionResponse(("P1-h",)))
    assert _asked(session) is P2

    _discard_to_interrupt(session, P2, "P2-honor0", HONOR_DOWN)

    assert session.game.pending is None
    assert session.game.table.seats[P1].honor == 1


def test_an_answer_naming_an_effect_the_forecast_no_longer_holds_is_refused():
    game = _inside_an_action()
    _honor_card(game.table, "P2-honor1", P2)
    resolve_action_effects(game, [GainHonor(P1, 2), GainHonor(P1, 3)])
    action_sequence.perform(game, DiscardToInterrupt("P2-honor0", "honor"))
    request = game.pending
    assert isinstance(request, ChooseInterruptEffect)

    with pytest.raises(RuntimeError, match="no longer among"):
        interrupts.apply_interrupt_effect(game, request, DecisionResponse(("P1 gains 9 honor",)))


def test_a_card_interrupt_answers_the_effect_as_earlier_interrupts_left_it():
    # Courage takes the Fear to 0 before Okura is played on it, so Okura's destroy rides a Fear
    # that no longer reaches the 2F guard, and the guard stands.
    session = _fear_announced({DEFENDER: 1}, strategies=(OKURA,))
    _discard_to_interrupt(session, DEFENDER, "P2-courage0", COURAGE_DOWN)
    assert _asked(session) is DEFENDER

    session.act(DEFENDER, PlayInterrupt("okura"))
    pay(session, DEFENDER)

    assert session.game.pending is None
    assert not _guard_bowed(session)
    assert "guard" in {card.id for card in session.game.table.battlefield.cards}


# --- the step is a round ---


def test_an_unstoppable_action_entitles_no_other_seat_to_interrupt():
    game = two_seat_game()
    put_in_play(game, holding("P1-h", printed_id="unstoppable_probe"))
    _honor_card(game.table, "P2-honor0", P2)
    session = EngineSession.start(game.table, P1)

    session.act(P1, ActivateAbility("P1-h"))

    assert session.game.round.kind is not RoundKind.INTERRUPT
    assert session.game.table.seats[P1].honor == 2


def test_an_unstoppable_action_still_opens_the_step_for_its_own_seat():
    game = two_seat_game()
    put_in_play(game, holding("P1-h", printed_id="unstoppable_probe"))
    _honor_card(game.table, "P1-honor0", P1)
    _honor_card(game.table, "P2-honor0", P2)
    session = EngineSession.start(game.table, P1)

    session.act(P1, ActivateAbility("P1-h"))

    assert _asked(session) is P1
    assert session.legal_actions(P2) == []
    _discard_to_interrupt(session, P1, "P1-honor0", HONOR_UP)
    assert session.game.table.seats[P1].honor == 3


def test_an_interrupt_answering_every_effect_binds_to_all_of_them():
    game = _inside_an_action()
    farm = put_in_play(game, holding("P1-farm"))
    _strategy(game.table, "P2-negate", "negate_action_probe", P2)
    resolve_action_effects(game, [GainHonor(P1, 2), Bow(farm.id)])

    action_sequence.perform(game, PlayInterrupt("P2-negate"))
    action_sequence.submit(game, DecisionResponse(()))  # the cost of zero
    sequence.run_stack(game)

    assert game.pending is None and game.round.kind is not RoundKind.INTERRUPT
    assert game.table.seats[P1].honor == 0 and not farm.bowed


def test_an_interrupt_on_an_event_in_a_province_is_offered_and_taken_from_there():
    game = _inside_an_action()
    farm = put_in_play(game, holding("P1-farm"))
    event = holding("P2-event", owner=P2, printed_id="province_event_probe")
    event.turn_face_up()
    province = ProvinceZone(owner=P2)
    province.add(register(game.table, event))
    game.table.zones[ZoneKey(P2, ZoneRole.PROVINCE, 0)] = province
    resolve_action_effects(game, [Bow(farm.id)])

    assert legality.legal_actions(game, P2) == [Pass(), PlayInterrupt("P2-event")]
    action_sequence.perform(game, PlayInterrupt("P2-event"))
    sequence.run_stack(game)

    assert game.table.seats[P2].honor == 1 and farm.bowed
    discard = game.table.zones[ZoneKey(P2, ZoneRole.DYNASTY_DISCARD)].cards
    assert "P2-event" in {card.id for card in discard}


def test_the_step_is_a_round_over_the_round_the_action_was_taken_in():
    session = _proclaim_session({P2: 1})
    assert session.game.round.kind is RoundKind.INTERRUPT
    assert session.game.round.timings == INTERRUPT_TIMINGS
    assert len(session.game.round_stack) == 1

    session.act(P2, Pass())

    assert session.game.round.kind is not RoundKind.INTERRUPT
    assert session.game.round_stack == []


def test_an_interrupt_leaves_the_action_record_as_the_interrupted_action():
    session = _fear_announced({}, strategies=(OKURA,))

    session.act(DEFENDER, PlayInterrupt("okura"))

    assert session.game.action == ActivateAbility("raider")
    assert session.game.action_seat is ATTACKER


@choice_resolver("interrupt_probe_choice", prompt="Pick one")
def _resolve_interrupt_probe_choice(game, source_id, chosen, seat):
    return [GainHonor(seat, 1)]


def test_no_response_step_opens_inside_the_interrupt_step():
    # A Response answers a non-Interrupt action (ShE datasheet, Response), so an Interrupt taken
    # inside the step opens no Response Step of its own.
    session = _fear_announced({}, strategies=(OKURA,))
    assert session.game.round.kind is RoundKind.INTERRUPT

    assert sequence.open_response_window(session.game) is False
    assert session.game.round.kind is RoundKind.INTERRUPT


def test_the_step_closes_into_a_decision_the_held_action_asks():
    # The held action's own question comes after the step has closed: the round beneath it is
    # back in place, and the answer hands the opportunity on from that round.
    game = _inside_an_action()
    _honor_card(game.table, "P2-honor0", P2)
    resolve_action_effects(
        game,
        [GainHonor(P1, 1), Choose(P1, ("either", "or"), 1, 1, "interrupt_probe_choice", None)],
    )
    assert _asked_seat(game) is P2

    action_sequence.perform(game, Pass())

    assert game.round.kind is not RoundKind.INTERRUPT and game.round_stack == []
    assert isinstance(game.pending, ChooseCards)
    assert game.table.seats[P1].honor == 1
    action_sequence.submit(game, DecisionResponse(("either",)))
    assert game.pending is None and game.table.seats[P1].honor == 2
