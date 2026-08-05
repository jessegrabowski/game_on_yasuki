from yasuki_core.engine.players import PlayerId
from yasuki_core.engine.table import DeckKey, TableState, ZoneKey, ZoneRole
from yasuki_core.engine.zones import ProvinceZone
from yasuki_core.game_pieces.constants import Side
from yasuki_core.game_pieces.dynasty import DynastyHolding
from yasuki_core.engine.rules.abilities import (
    _PRODUCTION_BOOST,
    ProductionBoost,
    register_production_boost,
)
from yasuki_core.engine.rules.actions import Pass, Recruit
from yasuki_core.engine.rules.agents import AutoAgent
from yasuki_core.engine.rules.decisions import DecisionResponse
from yasuki_core.engine.rules.log import replay
from yasuki_core.engine.session import EngineSession

from tests.yasuki_core.engine.builders import put_in_play, register

P1 = PlayerId.P1


def _outlying_game(*, target_cost=2, with_producer=True):
    """A Dynasty-phase session with P1's Outlying Farms (gp 2) in play, an optional 8-gold producer,
    and a face-up target Holding in a province to recruit."""
    state = TableState.empty_two_seat()
    state.decks[DeckKey(P1, Side.DYNASTY)].cards = [
        register(state, DynastyHolding(id="refill", name="R", side=Side.DYNASTY, owner=P1))
    ]
    if with_producer:
        put_in_play(
            state,
            DynastyHolding(id="sh", name="SH", side=Side.DYNASTY, owner=P1, gold_production=8),
        )
    put_in_play(
        state,
        DynastyHolding(
            id="of",
            name="Outlying Farms",
            side=Side.DYNASTY,
            owner=P1,
            printed_id="outlying_farms",
            keywords=("Farm",),
            gold_production=2,
        ),
    )
    target = register(
        state,
        DynastyHolding(
            id="target",
            name="Target",
            side=Side.DYNASTY,
            owner=P1,
            printed_id="plain_holding",
            gold_cost=target_cost,
            gold_production=2,
        ),
    )
    target.turn_face_up()
    province = ProvinceZone(owner=P1)
    province.add(target)
    state.zones[ZoneKey(P1, ZoneRole.PROVINCE, 0)] = province
    session = EngineSession.start(state, P1)  # Action phase
    session.act(P1, Pass())  # Action -> Attack
    session.act(P1, Pass())  # Attack -> Dynasty
    return session


def _recruited(session, card_id):
    return session.game.table.cards_by_id[card_id] in session.game.table.battlefield.cards


def _in_dynasty_discard(session, card_id):
    discard = session.game.table.zones[ZoneKey(P1, ZoneRole.DYNASTY_DISCARD)]
    return card_id in {c.id for c in discard.cards}


def test_outlying_farms_is_flagged_boostable_in_the_payment_offer():
    session = _outlying_game()
    session.act(P1, Recruit("target"))
    assert session.game.pending.boostable == (("of", 2),)


def test_boost_makes_the_extra_gold_needed_to_afford_a_recruit():
    # The whole point: Outlying Farms alone (base 2) covers a cost-4 recruit only boosted (to 4). The
    # recruit is offered, the unboosted answer is rejected, and boosting pays and destroys it.
    session = _outlying_game(target_cost=4, with_producer=False)
    assert Recruit("target") in session.legal_actions(P1)

    session.act(P1, Recruit("target"))
    pending = session.game.pending
    assert not pending.accepts(DecisionResponse(("of",)))  # base 2 < 4
    assert pending.accepts(DecisionResponse(("of",), ("of",)))  # boosted 4 >= 4

    session.submit(P1, DecisionResponse(("of",), ("of",)))
    assert _recruited(session, "target")
    assert _in_dynasty_discard(session, "of")  # destroyed after bowing boosted
    assert session.game.gold[P1] == 0


def test_boosting_banks_the_extra_gold_and_destroys_outlying_farms():
    session = _outlying_game(target_cost=2, with_producer=False)
    session.act(P1, Recruit("target"))
    session.submit(P1, DecisionResponse(("of",), ("of",)))  # boost though 2 already covers

    assert _recruited(session, "target")
    assert _in_dynasty_discard(session, "of")
    assert session.game.gold[P1] == 2  # 4 produced, 2 spent, 2 excess banked


