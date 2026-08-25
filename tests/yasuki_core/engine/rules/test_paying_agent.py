import pytest

from yasuki_core.engine.players import PlayerId
from yasuki_core.engine.rules.abilities import (
    _PRODUCTION_BOOST,
    ProductionBoost,
    register_production_boost,
)
from yasuki_core.engine.rules.agents import AutoAgent, PayingAgent
from yasuki_core.engine.rules.decisions import BoostOffer, ChoosePayment, DiscardToHandSize
from yasuki_core.engine.rules.actions import Recruit
from yasuki_core.engine.rules.policies import EconomicPolicy
from yasuki_core.engine.runner import Controls, play_game
from yasuki_core.engine.session import EngineSession

from tests.yasuki_core.engine.builders import (
    dealt_table,
    end_phase,
    holding,
    pay,
    province_card,
    put_in_play,
)

P1 = PlayerId.P1


def _answer(**kwargs) -> tuple[tuple[str, ...], tuple[str, ...]]:
    request = ChoosePayment(P1, (), label="x", **kwargs)
    response = PayingAgent().decide(request, view=None)
    return response.choices, tuple(sorted(ChoosePayment.boosts_taken(response)))


def test_a_cost_already_in_the_pool_bows_nothing():
    assert _answer(amount=3, available=3, produced=(("mine", 4),)) == ((), ())


def test_it_bows_the_smallest_producer_first():
    """Smallest first, so the larger producers stay straight for a second purchase this turn. The
    answer names one; the payment comes back round for the rest."""
    chosen, boosted = _answer(
        amount=3, available=0, produced=(("big", 5), ("small", 1), ("mid", 2))
    )

    assert chosen == ("small",)
    assert boosted == ()


def test_a_boost_is_left_alone_when_plain_production_covers_the_cost():
    """A boost costs the producer whatever its card names, so it is never taken for convenience."""
    chosen, boosted = _answer(
        amount=2, available=0, produced=(("farm", 2),), boostable=(BoostOffer("farm", 2),)
    )

    assert chosen == ("farm",)
    assert boosted == ()


def test_a_boost_is_taken_when_nothing_else_reaches_the_cost():
    chosen, boosted = _answer(
        amount=4, available=0, produced=(("farm", 2),), boostable=(BoostOffer("farm", 2),)
    )

    assert chosen == ("farm",)
    assert boosted == ("farm",)


def test_it_answers_a_non_payment_decision_exactly_as_the_placeholder_does():
    """Only payments need the special handling. Delegating anything else keeps one answer for a
    decision type rather than two that can drift apart."""
    request = DiscardToHandSize(P1, ("a", "b", "c"), count=2)

    assert PayingAgent().decide(request, view=None) == AutoAgent().decide(request, view=None)


def test_a_plain_recruit_is_paid_for_and_leaves_the_producer_alive():
    """The ordinary path: enough production to cover the cost, so the producer bows without paying
    the price a boost would carry."""
    session = EngineSession.start(dealt_table(), P1, seed=1)
    put_in_play(session.game, holding("mine", owner=P1, gold_production=4))
    province_card(session.game, "target", seat=P1, gold_cost=3)
    controls = {seat: Controls(EconomicPolicy(), PayingAgent()) for seat in PlayerId}

    play_game(session, controls, turn_limit=1)

    table = session.game.table
    assert table.cards_by_id["target"] in table.battlefield.cards
    assert table.cards_by_id["mine"] in table.battlefield.cards
    assert table.cards_by_id["mine"].bowed


def _boost_only_game() -> EngineSession:
    """A board where the one affordable recruit is affordable only by boosting.

    Outlying Farms yields 2 and can raise that to 4 as it bows, at the price of destroying itself.
    ``legal_actions`` offers the 4-cost card because ``reachable_gold`` counts the boost.
    """
    table = dealt_table()
    put_in_play(table, holding("of", owner=P1, printed_id="outlying_farms", gold_production=2))
    session = EngineSession.start(table, P1, seed=1)
    province_card(session.game, "target", seat=P1, gold_cost=4)
    return session


def test_the_placeholder_agent_cannot_pay_a_cost_that_needs_a_boost():
    """Pins why this agent exists. The engine offers the recruit, so a run that takes it dies on a
    payment with no answer — a crash reachable by any policy that recruits."""
    session = _boost_only_game()
    controls = {seat: Controls(EconomicPolicy(), AutoAgent()) for seat in PlayerId}

    with pytest.raises(ValueError, match="no auto-answer satisfies ChoosePayment"):
        play_game(session, controls, turn_limit=1)


def test_a_boosted_recruit_is_paid_for_and_completes():
    session = _boost_only_game()
    controls = {seat: Controls(EconomicPolicy(), PayingAgent()) for seat in PlayerId}

    play_game(session, controls, turn_limit=1)

    table = session.game.table
    assert table.cards_by_id["target"] in table.battlefield.cards
    # Outlying Farms paid with its boost, which destroys it.
    assert table.cards_by_id["of"] not in table.battlefield.cards


def test_it_keeps_answering_until_the_cost_is_met():
    """Three one-gold producers against a cost of three, driven end to end. Any off-by-one in the
    loop's stopping condition under-pays here while covering every cost met in a single larger
    jump. The agent picks one each round; knowing when to stop is the payment's job, not its."""
    state = dealt_table()
    for name in ("a", "b", "c"):
        put_in_play(state, holding(name, owner=P1, gold_production=1))
    session = EngineSession.start(state, P1)
    province_card(session.game, "target", seat=P1, gold_cost=3)
    end_phase(session)
    end_phase(session)
    session.act(P1, Recruit("target"))

    pay(session, P1)

    table = session.game.table
    assert table.cards_by_id["target"] in table.battlefield.cards
    assert all(table.cards_by_id[name].bowed for name in ("a", "b", "c"))


def test_it_stops_as_soon_as_the_pool_covers_the_cost():
    """Gold left over from an earlier payment stays in the pool, so a later cost is only partly
    borne by producers. Bowing a second producer here would be one more than needed."""
    state = dealt_table()
    for name in ("a", "b"):
        put_in_play(state, holding(name, owner=P1, gold_production=3))
    session = EngineSession.start(state, P1)
    province_card(session.game, "target", seat=P1, gold_cost=5)
    end_phase(session)
    end_phase(session)
    session.act(P1, Recruit("target"))
    session.game.gold[P1] = 2  # left over from an earlier payment this phase

    pay(session, P1)

    table = session.game.table
    assert table.cards_by_id["target"] in table.battlefield.cards
    assert sum(table.cards_by_id[name].bowed for name in ("a", "b")) == 1


def test_it_boosts_the_producer_that_can_when_the_smallest_cannot():
    """The greedy pick and the boostable card need not be the same one. Bowing smallest-first hands
    over a producer with nothing to give, and the boost has to still be taken on the next round or
    the payment strands one Gold short."""
    register_production_boost("boostable_probe", ProductionBoost(2))

    try:
        state = dealt_table()
        put_in_play(state, holding("small", owner=P1, gold_production=1))
        put_in_play(
            state, holding("big", owner=P1, printed_id="boostable_probe", gold_production=2)
        )
        session = EngineSession.start(state, P1)
        province_card(session.game, "target", seat=P1, gold_cost=5)
        end_phase(session)
        end_phase(session)
        session.act(P1, Recruit("target"))

        pay(session, P1)

        table = session.game.table
        assert table.cards_by_id["target"] in table.battlefield.cards
        assert table.cards_by_id["small"].bowed and table.cards_by_id["big"].bowed
    finally:
        _PRODUCTION_BOOST.pop("boostable_probe", None)
