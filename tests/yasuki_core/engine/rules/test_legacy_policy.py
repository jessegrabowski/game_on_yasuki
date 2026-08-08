from dataclasses import replace

from yasuki_core.engine.players import PlayerId
from yasuki_core.engine.rules.actions import Legacy, Pass, Recruit
from yasuki_core.engine.rules.agents import LegacyAgent, PayingAgent
from yasuki_core.engine.rules.decisions import (
    BanishForLegacy,
    ChooseLegacyCard,
    ChoosePayment,
    DecisionResponse,
    PlaceLegacy,
)
from yasuki_core.engine.rules.policies import EconomicLegacyPolicy
from yasuki_core.engine.runner import Controls, run_game
from yasuki_core.engine.session import EngineSession
from yasuki_core.engine.table import DeckKey
from yasuki_core.game_pieces.constants import Side

from tests.yasuki_core.engine.builders import (
    dealt_table,
    holding,
    province_card,
    put_in_play,
    register,
)

P1 = PlayerId.P1


def _dynasty_phase(production: int = 6) -> EngineSession:
    """A session parked in the Dynasty phase, where Legacy and recruits are both on offer."""
    table = dealt_table()
    put_in_play(table, holding("purse", owner=P1, gold_production=production))
    session = EngineSession.start(table, P1, seed=1)
    session.act(P1, Pass())
    session.act(P1, Pass())
    return session


def _legacy_card(card_id: str, production: int):
    return holding(card_id, owner=P1, keywords=("Legacy",), gold_production=production, gold_cost=3)


def _choose(session: EngineSession, pool):
    """The policy's choice with ``pool`` standing in for what the seat's search would find."""
    view = replace(session.project(P1), legacy_pool=tuple(pool))
    return EconomicLegacyPolicy().choose(view, session.legal_actions(P1))


# --- when the policy takes Legacy -----------------------------------------------------------------


def test_it_takes_legacy_when_the_pool_beats_the_board():
    session = _dynasty_phase()
    province_card(session.game, "onboard", seat=P1, gold_cost=3, gold_production=2)

    assert _choose(session, [_legacy_card("buried", production=5)]) == Legacy()


def test_it_declines_when_the_board_already_matches_the_pool():
    """Two cards to swap a 3-producer for another 3-producer is a trade the seat should refuse."""
    session = _dynasty_phase()
    province_card(session.game, "onboard", seat=P1, gold_cost=3, gold_production=3)

    assert _choose(session, [_legacy_card("buried", production=3)]) != Legacy()


def test_it_declines_when_the_board_beats_the_pool():
    session = _dynasty_phase()
    province_card(session.game, "onboard", seat=P1, gold_cost=3, gold_production=5)

    assert _choose(session, [_legacy_card("buried", production=2)]) != Legacy()


def test_an_empty_pool_vetoes_legacy_however_bare_the_board():
    """Searching with nothing to find loses the game outright, so this is a veto and not a weighing:
    even with no producer in sight the seat must not reach for it."""
    session = _dynasty_phase()

    assert _choose(session, []) != Legacy()


def test_it_buys_like_the_economic_policy_when_it_does_not_take_legacy():
    session = _dynasty_phase()
    province_card(session.game, "affordable", seat=P1, gold_cost=3, gold_production=4)

    assert _choose(session, []) == Recruit("affordable")


# --- how the agent answers the decisions Legacy raises --------------------------------------------


def test_the_agent_searches_out_the_biggest_producer():
    session = _dynasty_phase()
    # Ids deliberately sort against production, so picking the first candidate cannot pass.
    pool = [_legacy_card("a-weak", 1), _legacy_card("b-strong", 5), _legacy_card("c-mid", 3)]
    view = replace(session.project(P1), legacy_pool=tuple(pool))
    request = ChooseLegacyCard(seat=P1, candidates=("a-weak", "b-strong", "c-mid"))

    assert LegacyAgent().decide(request, view) == DecisionResponse(("b-strong",))


def test_the_agent_displaces_the_least_valuable_province_card():
    session = _dynasty_phase()
    province_card(session.game, "keep", seat=P1, gold_cost=3, gold_production=4)
    province_card(session.game, "spend", seat=P1, gold_cost=3, gold_production=0)
    view = session.project(P1)
    request = PlaceLegacy(seat=P1, candidates=("keep", "spend"), legacy_card_id="buried")

    assert LegacyAgent().decide(request, view) == DecisionResponse(("spend",))


def test_the_agent_banishes_deterministically():
    """The hand card's value is not modelled, so the choice only has to be reproducible."""
    session = _dynasty_phase()
    view = session.project(P1)
    request = BanishForLegacy(seat=P1, candidates=("h-c", "h-a", "h-b"))

    answers = {LegacyAgent().decide(request, view).choices for _ in range(3)}
    assert answers == {("h-a",)}


def test_the_agent_breaks_a_production_tie_toward_the_cheaper_card():
    """The fetched card still has to be paid for, so between equal producers the cheaper one is
    likelier to reach play the turn it is placed."""
    session = _dynasty_phase()
    pool = [
        holding("a-dear", owner=P1, keywords=("Legacy",), gold_production=3, gold_cost=6),
        holding("b-cheap", owner=P1, keywords=("Legacy",), gold_production=3, gold_cost=2),
    ]
    view = replace(session.project(P1), legacy_pool=tuple(pool))
    request = ChooseLegacyCard(seat=P1, candidates=("a-dear", "b-cheap"))

    assert LegacyAgent().decide(request, view) == DecisionResponse(("b-cheap",))


def test_the_agent_hands_everything_else_to_the_paying_agent():
    """A Legacy game still has to pay for what it recruits. Answering only the Legacy decisions and
    dropping the rest would strand the driver on the first ChoosePayment."""
    request = ChoosePayment(
        seat=P1, candidates=("purse",), amount=4, available=0, produced=(("purse", 6),), label="x"
    )

    assert LegacyAgent().decide(request, view=None) == PayingAgent().decide(request, view=None)


def test_a_driven_game_takes_legacy_and_runs_to_the_turn_limit():
    """The whole path in one go: the policy announces Legacy, the agent answers all three decisions,
    and the placement leaves a table the engine can keep playing on. A whiff would end the game
    early, so reaching the limit is what says the pool veto held."""
    session = _dynasty_phase()
    for index in range(3):
        province_card(session.game, f"buy-{index}", seat=P1, gold_cost=2, gold_production=1)
    deck = session.game.table.decks[DeckKey(P1, Side.DYNASTY)]
    deck.cards.append(register(session.game.table, _legacy_card("buried", production=6)))

    log = []
    controls = {seat: Controls(EconomicLegacyPolicy(), LegacyAgent()) for seat in PlayerId}
    for step in run_game(session, controls, turn_limit=4):
        log.append(step)

    assert any(isinstance(getattr(step, "action", None), Legacy) for step in log)
    assert not session.game.game_over  # no whiff: the search always had something to find
