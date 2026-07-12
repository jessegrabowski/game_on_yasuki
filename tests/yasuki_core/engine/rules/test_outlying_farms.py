from yasuki_core.engine.players import PlayerId
from yasuki_core.engine.table import DeckKey, TableState, ZoneKey, ZoneRole
from yasuki_core.engine.zones import ProvinceZone
from yasuki_core.game_pieces.constants import Side
from yasuki_core.game_pieces.dynasty import DynastyHolding
from yasuki_core.engine.rules.actions import Pass, Recruit
from yasuki_core.engine.rules.agents import AutoAgent
from yasuki_core.engine.rules.decisions import DecisionResponse
from yasuki_core.engine.rules.log import replay
from yasuki_core.engine.session import EngineSession

P1 = PlayerId.P1


def _register(state, card):
    state.cards_by_id[card.id] = card
    return card


def _outlying_game(*, target_cost=2, with_producer=True):
    """A Dynasty-phase session with P1's Outlying Farms (gp 2) in play, an optional 8-gold producer,
    and a face-up target Holding in a province to recruit."""
    state = TableState.empty_two_seat()
    state.decks[DeckKey(P1, Side.DYNASTY)].cards = [
        _register(state, DynastyHolding(id="refill", name="R", side=Side.DYNASTY, owner=P1))
    ]
    if with_producer:
        state.battlefield.add(
            _register(
                state,
                DynastyHolding(id="sh", name="SH", side=Side.DYNASTY, owner=P1, gold_production=8),
            )
        )
    state.battlefield.add(
        _register(
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
    )
    target = _register(
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
