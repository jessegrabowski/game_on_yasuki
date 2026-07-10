import json

from yasuki_core.engine.players import PlayerId
from yasuki_core.engine.table import DeckKey, TableState, ZoneKey, ZoneRole
from yasuki_core.engine.zones import ProvinceZone
from yasuki_core.game_pieces.constants import Side
from yasuki_core.game_pieces.dynasty import DynastyHolding
from yasuki_core.engine.rules.actions import ActivateAbility, Pass, Recruit
from yasuki_core.engine.rules.decisions import (
    ChooseAbilityTarget,
    ChooseCards,
    DecisionResponse,
)
from yasuki_core.engine.rules.log import game_log_from_dict, game_log_to_dict
from yasuki_core.engine.session import EngineSession


def _register(state, card):
    state.cards_by_id[card.id] = card
    return card


def _recruit_game(
    holding_id, printed_id, *, sincerity, keywords=("Sincerity",), gold_cost=2, gp=2, producer_gp=8
):
    """A Dynasty-phase session with a producer and a face-up Sincerity holding, pre-seeded with
    ``sincerity`` tokens, sitting in a province ready to recruit."""
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
            keywords=keywords,
            gold_cost=gold_cost,
            gold_production=gp,
            counters={"sincerity": sincerity} if sincerity else {},
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


def _recruit(session, holding_id):
    session.act(PlayerId.P1, Recruit(holding_id))
    session.submit(PlayerId.P1, DecisionResponse(("SH",)))  # bow the stronghold to pay


def test_sincerity_tokens_are_removed_when_the_card_enters_play():
    session = _recruit_game("s", "plain_sincerity", sincerity=2)  # no payoff trait of its own
    _recruit(session, "s")
    assert session.game.table.cards_by_id["s"].counters == {}  # tokens cleared on entry


def test_pawnbroker_turns_each_sincerity_token_into_a_wealth_token():
    session = _recruit_game("pb", "pawnbroker", sincerity=3, keywords=("Market", "Sincerity"), gp=0)
    _recruit(session, "pb")
    assert session.game.table.cards_by_id["pb"].counters == {"wealth": 3}  # 3 sincerity -> 3 wealth


def test_sapphire_mine_banks_a_wealth_token_from_two_or_more_sincerity():
    session = _recruit_game("sm", "sapphire_mine", sincerity=2, keywords=("Mine", "Sincerity"))
    _recruit(session, "sm")
    assert session.game.table.cards_by_id["sm"].counters == {"wealth": 1}


def test_sapphire_mine_banks_nothing_below_two_sincerity():
    session = _recruit_game("sm", "sapphire_mine", sincerity=1, keywords=("Mine", "Sincerity"))
    _recruit(session, "sm")
    assert session.game.table.cards_by_id["sm"].counters == {}  # 1 < 2: tokens gone, no wealth


def test_the_kurai_district_court_produces_gold_from_its_sincerity_on_entry():
    session = _recruit_game(
        "kd",
        "the_kurai_district_court",
        sincerity=3,
        keywords=("Court", "Sincerity"),
        gold_cost=2,
        gp=0,
        producer_gp=2,  # the payment bows exactly the cost, so the pool isolates the court's gold
    )
    _recruit(session, "kd")
    assert session.game.gold[PlayerId.P1] == 3  # produced one Gold per Sincerity token
    assert session.game.table.cards_by_id["kd"].counters == {}


def test_a_sincerity_payoff_recruit_replays_and_round_trips():
    session = _recruit_game("pb", "pawnbroker", sincerity=2, keywords=("Market", "Sincerity"), gp=0)
    _recruit(session, "pb")
    restored = game_log_from_dict(json.loads(json.dumps(game_log_to_dict(session.log))))
    assert restored.replay() == session.game


# --- Sincerity sources (Training Court on recruit, Shrine of Sincerity as an ability) ---


def _base_state():
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
                id="SH", name="SH", side=Side.DYNASTY, owner=PlayerId.P1, gold_production=8
            ),
        )
    )
    return state


def _province_card(state, card_id, printed_id, keywords, index, *, sincerity=0):
    card = _register(
        state,
        DynastyHolding(
            id=card_id,
            name=card_id,
            side=Side.DYNASTY,
            owner=PlayerId.P1,
            printed_id=printed_id,
            keywords=keywords,
            gold_cost=2,
            counters={"sincerity": sincerity} if sincerity else {},
        ),
    )
    card.turn_face_up()
    province = ProvinceZone(owner=PlayerId.P1)
    province.add(card)
    state.zones[ZoneKey(PlayerId.P1, ZoneRole.PROVINCE, index)] = province
    return card


def _to_dynasty(session):
    session.act(PlayerId.P1, Pass())  # Action -> Attack
    session.act(PlayerId.P1, Pass())  # Attack -> Dynasty


