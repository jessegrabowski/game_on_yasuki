from yasuki_core.engine.players import PlayerId
from yasuki_core.engine.rules.actions import Action, Pass, Recruit
from yasuki_core.engine.rules.agents import AutoAgent
from yasuki_core.engine.rules.policies import EconomicPolicy, PassPolicy
from yasuki_core.engine.runner import Controls, play_game
from yasuki_core.engine.session import EngineSession
from yasuki_core.sim.metrics import provinces_cleared
from yasuki_core.sim.recording import TurnRecorder

from yasuki_core.engine.table import DeckKey, ZoneKey, ZoneRole
from yasuki_core.engine.zones import ProvinceZone
from yasuki_core.game_pieces.constants import Side
from yasuki_core.game_pieces.cards import L5RCard
from yasuki_core.game_pieces.prints import PersonalityPrint

from tests.yasuki_core.engine.builders import (
    dealt_table,
    end_phase,
    holding,
    province_card,
    put_in_play,
    register,
)

P1, P2 = PlayerId.P1, PlayerId.P2


def _dynasty_phase(production: int = 6) -> EngineSession:
    """A session parked in the Dynasty phase, where recruits are on offer."""
    table = dealt_table()
    put_in_play(table, holding("purse", owner=P1, gold_production=production))
    session = EngineSession.start(table, P1, seed=1)
    end_phase(session)
    end_phase(session)
    return session


def _choice(session: EngineSession) -> Action:
    return EconomicPolicy().choose(session.project(P1), session.legal_actions(P1))


def test_it_recruits_when_it_can_afford_to():
    session = _dynasty_phase()
    province_card(session.game, "affordable", seat=P1, gold_cost=3)

    assert _choice(session) == Recruit("affordable")


def test_it_passes_when_nothing_is_affordable():
    """Nothing on the board is within reach, so there is no Recruit to choose. A policy that ranked
    without a fallback would raise here, and one that invented an action would be refused."""
    session = _dynasty_phase(production=1)
    province_card(session.game, "dear", seat=P1, gold_cost=9)

    assert not [a for a in session.legal_actions(P1) if isinstance(a, Recruit)]
    assert _choice(session) == Pass()


def test_it_takes_the_dearer_of_two_it_can_afford():
    # The heuristic itself: among cards it could equally buy, cost decides.
    session = _dynasty_phase()
    province_card(session.game, "cheap", seat=P1, gold_cost=2, index=0)
    province_card(session.game, "dear", seat=P1, gold_cost=5, index=1)

    assert _choice(session) == Recruit("dear")


def test_a_producer_beats_a_dearer_card_that_produces_nothing():
    """Production outranks cost, which is what makes this an economic policy rather than a greedy
    one. Ranking on cost alone would take the barren card and starve the following turns."""
    session = _dynasty_phase()
    province_card(session.game, "barren", seat=P1, gold_cost=6, index=0)
    province_card(session.game, "farm", seat=P1, gold_cost=3, index=1, gold_production=2)

    assert _choice(session) == Recruit("farm")


def test_it_takes_the_plain_purchase_over_the_invest_variant():
    """Training Court offers both. Investing costs more gold and raises a second decision the
    payment has to answer, so the policy commits to the plain purchase."""
    session = _dynasty_phase()
    province_card(session.game, "court", seat=P1, printed_id="training_court", gold_cost=3)
    offered = session.legal_actions(P1)

    assert Recruit("court", invest=True) in offered  # the variant is genuinely on the table
    assert EconomicPolicy().choose(session.project(P1), offered) == Recruit("court")


def test_the_id_breaks_a_tie_rather_than_zone_order():
    """Two cards the ranking cannot separate. The one in the later province wins on its id, so a
    seeded run reproduces instead of following whatever order the zones happen to iterate in."""
    session = _dynasty_phase()
    province_card(session.game, "twin_b", seat=P1, gold_cost=3, index=0)
    province_card(session.game, "twin_a", seat=P1, gold_cost=3, index=1)

    assert _choice(session) == Recruit("twin_a")