def test_declining_the_boost_bows_outlying_farms_for_its_plain_yield():
    session = _outlying_game(target_cost=2, with_producer=False)
    session.act(P1, Recruit("target"))
    session.submit(P1, DecisionResponse(("of",)))  # no boost

    assert _recruited(session, "target")
    of = session.game.table.cards_by_id["of"]
    assert of in session.game.table.battlefield.cards and of.bowed  # bowed, not destroyed
    assert session.game.gold[P1] == 0


def test_a_payment_can_only_boost_a_bowed_boostable_producer():
    session = _outlying_game()
    session.act(P1, Recruit("target"))
    pending = session.game.pending
    assert not pending.accepts(DecisionResponse(("sh",), ("of",)))  # boosted a producer not bowed
    assert not pending.accepts(
        DecisionResponse(("sh",), ("sh",))
    )  # boosted a non-boostable producer


def test_the_auto_agent_never_boosts_so_outlying_farms_survives():
    # Regression: the boost must never be forced. The generic agent leaves boosted empty, so a
    # base-covering payment never sacrifices Outlying Farms.
    session = _outlying_game(target_cost=2)
    session.act(P1, Recruit("target"))

    answer = AutoAgent().decide(session.game.pending, session.project(P1))
    assert answer.boosted == ()


def test_outlying_farms_boost_replays_to_the_same_state():
    session = _outlying_game(target_cost=4, with_producer=False)
    session.act(P1, Recruit("target"))
    session.submit(P1, DecisionResponse(("of",), ("of",)))
    assert replay(session.log) == session.game


def test_a_boost_that_declares_no_consequence_leaves_its_producer_alive():
    """The payment path used to destroy any boosted producer, which is Outlying Farms' text applied
    to every card that might ever boost. A boost that declares nothing must cost nothing."""
    register_production_boost("free_boost_probe", ProductionBoost(3))

    try:
        state = TableState.empty_two_seat()
        state.decks[DeckKey(P1, Side.DYNASTY)].cards = [
            register(state, DynastyHolding(id="refill", name="R", side=Side.DYNASTY, owner=P1))
        ]
        put_in_play(
            state,
            DynastyHolding(
                id="fb",
                name="Free Boost",
                side=Side.DYNASTY,
                owner=P1,
                printed_id="free_boost_probe",
                gold_production=2,
            ),
        )
        target = register(
            state,
            DynastyHolding(id="tgt", name="T", side=Side.DYNASTY, owner=P1, gold_cost=5),
        )
        target.turn_face_up()
        province = ProvinceZone(owner=P1)
        province.add(target)
        state.zones[ZoneKey(P1, ZoneRole.PROVINCE, 0)] = province

        session = EngineSession.start(state, P1)
        session.act(P1, Pass())
        session.act(P1, Pass())
        session.act(P1, Recruit("tgt"))
        session.submit(P1, DecisionResponse(("fb",), ("fb",)))

        probe = session.game.table.cards_by_id["fb"]

        assert probe.bowed
        assert probe in session.game.table.battlefield.cards
    finally:
        _PRODUCTION_BOOST.pop("free_boost_probe", None)


def test_a_producers_yield_at_resolution_still_depends_on_what_it_pays_for():
    """Jade Works yields +2 only when paying for a Jade card. Payment resolution recomputes each
    producer's yield, so it has to recompute it against the same target the offer quoted."""
    state = TableState.empty_two_seat()
    state.decks[DeckKey(P1, Side.DYNASTY)].cards = [
        register(state, DynastyHolding(id="refill", name="R", side=Side.DYNASTY, owner=P1))
    ]
    put_in_play(
        state,
        DynastyHolding(
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
        DynastyHolding(
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
    session.act(P1, Pass())
    session.act(P1, Pass())
    session.act(P1, Recruit("jade"))
    # The offer quotes 4 — base 2 plus the Jade bonus — and bowing it alone must cover the cost.
    session.submit(P1, DecisionResponse(("jw",)))

    # 4 produced (2 base + 2 Jade bonus) less the 4 spent. Recomputing without the target would
    # yield 2 and leave the seat short, which asserting on the recruit alone would not notice.
    assert session.game.gold[P1] == 0
    assert _recruited(session, "jade")
