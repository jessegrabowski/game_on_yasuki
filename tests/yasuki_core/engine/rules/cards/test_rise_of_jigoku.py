from yasuki_core.engine.players import PlayerId
from yasuki_core.engine.table import TableState, DeckKey, ZoneKey, ZoneRole
from yasuki_core.engine.zones import ProvinceZone
from yasuki_core.engine.rules.actions import ActivateAbility, Recruit
from yasuki_core.engine.rules.decisions import (
    ChooseAbilityTarget,
    ChooseCards,
    ChoosePayment,
    DecisionResponse,
)
from yasuki_core.engine.rules.economy import effective_gold_production
from yasuki_core.engine.rules.log import replay
from yasuki_core.engine.session import EngineSession
from yasuki_core.game_pieces.constants import Side
from yasuki_core.game_pieces.cards import L5RCard
from yasuki_core.game_pieces.prints import HoldingPrint

from tests.yasuki_core.engine.builders import (
    end_phase,
    holding,
    put_in_play,
    register,
)

P1 = PlayerId.P1


def _rural_market_game(wealth=1):
    state = TableState.empty_two_seat()
    counters = {"wealth": wealth} if wealth else {}
    put_in_play(
        state,
        holding("rm", printed_id="rural_market", keywords=("Farm", "Market"), counters=counters),
    )
    put_in_play(
        state, holding("bf", printed_id="plain_farm", keywords=("Farm",), gold_production=2)
    )
    session = EngineSession.start(state, P1)
    session.game.table.cards_by_id["bf"].bow()  # bow after the start-of-turn straighten
    return session


def test_rural_market_spends_a_wealth_token_to_straighten_a_farm():
    session = _rural_market_game(wealth=1)
    session.act(P1, ActivateAbility("rm"))
    session.submit(P1, DecisionResponse(("bf",)))

    table = session.game.table
    assert not table.cards_by_id["bf"].bowed  # straightened
    assert table.cards_by_id["rm"].counters.get("wealth", 0) == 0  # the token was spent


def test_rural_market_is_not_activatable_without_a_wealth_token():
    session = _rural_market_game(wealth=0)
    assert ActivateAbility("rm") not in session.legal_actions(P1)


def _harvested_game(other_farms: int = 2) -> EngineSession:
    state = TableState.empty_two_seat()
    put_in_play(
        state, holding("hl", printed_id="harvested_land", keywords=("Farm",), gold_production=2)
    )
    for i in range(other_farms):
        put_in_play(
            state, holding(f"f{i}", printed_id="plain_farm", keywords=("Farm",), gold_production=2)
        )
    return EngineSession.start(state, P1)


def test_harvested_land_destroys_itself_to_boost_your_other_farms():
    session = _harvested_game(other_farms=2)
    session.act(P1, ActivateAbility("hl"))

    table = session.game.table
    assert session.game.pending is None  # untargeted — it hits every other Farm, no choice
    assert "hl" in {c.id for c in table.zones[ZoneKey(P1, ZoneRole.DYNASTY_DISCARD)].cards}
    assert effective_gold_production(session.game, table.cards_by_id["f0"]) == 3  # base 2 + 1
    assert effective_gold_production(session.game, table.cards_by_id["f1"]) == 3


def test_harvested_land_is_not_offered_without_another_farm():
    session = _harvested_game(other_farms=0)
    assert ActivateAbility("hl") not in session.legal_actions(P1)


def test_harvested_land_boost_expires_at_end_of_turn():
    session = _harvested_game(other_farms=1)
    session.act(P1, ActivateAbility("hl"))
    assert effective_gold_production(session.game, session.game.table.cards_by_id["f0"]) == 3

    for _ in range(3):  # end P1's turn — the boost outlives its destroyed source but not the turn
        end_phase(session)
    assert effective_gold_production(session.game, session.game.table.cards_by_id["f0"]) == 2


def test_harvested_land_activation_replays_to_the_same_state():
    session = _harvested_game(other_farms=2)
    session.act(P1, ActivateAbility("hl"))
    assert replay(session.log) == session.game