def _buyable_game() -> EngineSession:
    table = dealt_table()
    put_in_play(table, holding("purse", owner=P1, gold_production=4))
    session = EngineSession.start(table, P1, seed=1)
    # Stocked so a bought province refills face-down. Left empty, it reads as an exhausted deck
    # instead and provinces_cleared counts nothing.
    session.game.table.decks[DeckKey(P1, Side.DYNASTY)].cards = [
        register(session.game.table, holding(f"deck{i}", owner=P1, gold_cost=2)) for i in range(9)
    ]
    for index in range(3):
        province_card(session.game, f"prov{index}", seat=P1, gold_cost=2, index=index)
    return session


def _cleared(policy) -> list[int]:
    session = _buyable_game()
    recorder = TurnRecorder({}, end_of_turn={"cleared": provinces_cleared})
    controls = {seat: Controls(policy, AutoAgent()) for seat in PlayerId}
    play_game(session, controls, turn_limit=3, observer=recorder)
    return [value for _, value in recorder.series(P1, "cleared")]


def test_a_game_under_this_policy_differs_from_one_that_only_passes():
    """The point of the step. Asserted as a direction rather than an exact count, so tuning the
    heuristic does not break the test that proves the heuristic does anything at all."""
    passive = sum(_cleared(PassPolicy()))

    assert passive == 0
    assert sum(_cleared(EconomicPolicy())) > passive


def test_a_face_down_province_neighbor_does_not_stop_it_choosing():
    """A province refilled after a purchase is face-down, and reaches even its own owner redacted —
    with no name, no cost, and nothing to rank. Reading one as though it were a card crashes the
    policy on the turn after its first buy, which no all-face-up board reveals."""
    session = _dynasty_phase()
    province_card(session.game, "refilled", seat=P1, gold_cost=2, index=0, face_up=False)
    province_card(session.game, "visible", seat=P1, gold_cost=3, index=1)

    assert _choice(session) == Recruit("visible")


def test_a_personality_is_ranked_without_gold_production():
    """Gold Production lives only on Holdings, and a Personality is offered as a recruit like any
    other province card. Ranking one must not assume the field is there — a Holding that produces
    still wins, even at a lower cost."""
    session = _dynasty_phase()
    hero = register(
        session.game.table,
        L5RCard.of(
            PersonalityPrint, id="hero", name="Hero", side=Side.DYNASTY, owner=P1, gold_cost=5
        ),
    )
    hero.turn_face_up()
    zone = ProvinceZone(owner=P1)
    zone.add(hero)
    session.game.table.zones[ZoneKey(P1, ZoneRole.PROVINCE, 0)] = zone
    province_card(session.game, "farm", seat=P1, gold_cost=3, index=1, gold_production=1)

    assert not hasattr(hero, "gold_production")  # the premise the ranking has to survive
    assert _choice(session) == Recruit("farm")


def test_a_card_printed_with_a_dash_cost_ranks_as_free():
    """A dash means no printed cost at all, which the engine charges as nothing. It has to rank
    rather than raise, and it loses to any card with a real price behind it."""
    session = _dynasty_phase()
    province_card(session.game, "dash", seat=P1, gold_cost=None, index=0)
    province_card(session.game, "priced", seat=P1, gold_cost=4, index=1)

    assert _choice(session) == Recruit("priced")


def test_a_province_card_is_ranked_on_what_it_produces_now_not_what_it_printed():
    """The policy sees only a view, and a view used to carry no modifiers at all — so a card
    carrying Wealth was weighed at its printed number and passed over for a card that is worth
    less."""
    session = _dynasty_phase()
    province_card(session.game, "boosted", seat=P1, gold_cost=2, gold_production=1, index=0)
    province_card(session.game, "plain", seat=P1, gold_cost=2, gold_production=2, index=1)
    session.game.table.cards_by_id["boosted"].adjust_counter("wealth", 3)

    assert _choice(session) == Recruit("boosted")  # 1 printed + 3 Wealth beats a printed 2
