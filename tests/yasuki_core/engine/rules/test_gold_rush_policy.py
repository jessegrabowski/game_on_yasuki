from dataclasses import replace

from yasuki_core.engine.players import PlayerId
from yasuki_core.engine.rules.actions import (
    Action,
    ActivateAbility,
    DynastyDiscard,
    Legacy,
    Pass,
    Recruit,
)
from yasuki_core.engine.rules.decisions import ChooseAbilityTarget, ChooseCards
from yasuki_core.engine.rules.policies import GoldRushPolicy
from yasuki_core.engine.session import EngineSession
from yasuki_core.engine.table import ZoneKey, ZoneRole
from yasuki_core.engine.zones import ProvinceZone

from tests.yasuki_core.engine.builders import (
    dealt_table,
    end_phase,
    holding,
    personality,
    province_card,
    put_in_play,
    register,
)

P1 = PlayerId.P1


def _dynasty_phase(production: int = 6) -> EngineSession:
    """A session parked in the Dynasty phase, where recruits and discards are both on offer."""
    table = dealt_table()
    put_in_play(table, holding("purse", owner=P1, gold_production=production))
    session = EngineSession.start(table, P1, seed=1)
    end_phase(session)
    end_phase(session)
    return session


def _choice(session: EngineSession, pool=()) -> Action:
    """The policy's choice, with ``pool`` standing in for what a Legacy search would find."""
    view = replace(session.project(P1), legacy_pool=tuple(pool))
    return GoldRushPolicy().choose(view, session.legal_actions(P1))


def test_it_buys_when_it_can_afford_to():
    session = _dynasty_phase()
    province_card(session.game, "farm", seat=P1, gold_cost=3, gold_production=2)

    assert _choice(session) == Recruit("farm")


def test_it_flushes_a_card_that_produces_nothing_when_it_cannot_buy():
    """The whole point of the policy: without a discard the Province stays clogged for the rest of
    the game and the seat plays on with fewer slots than it has."""
    session = _dynasty_phase(production=1)
    province_card(session.game, "barren", seat=P1, gold_cost=9)

    assert _choice(session) == DynastyDiscard("barren")


def test_it_keeps_a_producer_it_cannot_yet_afford():
    # Discarding here would throw away the production the policy exists to chase; the card is
    # bought a turn later once the board can reach it.
    session = _dynasty_phase(production=1)
    province_card(session.game, "dear-farm", seat=P1, gold_cost=9, gold_production=4)

    assert _choice(session) == Pass()


def test_it_buys_before_it_flushes():
    # Both are on offer, and only the purchase converts the turn's Gold into board production.
    session = _dynasty_phase()
    province_card(session.game, "barren", seat=P1, gold_cost=2, index=0)
    province_card(session.game, "farm", seat=P1, gold_cost=3, index=1, gold_production=2)

    assert _choice(session) == Recruit("farm")


def test_it_flushes_the_lowest_id_when_several_are_barren():
    # Ties settle on the id rather than on zone order, so a run stays reproducible.
    session = _dynasty_phase(production=1)
    # Id order deliberately matches neither end of the zone order, so taking the first or the last
    # offered discard would pick a different card.
    province_card(session.game, "mid", seat=P1, gold_cost=9, index=0)
    province_card(session.game, "alpha", seat=P1, gold_cost=9, index=1)
    province_card(session.game, "zeta", seat=P1, gold_cost=9, index=2)

    assert _choice(session) == DynastyDiscard("alpha")


def test_it_takes_legacy_ahead_of_a_purchase_when_the_pool_beats_the_board():
    session = _dynasty_phase()
    province_card(session.game, "onboard", seat=P1, gold_cost=3, gold_production=2)
    buried = holding("buried", owner=P1, keywords=("Legacy",), gold_production=5, gold_cost=3)

    assert _choice(session, [buried]) == Legacy()


def test_it_declines_legacy_the_board_already_beats():
    session = _dynasty_phase()
    province_card(session.game, "onboard", seat=P1, gold_cost=3, gold_production=5)
    buried = holding("buried", owner=P1, keywords=("Legacy",), gold_production=2, gold_cost=3)

    assert _choice(session, [buried]) == Recruit("onboard")