def _modest_farm_game(
    *,
    target_keywords=(),
    target_cost=2,
    with_producer=True,
    producer_gp=8,
    target_printed_id="plain_holding",
    extra_in_play=(),
):
    """An Action-phase session: P1's Modest Farm and a face-up Holding in a province to recruit
    through Modest Farm's ability. With ``with_producer`` a gold Holding of ``producer_gp`` yield is
    also in play to pay the recruit; without it, only Modest Farm's own (forfeited) production
    remains."""
    state = TableState.empty_two_seat()
    state.decks[DeckKey(P1, Side.DYNASTY)].cards = [
        register(
            state,
            L5RCard.of(HoldingPrint, id="refill", name="R", side=Side.DYNASTY, owner=P1),
        )
    ]
    if with_producer:
        put_in_play(
            state,
            L5RCard.of(
                HoldingPrint,
                id="SH",
                name="SH",
                side=Side.DYNASTY,
                owner=P1,
                gold_production=producer_gp,
            ),
        )
    put_in_play(
        state,
        L5RCard.of(
            HoldingPrint,
            id="mf",
            name="Modest Farm",
            side=Side.DYNASTY,
            owner=P1,
            printed_id="modest_farm",
            keywords=("Farm",),
            gold_production=1,
        ),
    )
    target = register(
        state,
        L5RCard.of(
            HoldingPrint,
            id="target",
            name="Target",
            side=Side.DYNASTY,
            owner=P1,
            printed_id=target_printed_id,
            keywords=target_keywords,
            gold_cost=target_cost,
            gold_production=2,
        ),
    )
    target.turn_face_up()
    province = ProvinceZone(owner=P1)
    province.add(target)
    state.zones[ZoneKey(P1, ZoneRole.PROVINCE, 0)] = province
    for card in extra_in_play:
        put_in_play(state, card)
    return EngineSession.start(state, P1)  # Action phase


def _drive_to_straighten_choice(session):
    session.act(P1, ActivateAbility("mf"))
    pending = session.game.pending
    assert isinstance(pending, ChooseAbilityTarget) and pending.candidates == ("target",)
    session.submit(P1, DecisionResponse(("target",)))
    pending = session.game.pending
    assert isinstance(pending, ChoosePayment) and pending.amount == 2  # X = the target's cost
    session.submit(P1, DecisionResponse(("SH",)))
    pending = session.game.pending
    assert isinstance(pending, ChooseCards) and pending.candidates == ("mf",)  # may destroy MF


def test_modest_farm_is_activatable_with_a_province_holding():
    session = _modest_farm_game()
    assert ActivateAbility("mf") in session.legal_actions(P1)


def test_modest_farm_is_not_activatable_while_bowed():
    session = _modest_farm_game()
    session.game.table.cards_by_id["mf"].bow()
    assert ActivateAbility("mf") not in session.legal_actions(P1)


def test_modest_farm_is_not_offered_when_no_target_is_affordable():
    # Modest Farm's cost is paying the target's recruit cost; with no producer to cover it (Modest
    # Farm bows itself out of the pool), the ability must not be offered — else the recruit would
    # wedge at an unpayable payment.
    session = _modest_farm_game(target_cost=3, with_producer=False)
    assert ActivateAbility("mf") not in session.legal_actions(P1)


def test_modest_farm_does_not_count_its_own_forfeited_production_as_affordability():
    # Producer gp2 + Modest Farm gp1 covers a cost-3 target only if Modest Farm's own yield counts —
    # but Modest Farm bows itself as the cost, so it cannot. The ability must not be offered.
    session = _modest_farm_game(target_cost=3, producer_gp=2)
    assert ActivateAbility("mf") not in session.legal_actions(P1)


def test_modest_farm_destroys_itself_to_recruit_the_target_unbowed():
    session = _modest_farm_game(target_keywords=("Farm",))
    _drive_to_straighten_choice(session)
    session.submit(P1, DecisionResponse(("mf",)))  # sacrifice Modest Farm

    table = session.game.table
    assert table.cards_by_id["target"] in table.battlefield.cards
    assert not table.cards_by_id["target"].bowed  # straightened by the sacrifice
    discard = table.zones[ZoneKey(P1, ZoneRole.DYNASTY_DISCARD)]
    assert "mf" in {c.id for c in discard.cards}  # Modest Farm destroyed


def test_modest_farm_can_be_kept_leaving_the_recruit_bowed():
    session = _modest_farm_game()
    _drive_to_straighten_choice(session)
    session.submit(P1, DecisionResponse(()))  # decline the sacrifice

    table = session.game.table
    assert table.cards_by_id["target"].bowed  # recruits enter bowed
    mf = table.cards_by_id["mf"]
    assert mf in table.battlefield.cards and mf.bowed  # Modest Farm kept, still bowed by its cost


