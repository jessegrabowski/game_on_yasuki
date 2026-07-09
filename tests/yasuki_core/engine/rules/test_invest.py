import json

from yasuki_core.engine.players import PlayerId
from yasuki_core.engine.table import DeckKey, TableState, ZoneKey, ZoneRole
from yasuki_core.engine.zones import ProvinceZone
from yasuki_core.game_pieces.constants import Side
from yasuki_core.game_pieces.dynasty import DynastyHolding
from yasuki_core.engine.rules.actions import Pass, Recruit
from yasuki_core.engine.rules.decisions import ChooseInvestAmount, ChoosePayment, DecisionResponse
from yasuki_core.engine.rules.log import game_log_from_dict, game_log_to_dict
from yasuki_core.engine.session import EngineSession


def _register(state: TableState, card):
    state.cards_by_id[card.id] = card
    return card


def _invest_game(holding_id: str, printed_id: str, gold_cost: int, producer_gp: int = 8):
    """A session in the Dynasty phase with a big producer and one face-up Invest holding to recruit."""
    state = TableState.empty_two_seat()
    state.decks[DeckKey(PlayerId.P1, Side.DYNASTY)].cards = [
        _register(
            state, DynastyHolding(id="refill", name="R", side=Side.DYNASTY, owner=PlayerId.P1)
        )
    ]
    state.battlefield.add(
        _register(
            state,
            DynastyHolding(
                id="SH",
                name="SH",
                side=Side.DYNASTY,
                owner=PlayerId.P1,
                gold_production=producer_gp,
            ),
        )
    )
    holding = _register(
        state,
        DynastyHolding(
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
    session.act(PlayerId.P1, Pass())  # Action -> Attack
    session.act(PlayerId.P1, Pass())  # Attack -> Dynasty
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


def test_training_court_and_courts_each_invest_for_one_token():
    for holding_id, printed_id in [("tc", "training_court"), ("co", "courts_of_otosan_uchi")]:
        session = _invest_game(holding_id, printed_id, gold_cost=1)
        session.act(PlayerId.P1, Recruit(holding_id, invest=True))
        session.submit(PlayerId.P1, DecisionResponse(("SH",)))
        assert session.game.table.cards_by_id[holding_id].counters == {"wealth": 1}


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