def test_it_passes_when_it_can_neither_buy_nor_usefully_flush():
    session = _dynasty_phase(production=1)
    province_card(session.game, "dear-farm", seat=P1, gold_cost=9, gold_production=4, index=0)

    assert _choice(session) == Pass()


def _personality(session: EngineSession, card_id: str, *, gold_cost: int, index: int = 0):
    """Put a Personality — a province card with no Gold Production at all — into a province."""
    card = register(
        session.game.table,
        personality(card_id, owner=P1, gold_cost=gold_cost),
    )
    card.turn_face_up()
    zone = ProvinceZone(owner=P1)
    zone.add(card)
    session.game.table.zones[ZoneKey(P1, ZoneRole.PROVINCE, index)] = zone
    return card


def test_it_buys_a_personality_when_no_holding_is_on_offer():
    """Gold it cannot turn into production is better spent on a body than left in the pool, and
    buying clears the province either way."""
    session = _dynasty_phase()
    _personality(session, "hero", gold_cost=4)

    assert _choice(session) == Recruit("hero")


def test_a_holding_still_outranks_an_affordable_personality():
    session = _dynasty_phase()
    _personality(session, "hero", gold_cost=5, index=0)
    province_card(session.game, "farm", seat=P1, gold_cost=3, index=1, gold_production=1)

    assert _choice(session) == Recruit("farm")


def test_it_flushes_every_barren_card_it_could_not_buy():
    """One choice per window, so clearing three provinces takes three of them — and the seat must
    still be offered the discard after the first, or the rest sit there for the whole game."""
    session = _dynasty_phase(production=1)
    for index, card_id in enumerate(("one", "two", "three")):
        province_card(session.game, card_id, seat=P1, gold_cost=9, index=index)
    policy = GoldRushPolicy()

    flushed = []
    while True:
        choice = policy.choose(session.project(P1), session.legal_actions(P1))
        if isinstance(choice, Pass):
            break
        assert isinstance(choice, DynastyDiscard)
        flushed.append(choice.card_id)
        session.act(P1, choice)

    assert sorted(flushed) == ["one", "three", "two"]


# --- activated abilities -------------------------------------------------------------------------


def _action_phase(production: int = 8, farm_gp: int = 1) -> EngineSession:
    """An Action-phase session where P1 holds Modest Farm and a producer to pay with. The Action
    Phase is the only round permitting Open actions, which every economy ability here is."""
    table = dealt_table()
    put_in_play(table, holding("purse", owner=P1, gold_production=production))
    put_in_play(
        table,
        holding(
            "mf", owner=P1, printed_id="modest_farm", keywords=("Farm",), gold_production=farm_gp
        ),
    )
    return EngineSession.start(table, P1, seed=1)


def test_it_activates_modest_farm_for_a_farm_it_can_reach():
    session = _action_phase()
    province_card(session.game, "barn", seat=P1, gold_cost=3, gold_production=2, keywords=("Farm",))

    assert _choice(session) == ActivateAbility("mf")


def test_it_leaves_modest_farm_alone_for_a_target_that_would_refill_face_down():
    """Only a Farm target is granted Renew, and only Renew refills the vacated Province face-up.
    Recruiting anything else early spends Modest Farm's Gold to go down to three live Provinces for
    the rest of the turn."""
    session = _action_phase()
    province_card(session.game, "market", seat=P1, gold_cost=3, gold_production=4)

    assert ActivateAbility("mf") in session.legal_actions(P1)  # the engine offers it
    assert _choice(session) == Pass()  # the policy declines


def test_it_leaves_modest_farm_alone_when_its_own_yield_is_what_would_pay():
    # Modest Farm bows itself as the cost, so the Farm costing exactly the board's reach is out of
    # reach by its own yield. Counting that yield would activate into an unpayable recruit.
    session = _action_phase(production=3, farm_gp=1)
    province_card(session.game, "barn", seat=P1, gold_cost=4, gold_production=2, keywords=("Farm",))

    assert _choice(session) == Pass()