def test_modest_farm_grants_a_farm_target_renew_refilling_its_province_face_up():
    session = _modest_farm_game(target_keywords=("Farm",))
    _drive_to_straighten_choice(session)
    session.submit(P1, DecisionResponse(()))

    refill = session.game.table.zones[ZoneKey(P1, ZoneRole.PROVINCE, 0)].cards[-1]
    assert refill.face_up  # Renew granted to the Farm target


def test_modest_farm_does_not_grant_renew_to_a_non_farm_target():
    session = _modest_farm_game(target_keywords=("Market",))
    _drive_to_straighten_choice(session)
    session.submit(P1, DecisionResponse(()))

    refill = session.game.table.zones[ZoneKey(P1, ZoneRole.PROVINCE, 0)].cards[-1]
    assert not refill.face_up  # no Renew for a non-Farm target


def test_modest_farm_activation_replays_to_the_same_state():
    session = _modest_farm_game(target_keywords=("Farm",))
    _drive_to_straighten_choice(session)
    session.submit(P1, DecisionResponse(("mf",)))
    assert replay(session.log) == session.game


def test_recruiting_a_renew_keyword_card_refills_its_province_face_up():
    # The general Renew rule: a normally-recruited card with the Renew keyword refills face-up.
    state = TableState.empty_two_seat()
    state.decks[DeckKey(P1, Side.DYNASTY)].cards = [
        register(
            state,
            L5RCard.of(HoldingPrint, id="refill", name="R", side=Side.DYNASTY, owner=P1),
        )
    ]
    put_in_play(
        state,
        L5RCard.of(
            HoldingPrint,
            id="SH",
            name="SH",
            side=Side.DYNASTY,
            owner=P1,
            gold_production=8,
        ),
    )
    renewer = register(
        state,
        L5RCard.of(
            HoldingPrint,
            id="warrens",
            name="W",
            side=Side.DYNASTY,
            owner=P1,
            keywords=("Renew",),
            gold_cost=1,
        ),
    )
    renewer.turn_face_up()
    province = ProvinceZone(owner=P1)
    province.add(renewer)
    state.zones[ZoneKey(P1, ZoneRole.PROVINCE, 0)] = province
    session = EngineSession.start(state, P1)
    end_phase(session)  # Action -> Battle
    end_phase(session)  # Battle -> Dynasty

    session.act(P1, Recruit("warrens"))
    session.submit(P1, DecisionResponse(("SH",)))
    refill = session.game.table.zones[ZoneKey(P1, ZoneRole.PROVINCE, 0)].cards[-1]
    assert refill.face_up


def _decision_sequence(session, answers):
    """Drive the session with ``answers`` and record every decision it paused on, as
    ``(request type name, candidates)``."""
    recorded = []
    for answer in answers:
        pending = session.game.pending
        recorded.append((type(pending).__name__, tuple(pending.candidates)))
        session.submit(P1, DecisionResponse(answer))
    return recorded


def test_modest_farm_recruit_puts_its_questions_in_a_fixed_order():
    # A characterization test: the recruited card's own enter-play trait must resolve *before*
    # Modest Farm offers its sacrifice. Both orderings leave the same final board, so only the
    # question order distinguishes them.
    session = _modest_farm_game(
        target_keywords=("Farm",),
        target_printed_id="wheat_farm",
        # Must be dealt before the session starts: EngineSession.start snapshots the table into the
        # log, so a card added afterwards is absent on replay.
        extra_in_play=(
            L5RCard.of(
                HoldingPrint,
                id="other-farm",
                name="Other Farm",
                side=Side.DYNASTY,
                owner=P1,
                keywords=("Farm",),
            ),
        ),
    )

    session.act(P1, ActivateAbility("mf"))
    sequence = _decision_sequence(
        session,
        answers=[("target",), ("SH",), ("other-farm",), ("mf",)],
    )

    assert sequence == [
        ("ChooseAbilityTarget", ("target",)),  # which Province Holding to recruit
        ("ChoosePayment", ("SH",)),  # pay its cost
        ("ChooseCards", ("mf", "other-farm")),  # Wheat Farm's own enter-play trait
        ("ChooseCards", ("mf",)),  # only then: destroy Modest Farm to straighten it?
    ]
    assert session.game.pending is None
    assert replay(session.log) == session.game  # the whole interleaving rebuilds from the tape
