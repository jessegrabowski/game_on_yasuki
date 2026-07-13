import json

from yasuki_core.engine.players import PlayerId
from yasuki_core.engine.table import DeckKey, TableState, ZoneKey, ZoneRole
from yasuki_core.engine.zones import ProvinceZone
from yasuki_core.game_pieces.constants import Side
from yasuki_core.game_pieces.dynasty import DynastyHolding
from yasuki_core.game_pieces.fate import FateCard
from yasuki_core.game_pieces.counters import SINCERITY, counter_from_key
from yasuki_core.engine.rules import flow
from yasuki_core.engine.rules.actions import Pass
from yasuki_core.engine.rules.log import game_log_from_dict, game_log_to_dict
from yasuki_core.engine.rules.state import GameState
from yasuki_core.engine.session import EngineSession


def _game():
    return GameState.start(TableState.empty_two_seat(), PlayerId.P1)


def _province_card(
    game, card_id, *, seat=PlayerId.P1, keywords=("Sincerity",), face_up=True, index=0
):
    card = DynastyHolding(
        id=card_id, name=card_id, side=Side.DYNASTY, owner=seat, keywords=keywords
    )
    card.turn_face_up() if face_up else card.turn_face_down()
    game.table.cards_by_id[card.id] = card
    key = ZoneKey(seat, ZoneRole.PROVINCE, index)
    zone = game.table.zones.get(key) or ProvinceZone(owner=seat)
    game.table.zones[key] = zone
    zone.add(card)
    return card


def test_sincerity_counter_is_registered_and_grants_no_gold():
    assert counter_from_key("sincerity") is SINCERITY
    assert SINCERITY.gold_production == 0  # a resource, not a gold source


def test_end_of_turn_gives_a_face_up_sincerity_province_card_a_token():
    game = _game()
    card = _province_card(game, "s")

    flow._end_turn(game)

    assert card.counters == {"sincerity": 1}


def test_a_face_down_province_card_does_not_accrue():
    game = _game()
    card = _province_card(game, "s", face_up=False)

    flow._end_turn(game)

    assert card.counters == {}  # a face-down refill just arrived — it never lingered face-up


def test_a_non_sincerity_province_card_does_not_accrue():
    game = _game()
    card = _province_card(game, "p", keywords=())

    flow._end_turn(game)

    assert card.counters == {}


def test_every_lingering_sincerity_card_accrues_across_provinces():
    game = _game()
    first = _province_card(game, "s1", index=0)
    second = _province_card(game, "s2", index=1)

    flow._end_turn(game)

    assert first.counters == {"sincerity": 1} and second.counters == {"sincerity": 1}


def test_a_sincerity_card_in_play_does_not_accrue():
    game = _game()
    card = DynastyHolding(
        id="s", name="s", side=Side.DYNASTY, owner=PlayerId.P1, keywords=("Sincerity",)
    )
    card.turn_face_up()
    game.table.cards_by_id["s"] = card
    game.table.battlefield.add(card)  # in play, not lingering in a Province

    flow._end_turn(game)

    assert card.counters == {}


def test_sincerity_accrues_only_on_the_owners_own_turns():
    game = _game()  # P1 active
    card = _province_card(game, "s")  # in P1's Province

    flow._end_turn(game)  # P1's turn ends -> +1
    flow._end_turn(game)  # P2's turn ends -> P1's card is not in P2's Provinces
    flow._end_turn(game)  # P1's turn ends -> +1

    assert card.counters == {"sincerity": 2}


def test_sincerity_accrual_replays_through_a_full_turn():
    state = TableState.empty_two_seat()
    state.decks[DeckKey(PlayerId.P1, Side.FATE)].cards = [
        FateCard(id="fd", name="F", side=Side.FATE, owner=PlayerId.P1)
    ]
    state.cards_by_id["fd"] = state.decks[DeckKey(PlayerId.P1, Side.FATE)].cards[0]
    card = DynastyHolding(
        id="s", name="s", side=Side.DYNASTY, owner=PlayerId.P1, keywords=("Sincerity",)
    )
    card.turn_face_up()
    state.cards_by_id["s"] = card
    province = ProvinceZone(owner=PlayerId.P1)
    province.add(card)
    state.zones[ZoneKey(PlayerId.P1, ZoneRole.PROVINCE, 0)] = province

    session = EngineSession.start(state, PlayerId.P1)
    for _ in range(3):  # Action -> Attack -> Dynasty -> end of P1's turn
        session.act(PlayerId.P1, Pass())

    assert session.game.table.cards_by_id["s"].counters == {"sincerity": 1}
    restored = game_log_from_dict(json.loads(json.dumps(game_log_to_dict(session.log))))
    assert restored.replay() == session.game
