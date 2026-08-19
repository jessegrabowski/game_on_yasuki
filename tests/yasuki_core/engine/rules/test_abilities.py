import pytest

from yasuki_core.engine.players import PlayerId
from yasuki_core.engine.table import TableState, DeckKey, ZoneKey, ZoneRole
from yasuki_core.engine.zones import ProvinceZone
from yasuki_core.game_pieces.constants import Side
from yasuki_core.engine.rules.abilities import (
    CardLocation,
    Ability,
    ProductionBoost,
    _ABILITIES,
    _ENTERS_UNBOWED,
    _INVEST,
    _PRODUCTION_BOOST,
    register_ability,
    register_enters_unbowed,
    register_invest,
    register_production_boost,
)
from yasuki_core.engine.rules.actions import ActionTiming, ActivateAbility, Recruit
from yasuki_core.engine.rules.decisions import ChooseAbilityTarget, ChooseCards, DecisionResponse
from yasuki_core.engine.rules.log import replay
from yasuki_core.engine.rules.effects import AdjustCounter, Choose
from yasuki_core.engine.rules.triggers import choice_resolver
from yasuki_core.engine.session import EngineSession
from yasuki_core.game_pieces.counters import WEALTH
from yasuki_core.game_pieces.cards import L5RCard
from yasuki_core.game_pieces.prints import HoldingPrint
from tests.yasuki_core.engine.builders import (
    end_phase,
    holding,
    province_card,
    put_in_play,
    register,
)


@choice_resolver("test_cost_pauses")
def _test_cost_grant(game, source_id, chosen, seat):
    return [AdjustCounter(card_id, WEALTH, 1) for card_id in chosen]


# A synthetic ability whose cost pauses for a choice. It exercises the deferred target selection: the
# cost's own decision must resolve before the ability's target is asked, neither clobbering the
# other. No real card pays a cost that pauses yet.
_ABILITIES["test_cost_pauses"] = Ability(
    timing=ActionTiming.OPEN,
    label="test",
    cost=lambda game, source: [
        Choose(source.owner, (source.id,), 0, 1, "test_cost_pauses", source.id)
    ],
    targets=lambda game, card: [
        c.id
        for c in game.table.battlefield.cards
        if c.owner is card.owner and c is not card and "Farm" in c.keywords
    ],
    effects=lambda game, source, target: [AdjustCounter(target.id, WEALTH, 1)],
)


def test_a_cost_that_pauses_resolves_before_the_ability_target():
    state = TableState.empty_two_seat()
    put_in_play(state, holding("src", printed_id="test_cost_pauses"))
    put_in_play(
        state, holding("tgt", printed_id="plain_farm", keywords=("Farm",), gold_production=2)
    )
    session = EngineSession.start(state, PlayerId.P1)

    session.act(PlayerId.P1, ActivateAbility("src"))
    assert isinstance(session.game.pending, ChooseCards)  # the cost's choice comes first
    assert session.game.pending.candidates == ("src",)

    session.submit(PlayerId.P1, DecisionResponse(("src",)))
    pending = session.game.pending
    assert isinstance(pending, ChooseAbilityTarget)  # the target, deferred until the cost resolved
    assert pending.candidates == ("tgt",)
    assert session.game.table.cards_by_id["src"].counters == {"wealth": 1}  # cost choice applied

    session.submit(PlayerId.P1, DecisionResponse(("tgt",)))
    assert session.game.pending is None
    assert session.game.table.cards_by_id["tgt"].counters == {"wealth": 1}  # ability effect applied
    assert replay(session.log) == session.game  # the deferred-cost chain replays deterministically


def test_a_second_ability_for_one_card_is_refused():
    # These three registries were dict literals until the card modules split them up, where a
    # repeated key was ruff's F601 to catch. Registration-time checks replace that guard.
    register_ability("guard_probe", _ABILITIES["millet_farm"])

    try:
        with pytest.raises(ValueError, match="guard_probe already has an ability"):
            register_ability("guard_probe", _ABILITIES["millet_farm"])
    finally:
        _ABILITIES.pop("guard_probe", None)


def test_a_second_invest_for_one_card_is_refused():
    register_invest("guard_probe", _INVEST["training_court"])

    try:
        with pytest.raises(ValueError, match="guard_probe already has an invest ability"):
            register_invest("guard_probe", _INVEST["training_court"])
    finally:
        _INVEST.pop("guard_probe", None)


def test_a_second_enters_unbowed_for_one_card_is_refused():
    # A set absorbs a repeated registration where the dict registries raise, so without this guard a
    # card listed from two set modules would be invisible rather than loud.
    register_enters_unbowed("guard_probe")

    try:
        with pytest.raises(ValueError, match="guard_probe already enters play unbowed"):
            register_enters_unbowed("guard_probe")
    finally:
        _ENTERS_UNBOWED.discard("guard_probe")


def test_a_second_production_boost_for_one_card_is_refused():
    register_production_boost("guard_probe", 2)

    try:
        with pytest.raises(ValueError, match="guard_probe already has a production boost"):
            register_production_boost("guard_probe", 2)
    finally:
        _PRODUCTION_BOOST.pop("guard_probe", None)


