from yasuki_core.engine.players import PlayerId
from yasuki_core.engine.rules.agents import AutoAgent, PayingAgent, is_production_window
from yasuki_core.engine.rules.decisions import ChoosePayment, Confirm, DiscardToHandSize
from yasuki_core.engine.rules.projection import project
from yasuki_core.engine.rules.actions import Recruit
from yasuki_core.engine.rules.policies import EconomicPolicy
from yasuki_core.engine.runner import Controls, play_game
from yasuki_core.engine.session import EngineSession

from tests.yasuki_core.engine.builders import (
    dealt_table,
    two_seat_game,
    end_phase,
    holding,
    pay,
    province_card,
    put_in_play,
)

P1 = PlayerId.P1


def _answer(**kwargs) -> tuple[str, ...]:
    request = ChoosePayment(P1, (), label="x", **kwargs)
    return PayingAgent().decide(request, view=None).choices


def test_a_cost_already_in_the_pool_bows_nothing():
    assert _answer(amount=3, available=3, produced=(("mine", 4),)) == ()


def test_it_bows_the_smallest_producer_first():
    """Smallest first, so the larger producers stay straight for a second purchase this turn. The
    answer names one; the payment comes back round for the rest."""
    assert _answer(amount=3, available=0, produced=(("big", 5), ("small", 1), ("mid", 2))) == (
        "small",
    )


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


def test_a_face_down_card_in_play_is_not_mistaken_for_a_window():
    """The window is recognized by the card that raised it, and a viewer who cannot identify a card
    in play sees a back with no printed id to read. Reaching for one crashes the agent for every
    decision, not just this one."""
    game = two_seat_game()
    put_in_play(game, holding("of", owner=P1, printed_id="outlying_farms")).turn_face_down()
    asked = Confirm(seat=P1, candidates=("of",), question="?", resolver="r", source_id="of")

    assert not is_production_window(asked, project(game, PlayerId.P2))


def _grant_only_game() -> EngineSession:
    """A board where the one affordable recruit is affordable only through a producer's own grant.

    Outlying Farms yields 2 and can raise that to 4 as it bows, at the price of destroying itself.
    ``legal_actions`` offers the 4-cost card because ``reachable_gold`` counts the grant.
    """
    table = dealt_table()
    put_in_play(table, holding("of", owner=P1, printed_id="outlying_farms", gold_production=2))
    session = EngineSession.start(table, P1, seed=1)
    province_card(session.game, "target", seat=P1, gold_cost=4)
    return session


def test_a_grant_the_payment_needs_cannot_be_declined():
    """The engine offers the recruit because the grant reaches it, so announcing it commits the seat
    to taking it. The window refuses no, which is what stops even the placeholder agent — whose rule
    is the shortest answer that fits — from stranding a payment it already committed to."""
    session = _grant_only_game()
    controls = {seat: Controls(EconomicPolicy(), AutoAgent()) for seat in PlayerId}

    play_game(session, controls, turn_limit=1)

    table = session.game.table
    assert table.cards_by_id["target"] in table.battlefield.cards
    assert table.cards_by_id["of"] not in table.battlefield.cards


def test_a_recruit_only_a_grant_reaches_is_paid_for_and_completes():
    session = _grant_only_game()
    controls = {seat: Controls(EconomicPolicy(), PayingAgent()) for seat in PlayerId}

    play_game(session, controls, turn_limit=1)

    table = session.game.table
    assert table.cards_by_id["target"] in table.battlefield.cards
    # Outlying Farms took its own grant to pay, which destroys it.
    assert table.cards_by_id["of"] not in table.battlefield.cards


def test_a_grant_is_declined_when_plain_production_covers_the_cost():
    """The grant costs the producer whatever its card names, so it is never taken for convenience.
    The window still opens; the agent answers no and the Farm lives."""
    table = dealt_table()
    put_in_play(table, holding("of", owner=P1, printed_id="outlying_farms", gold_production=2))
    session = EngineSession.start(table, P1)
    province_card(session.game, "target", seat=P1, gold_cost=2)
    end_phase(session)
    end_phase(session)
    session.act(P1, Recruit("target"))

    pay(session, P1)

    table = session.game.table
    assert table.cards_by_id["target"] in table.battlefield.cards
    assert table.cards_by_id["of"] in table.battlefield.cards


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


def test_it_takes_the_grant_on_a_later_round_when_the_smallest_producer_cannot():
    """The greedy pick and the card with a grant need not be the same one. Bowing smallest-first
    hands over a producer with nothing to give, and the grant has to still be taken on the next
    round or the payment strands one Gold short."""
    state = dealt_table()
    put_in_play(state, holding("small", owner=P1, gold_production=1))
    put_in_play(state, holding("of", owner=P1, printed_id="outlying_farms", gold_production=2))
    session = EngineSession.start(state, P1)
    province_card(session.game, "target", seat=P1, gold_cost=5)
    end_phase(session)
    end_phase(session)
    session.act(P1, Recruit("target"))

    pay(session, P1)

    table = session.game.table
    assert table.cards_by_id["target"] in table.battlefield.cards
    assert table.cards_by_id["small"].bowed
    assert table.cards_by_id["of"] not in table.battlefield.cards  # took its grant, and paid