def test_training_court_seeds_a_sincerity_token_on_a_province_card():
    state = _base_state()
    _province_card(state, "tc", "training_court", ("Court",), index=0)
    _province_card(state, "target", "plain_sincerity", ("Sincerity",), index=1)
    session = EngineSession.start(state, PlayerId.P1)
    _to_dynasty(session)

    session.act(PlayerId.P1, Recruit("tc"))
    session.submit(PlayerId.P1, DecisionResponse(("SH",)))  # pay the base cost

    pending = session.game.pending
    assert isinstance(pending, ChooseCards) and pending.candidates == ("target",)
    session.submit(PlayerId.P1, DecisionResponse(("target",)))
    assert session.game.table.cards_by_id["target"].counters == {"sincerity": 1}


def test_training_court_seeds_nothing_without_a_token_less_sincerity_card():
    state = _base_state()
    _province_card(state, "tc", "training_court", ("Court",), index=0)
    _province_card(state, "seeded", "plain_sincerity", ("Sincerity",), index=1, sincerity=1)
    session = EngineSession.start(state, PlayerId.P1)
    _to_dynasty(session)

    session.act(PlayerId.P1, Recruit("tc"))
    session.submit(PlayerId.P1, DecisionResponse(("SH",)))
    assert session.game.pending is None  # the only Sincerity card already has a token


def test_training_court_seed_offers_every_token_less_sincerity_card():
    state = _base_state()
    _province_card(state, "tc", "training_court", ("Court",), index=0)
    _province_card(state, "a", "plain_sincerity", ("Sincerity",), index=1)
    _province_card(state, "b", "plain_sincerity", ("Sincerity",), index=2)
    session = EngineSession.start(state, PlayerId.P1)
    _to_dynasty(session)

    session.act(PlayerId.P1, Recruit("tc"))
    session.submit(PlayerId.P1, DecisionResponse(("SH",)))
    assert set(session.game.pending.candidates) == {"a", "b"}  # both token-less cards offered


def test_training_court_invest_applies_after_the_seed_choice_resolves():
    state = _base_state()
    _province_card(state, "tc", "training_court", ("Court",), index=0)
    _province_card(state, "target", "plain_sincerity", ("Sincerity",), index=1)
    session = EngineSession.start(state, PlayerId.P1)
    _to_dynasty(session)

    session.act(PlayerId.P1, Recruit("tc", invest=True))
    session.submit(PlayerId.P1, DecisionResponse(("SH",)))  # pay base + Invest 1
    assert isinstance(session.game.pending, ChooseCards)  # the seed pauses before the Invest effect
    session.submit(PlayerId.P1, DecisionResponse(("target",)))

    table = session.game.table
    assert table.cards_by_id["target"].counters == {"sincerity": 1}  # the seed resolved
    assert table.cards_by_id["tc"].counters == {"wealth": 1}  # Invest still landed, after the seed


def test_training_court_seed_replays_and_round_trips():
    state = _base_state()
    _province_card(state, "tc", "training_court", ("Court",), index=0)
    _province_card(state, "target", "plain_sincerity", ("Sincerity",), index=1)
    session = EngineSession.start(state, PlayerId.P1)
    _to_dynasty(session)
    session.act(PlayerId.P1, Recruit("tc"))
    session.submit(PlayerId.P1, DecisionResponse(("SH",)))
    session.submit(PlayerId.P1, DecisionResponse(("target",)))

    restored = game_log_from_dict(json.loads(json.dumps(game_log_to_dict(session.log))))
    assert restored.replay() == session.game


def test_shrine_of_sincerity_bows_to_seed_a_province_sincerity_card():
    state = _base_state()
    state.battlefield.add(
        _register(
            state,
            DynastyHolding(
                id="shrine",
                name="Shrine",
                side=Side.DYNASTY,
                owner=PlayerId.P1,
                printed_id="shrine_of_sincerity",
                keywords=("Temple",),
                gold_production=2,
            ),
        )
    )
    _province_card(state, "target", "plain_sincerity", ("Sincerity",), index=0)
    session = EngineSession.start(state, PlayerId.P1)
    _to_dynasty(session)  # Shrine's ability is a Dynasty action

    session.act(PlayerId.P1, ActivateAbility("shrine"))
    pending = session.game.pending
    assert isinstance(pending, ChooseAbilityTarget) and pending.candidates == ("target",)
    session.submit(PlayerId.P1, DecisionResponse(("target",)))

    assert session.game.table.cards_by_id["target"].counters == {"sincerity": 1}
    assert session.game.table.cards_by_id["shrine"].bowed  # the bow cost was paid


def test_shrine_is_not_activatable_without_a_token_less_sincerity_card():
    state = _base_state()
    state.battlefield.add(
        _register(
            state,
            DynastyHolding(
                id="shrine",
                name="Shrine",
                side=Side.DYNASTY,
                owner=PlayerId.P1,
                printed_id="shrine_of_sincerity",
                keywords=("Temple",),
                gold_production=2,
            ),
        )
    )
    _province_card(state, "seeded", "plain_sincerity", ("Sincerity",), index=0, sincerity=1)
    session = EngineSession.start(state, PlayerId.P1)
    _to_dynasty(session)

    assert ActivateAbility("shrine") not in session.legal_actions(PlayerId.P1)