# An ability that acts from a Province rather than from play — the shape every Event needs. It
# targets its own source, so the test needs nothing else there.
_ABILITIES["test_acts_from_province"] = Ability(
    timing=ActionTiming.OPEN,
    label="test",
    cost=lambda game, source: [],
    targets=lambda game, card: [card.id],
    effects=lambda game, source, target: [AdjustCounter(target.id, WEALTH, 1)],
    located_at=(CardLocation.PROVINCE,),
)


def test_an_ability_that_acts_from_a_province_is_offered_there():
    state = TableState.empty_two_seat()
    card = province_card(state, "event", printed_id="test_acts_from_province")
    session = EngineSession.start(state, PlayerId.P1)

    assert ActivateAbility(card.id) in session.legal_actions(PlayerId.P1)


def test_an_ability_that_acts_from_a_province_is_not_offered_face_down():
    """Face-down the card has not been revealed, so it is not offering anything yet. Setup reveals
    what starts in a Province, so this is the state a refill leaves behind mid-game."""
    state = TableState.empty_two_seat()
    province_card(state, "event", printed_id="test_acts_from_province")
    session = EngineSession.start(state, PlayerId.P1)
    session.game.table.cards_by_id["event"].turn_face_down()

    assert ActivateAbility("event") not in session.legal_actions(PlayerId.P1)


def test_an_ability_that_acts_from_a_province_is_not_offered_in_play():
    """The scope says where the card acts from, so it excludes as well as it includes."""
    state = TableState.empty_two_seat()
    put_in_play(state, holding("event", printed_id="test_acts_from_province"))
    session = EngineSession.start(state, PlayerId.P1)

    assert ActivateAbility("event") not in session.legal_actions(PlayerId.P1)


def test_a_province_ability_is_not_offered_for_another_seats_card():
    """Asked from the seat holding priority, so it fails if the scan stops filtering by owner —
    asking P2 instead would pass on P2 having no actions at all."""
    state = TableState.empty_two_seat()
    province_card(state, "event", printed_id="test_acts_from_province", seat=PlayerId.P2)
    session = EngineSession.start(state, PlayerId.P1)

    assert ActivateAbility("event") not in session.legal_actions(PlayerId.P1)


def test_an_ability_in_play_is_not_offered_from_a_province():
    """The default scope is the battlefield, so a Holding sitting face-up in a Province offers
    nothing — which is what keeps every existing registration behaving as it did."""
    state = TableState.empty_two_seat()
    card = province_card(
        state, "millet", printed_id="millet_farm", keywords=("Farm",), gold_production=1
    )
    put_in_play(state, holding("farm", printed_id="plain_farm", keywords=("Farm",)))
    session = EngineSession.start(state, PlayerId.P1)

    assert ActivateAbility(card.id) not in session.legal_actions(PlayerId.P1)


# A card that acts from either place. The scope is a tuple so an ability can name more than one, and
# nothing else pins that.
_ABILITIES["test_acts_from_either"] = Ability(
    timing=ActionTiming.OPEN,
    label="test",
    cost=lambda game, source: [],
    targets=lambda game, card: [card.id],
    effects=lambda game, source, target: [AdjustCounter(target.id, WEALTH, 1)],
    located_at=(CardLocation.BATTLEFIELD, CardLocation.PROVINCE),
)


@pytest.mark.parametrize("in_play", [True, False])
def test_an_ability_may_act_from_more_than_one_place(in_play):
    state = TableState.empty_two_seat()
    if in_play:
        put_in_play(state, holding("event", printed_id="test_acts_from_either"))
    else:
        province_card(state, "event", printed_id="test_acts_from_either")
    session = EngineSession.start(state, PlayerId.P1)

    assert ActivateAbility("event") in session.legal_actions(PlayerId.P1)


def test_a_boost_that_declares_no_consequence_leaves_its_producer_alive():
    """The payment path used to destroy any boosted producer, which is Outlying Farms' text applied
    to every card that might ever boost. A boost that declares nothing must cost nothing."""
    register_production_boost("free_boost_probe", ProductionBoost(3))

    try:
        state = TableState.empty_two_seat()
        state.decks[DeckKey(PlayerId.P1, Side.DYNASTY)].cards = [
            register(
                state,
                L5RCard.of(
                    HoldingPrint, id="refill", name="R", side=Side.DYNASTY, owner=PlayerId.P1
                ),
            )
        ]
        put_in_play(
            state,
            L5RCard.of(
                HoldingPrint,
                id="fb",
                name="Free Boost",
                side=Side.DYNASTY,
                owner=PlayerId.P1,
                printed_id="free_boost_probe",
                gold_production=2,
            ),
        )
        target = register(
            state,
            L5RCard.of(
                HoldingPrint, id="tgt", name="T", side=Side.DYNASTY, owner=PlayerId.P1, gold_cost=5
            ),
        )
        target.turn_face_up()
        province = ProvinceZone(owner=PlayerId.P1)
        province.add(target)
        state.zones[ZoneKey(PlayerId.P1, ZoneRole.PROVINCE, 0)] = province

        session = EngineSession.start(state, PlayerId.P1)
        end_phase(session)
        end_phase(session)
        session.act(PlayerId.P1, Recruit("tgt"))
        session.submit(PlayerId.P1, DecisionResponse(("fb",), ("fb",)))

        probe = session.game.table.cards_by_id["fb"]

        assert probe.bowed
        assert probe in session.game.table.battlefield.cards
    finally:
        _PRODUCTION_BOOST.pop("free_boost_probe", None)