def test_it_never_activates_an_ability_it_has_no_model_for():
    """A policy cannot read what a card does, so an unmodelled ability is left alone rather than
    guessed at — otherwise every new card silently changes every deck's numbers. Harvested Land is
    given the lower id, so passing it over is the model talking and not the tie-break."""
    session = _action_phase()
    put_in_play(
        session.game,
        holding("aa", owner=P1, printed_id="harvested_land", keywords=("Farm",), gold_production=1),
    )
    province_card(session.game, "barn", seat=P1, gold_cost=3, gold_production=2, keywords=("Farm",))
    offered = session.legal_actions(P1)

    assert ActivateAbility("aa") in offered  # the engine offers it
    assert GoldRushPolicy().choose(session.project(P1), offered) == ActivateAbility("mf")


def _millet_session(purse: int, cost: int) -> EngineSession:
    """P1 holding Millet Farm and a straight Farm to give its bonus to, against a Province card
    priced at ``cost``."""
    session = _action_phase(production=purse)
    put_in_play(
        session.game,
        holding("mill", owner=P1, printed_id="millet_farm", keywords=("Farm",), gold_production=1),
    )
    province_card(session.game, "market", seat=P1, gold_cost=cost, gold_production=3)
    return session


def test_it_gives_millet_farms_bonus_when_it_puts_a_card_in_reach():
    # Nine straight Gold, and Millet Farm bows one of it away to add two: eleven, which is what the
    # card costs and what the board could not otherwise reach.
    session = _millet_session(purse=8, cost=11)

    assert _choice(session) == ActivateAbility("mill")


def test_it_declines_millet_farms_bonus_when_the_seat_could_already_pay():
    """The grant expires at end of turn, so spending a bow on Gold the seat already had is a bow
    thrown away — and Millet Farm bows itself out of the pool to give it."""
    session = _millet_session(purse=8, cost=4)

    assert ActivateAbility("mill") in session.legal_actions(P1)
    assert _choice(session) != ActivateAbility("mill")


def test_it_targets_the_farm_over_a_larger_producer():
    """Renew is what makes the ability pay, and only a Farm target receives it — so the Farm wins
    even against a Holding that produces more."""
    session = _action_phase()
    province_card(session.game, "barn", seat=P1, gold_cost=3, gold_production=1, keywords=("Farm",))
    province_card(session.game, "market", seat=P1, gold_cost=4, gold_production=5, index=1)
    request = ChooseAbilityTarget(seat=P1, candidates=("market", "barn"), source_card_id="mf")

    assert GoldRushPolicy().decide(request, session.project(P1)).choices == ("barn",)


def test_it_gives_millet_farms_bonus_to_a_farm_still_able_to_use_it():
    """The bonus is only collected by bowing the Farm that receives it, so a bowed Farm is the one
    candidate that wastes it outright."""
    session = _action_phase()
    put_in_play(
        session.game,
        holding("mill", owner=P1, printed_id="millet_farm", keywords=("Farm",), gold_production=1),
    )
    session.game.table.cards_by_id["mf"].bow()
    request = ChooseAbilityTarget(seat=P1, candidates=("mf", "mill"), source_card_id="mill")

    assert GoldRushPolicy().decide(request, session.project(P1)).choices == ("mill",)


def _straighten_request(target_id: str) -> ChooseCards:
    return ChooseCards(
        seat=P1,
        candidates=("mf",),
        minimum=0,
        maximum=1,
        resolver="modest_farm_straighten",
        source_id=target_id,
    )


def test_it_keeps_modest_farm_when_straightening_the_target_buys_nothing():
    """Modest Farm straightens every turn its owner's begins, so each one is another out-of-sequence
    recruit. Trading that engine for one turn of a straight target is only worth it when that turn
    buys something."""
    session = _action_phase()
    barn = province_card(
        session.game, "barn", seat=P1, gold_cost=3, gold_production=2, keywords=("Farm",)
    )
    put_in_play(session.game, barn)
    barn.bow()  # a recruit enters play bowed, which is what the sacrifice would undo
    session.game.table.cards_by_id["mf"].bow()  # bowed as the ability's cost

    response = GoldRushPolicy().decide(_straighten_request("barn"), session.project(P1))

    assert response.choices == ()


