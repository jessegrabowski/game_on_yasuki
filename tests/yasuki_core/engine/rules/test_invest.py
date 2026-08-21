import json

import pytest

from yasuki_core.engine.players import PlayerId
from yasuki_core.engine.table import DeckKey, TableState, ZoneKey, ZoneRole
from yasuki_core.engine.zones import ProvinceZone
from yasuki_core.game_pieces.constants import Side
from yasuki_core.game_pieces.cards import L5RCard
from yasuki_core.game_pieces.prints import HoldingPrint
from yasuki_core.engine.rules.abilities import InvestAbility, _INVEST, register_invest
from yasuki_core.engine.rules.actions import Recruit
from yasuki_core.engine.rules.decisions import ChooseInvestAmount, ChoosePayment, DecisionResponse
from yasuki_core.engine.rules.economy import effective_gold_cost
from yasuki_core.engine.rules.log import game_log_from_dict, game_log_to_dict
from yasuki_core.engine.session import EngineSession

from tests.yasuki_core.engine.builders import end_phase, put_in_play, register


@pytest.fixture(autouse=True)
def _clear_probe_registrations():
    """The Invest registry is module-global, so a probe registered here would price a real card in
    every later test in the process."""
    yield
    _INVEST.pop("free_invest_probe", None)


def _register_free_invest(printed_id: str):
    """Register a zero-cost Invest for ``printed_id``, returning the decorated effect."""

    def register(effect):
        register_invest(printed_id, InvestAbility(amounts=(0,), effect=effect))
        return effect

    return register


def _invest_game(holding_id: str, printed_id: str, gold_cost: int, producer_gp: int = 8):
    """A session in the Dynasty phase with a big producer and one face-up Invest holding to recruit."""
    state = TableState.empty_two_seat()
    state.decks[DeckKey(PlayerId.P1, Side.DYNASTY)].cards = [
        register(
            state,
            L5RCard.of(HoldingPrint, id="refill", name="R", side=Side.DYNASTY, owner=PlayerId.P1),
        )
    ]
    put_in_play(
        state,
        L5RCard.of(
            HoldingPrint,
            id="SH",
            name="SH",
            side=Side.DYNASTY,
            owner=PlayerId.P1,
            gold_production=producer_gp,
        ),
    )
    holding = register(
        state,
        L5RCard.of(
            HoldingPrint,
            id=holding_id,
            name=holding_id,
            side=Side.DYNASTY,
            owner=PlayerId.P1,
            printed_id=printed_id,
            gold_cost=gold_cost,
        ),
    )
    holding.turn_face_up()
    province = ProvinceZone(owner=PlayerId.P1)
    province.add(holding)
    state.zones[ZoneKey(PlayerId.P1, ZoneRole.PROVINCE, 0)] = province
    session = EngineSession.start(state, PlayerId.P1)
    end_phase(session)  # Action -> Battle
    end_phase(session)  # Battle -> Dynasty
    return session


def test_questionable_market_offers_recruit_and_invest_options():
    session = _invest_game("qm", "questionable_market", gold_cost=1)
    actions = session.legal_actions(PlayerId.P1)
    assert Recruit("qm") in actions  # the plain recruit
    assert Recruit("qm", invest=True) in actions  # the Invest second option


def test_investing_in_questionable_market_pays_the_invest_cost_for_two_tokens():
    session = _invest_game("qm", "questionable_market", gold_cost=1)
    session.act(PlayerId.P1, Recruit("qm", invest=True))

    pending = session.game.pending
    assert isinstance(pending, ChoosePayment) and pending.amount == 3  # base 1 + Invest 2
    session.submit(PlayerId.P1, DecisionResponse(("SH",)))

    qm = session.game.table.cards_by_id["qm"]
    assert qm in session.game.table.battlefield.cards
    assert qm.counters == {"wealth": 2}


def test_invest_is_not_offered_when_only_the_base_cost_is_affordable():
    session = _invest_game("qm", "questionable_market", gold_cost=1, producer_gp=2)
    actions = session.legal_actions(PlayerId.P1)
    assert Recruit("qm") in actions  # base 1 fits in 2 gold
    assert Recruit("qm", invest=True) not in actions  # base 1 + Invest 2 does not


def test_rebuilt_harbor_asks_how_much_to_invest():
    session = _invest_game("rh", "rebuilt_harbor", gold_cost=1)
    session.act(PlayerId.P1, Recruit("rh", invest=True))

    pending = session.game.pending
    assert isinstance(pending, ChooseInvestAmount)
    assert pending.candidates == ("1", "2", "3")  # 8 gold covers base 1 + up to 3


def test_rebuilt_harbor_grants_wealth_tokens_equal_to_the_amount_invested():
    session = _invest_game("rh", "rebuilt_harbor", gold_cost=1)
    session.act(PlayerId.P1, Recruit("rh", invest=True))
    session.submit(PlayerId.P1, DecisionResponse(("3",)))

    pending = session.game.pending
    assert isinstance(pending, ChoosePayment) and pending.amount == 4  # base 1 + chosen 3
    session.submit(PlayerId.P1, DecisionResponse(("SH",)))
    assert session.game.table.cards_by_id["rh"].counters == {"wealth": 3}


def test_variable_invest_amounts_are_capped_by_affordable_gold():
    session = _invest_game("rh", "rebuilt_harbor", gold_cost=1, producer_gp=3)
    session.act(PlayerId.P1, Recruit("rh", invest=True))
    assert session.game.pending.candidates == ("1", "2")  # base 1 + 3 = 4 is out of reach with 3