def test_it_sacrifices_modest_farm_when_the_straightened_target_unlocks_a_purchase():
    session = _action_phase(production=2)
    barn = province_card(
        session.game, "barn", seat=P1, gold_cost=2, gold_production=3, keywords=("Farm",)
    )
    put_in_play(session.game, barn)
    barn.bow()
    session.game.table.cards_by_id["mf"].bow()
    # Out of reach of the two straight Gold on the board, within reach of it plus the Farm's three.
    province_card(session.game, "dear", seat=P1, gold_cost=4, gold_production=4, index=1)

    response = GoldRushPolicy().decide(_straighten_request("barn"), session.project(P1))

    assert response.choices == ("mf",)


def test_it_declines_when_the_only_affordable_target_is_not_the_farm():
    """The engine offers the ability once *any* Holding is within reach; the policy wants the Farm
    within reach, and Modest Farm's own forfeited yield is exactly the gap between the two. Reading
    the board's reach without that subtraction activates into a non-Farm target."""
    session = _action_phase(production=3, farm_gp=1)
    province_card(session.game, "barn", seat=P1, gold_cost=4, gold_production=2, keywords=("Farm",))
    province_card(session.game, "market", seat=P1, gold_cost=3, gold_production=2, index=1)

    assert ActivateAbility("mf") in session.legal_actions(P1)  # the Market keeps it on offer
    assert _choice(session) != ActivateAbility("mf")


def test_it_declines_millet_farms_bonus_when_every_other_farm_is_already_bowed():
    """A bowed Farm cannot be bowed again to collect the bonus, so the grant would expire unspent —
    even though the Gold it would add is exactly what the Market is out of reach by. The purse
    carries the Gold the bowed Farm no longer does, so the only thing separating this from the case
    above is which Farm can still be bowed."""
    session = _millet_session(purse=9, cost=11)
    session.game.table.cards_by_id["mf"].bow()

    assert ActivateAbility("mill") in session.legal_actions(P1)
    assert _choice(session) != ActivateAbility("mill")


def _fortification(session: EngineSession, card_id: str, index: int):
    """A six-for-six Holding that is not a Farm, so recruiting it refills its Province face-down."""
    return province_card(
        session.game,
        card_id,
        seat=P1,
        gold_cost=6,
        gold_production=6,
        keywords=("Fortification",),
        index=index,
    )


def test_it_takes_a_non_farm_that_chains_into_a_second_producer():
    """Destroying Modest Farm straightens what it recruited, so the first Fortification's six Gold
    pays for the second — which eight Gold on the board could not have done alone."""
    session = _action_phase(production=6, farm_gp=1)
    put_in_play(
        session.game,
        holding("mf2", owner=P1, printed_id="modest_farm", keywords=("Farm",), gold_production=1),
    )
    _fortification(session, "fort0", 0)
    _fortification(session, "fort1", 1)

    assert _choice(session) == ActivateAbility("mf")


def test_it_declines_a_non_farm_with_nothing_on_the_other_side_of_it():
    # The same Fortification, alone: recruiting it early spends Modest Farm's Gold and turns its
    # Province face-down, and the straightened six Gold has nothing left to buy.
    session = _action_phase(production=6, farm_gp=1)
    _fortification(session, "fort0", 0)

    assert ActivateAbility("mf") in session.legal_actions(P1)
    assert _choice(session) != ActivateAbility("mf")


def test_it_declines_a_chain_whose_target_barely_beats_the_farm_it_spends():
    """A two-Gold target chains as readily as a six-Gold one, and is not worth the Province turning
    face-down for the rest of the turn — so the target has to be worth several Modest Farms."""
    session = _action_phase(production=6, farm_gp=1)
    province_card(session.game, "shop", seat=P1, gold_cost=2, gold_production=2, index=0)
    province_card(session.game, "next", seat=P1, gold_cost=5, gold_production=2, index=1)

    assert ActivateAbility("mf") in session.legal_actions(P1)
    assert _choice(session) != ActivateAbility("mf")


def test_it_declines_a_chain_that_only_unlocks_a_card_producing_nothing():
    """The chain has to end in production. Spending Modest Farm and a face-up Province to reach a
    Personality a turn earlier converts a permanent producer into a body."""
    session = _action_phase(production=6, farm_gp=1)
    _fortification(session, "fort0", 0)
    _personality(session, "hero", gold_cost=4, index=1)

    assert ActivateAbility("mf") in session.legal_actions(P1)
    assert _choice(session) != ActivateAbility("mf")