def test_cancelling_the_invest_amount_leaves_the_holding_in_its_province():
    session = _invest_game("rh", "rebuilt_harbor", gold_cost=1)
    session.act(PlayerId.P1, Recruit("rh", invest=True))
    assert isinstance(session.game.pending, ChooseInvestAmount)

    session.cancel(PlayerId.P1)
    assert session.game.pending is None
    assert session.game.stack == []  # the recruit was never announced
    assert session.game.table.cards_by_id["rh"] not in session.game.table.battlefield.cards

    restored = game_log_from_dict(json.loads(json.dumps(game_log_to_dict(session.log))))
    assert restored.replay() == session.game  # the cancelled Invest choice replays


def test_training_court_invests_for_one_token():
    # Courts of Otosan Uchi pays the same Invest for the same token and a Courtier besides, so it is
    # tested with the card rather than here, where the fixture loads no token templates.
    session = _invest_game("tc", "training_court", gold_cost=1)

    session.act(PlayerId.P1, Recruit("tc", invest=True))
    session.submit(PlayerId.P1, DecisionResponse(("SH",)))

    assert session.game.table.cards_by_id["tc"].counters == {"wealth": 1}


def test_fixed_invest_recruit_replays_and_round_trips():
    session = _invest_game("qm", "questionable_market", gold_cost=1)
    session.act(PlayerId.P1, Recruit("qm", invest=True))
    session.submit(PlayerId.P1, DecisionResponse(("SH",)))

    restored = game_log_from_dict(json.loads(json.dumps(game_log_to_dict(session.log))))
    assert restored.replay() == session.game


def test_variable_invest_recruit_replays_and_round_trips():
    session = _invest_game("rh", "rebuilt_harbor", gold_cost=1)
    session.act(PlayerId.P1, Recruit("rh", invest=True))
    session.submit(PlayerId.P1, DecisionResponse(("2",)))
    session.submit(PlayerId.P1, DecisionResponse(("SH",)))

    restored = game_log_from_dict(json.loads(json.dumps(game_log_to_dict(session.log))))
    assert restored.replay() == session.game


def test_investing_permanently_raises_the_holdings_gold_cost():
    """ "Entering play, permanently increase the Gold Cost by the Invest cost to get the effect." The
    rise is what pays for the effect, so a card that got the effect must show it."""
    session = _invest_game("qm", "questionable_market", gold_cost=1)
    session.act(PlayerId.P1, Recruit("qm", invest=True))
    session.submit(PlayerId.P1, DecisionResponse(("SH",)))

    qm = session.game.table.cards_by_id["qm"]
    assert qm.gold_cost == 1  # printed, untouched
    assert effective_gold_cost(session.game, qm) == 1 + 2  # plus the Invest paid


def test_recruiting_without_investing_leaves_the_gold_cost_alone():
    session = _invest_game("qm", "questionable_market", gold_cost=1)
    session.act(PlayerId.P1, Recruit("qm"))
    session.submit(PlayerId.P1, DecisionResponse(("SH",)))

    qm = session.game.table.cards_by_id["qm"]
    assert effective_gold_cost(session.game, qm) == 1


def test_a_variable_invest_raises_the_cost_by_what_was_actually_paid():
    session = _invest_game("rh", "rebuilt_harbor", gold_cost=1)
    session.act(PlayerId.P1, Recruit("rh", invest=True))
    session.submit(PlayerId.P1, DecisionResponse(("3",)))
    session.submit(PlayerId.P1, DecisionResponse(("SH",)))

    rh = session.game.table.cards_by_id["rh"]
    assert effective_gold_cost(session.game, rh) == 1 + 3


def test_the_invest_rise_survives_the_turn_that_bought_it():
    """Permanent, not until-end-of-turn: the modifier has to still be there next turn."""
    session = _invest_game("qm", "questionable_market", gold_cost=1)
    session.act(PlayerId.P1, Recruit("qm", invest=True))
    session.submit(PlayerId.P1, DecisionResponse(("SH",)))
    bought_on = session.game.turn
    for _ in range(4):
        end_phase(session)
    assert session.game.turn > bought_on  # the turn really did roll over

    qm = session.game.table.cards_by_id["qm"]
    assert effective_gold_cost(session.game, qm) == 3


def test_a_free_invest_still_buys_what_the_invest_buys():
    """Zero is a price, not a refusal: a card whose own text drops its Invest to nothing still buys
    what the Invest buys."""
    invested: list[int] = []

    @_register_free_invest("free_invest_probe")
    def _effect(game, source, amount):
        invested.append(amount)
        return []

    session = _invest_game("fi", "free_invest_probe", gold_cost=1)
    session.act(PlayerId.P1, Recruit("fi", invest=True))
    session.submit(PlayerId.P1, DecisionResponse(("SH",)))

    assert invested == [0]


def test_a_recruit_without_the_option_runs_no_invest_at_all():
    """The other side of the same distinction: no Invest is None, and None runs nothing."""
    invested: list[int] = []

    @_register_free_invest("free_invest_probe")
    def _effect(game, source, amount):
        invested.append(amount)
        return []

    session = _invest_game("fi", "free_invest_probe", gold_cost=1)
    session.act(PlayerId.P1, Recruit("fi"))
    session.submit(PlayerId.P1, DecisionResponse(("SH",)))

    assert invested == []
