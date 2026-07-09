import pytest

from yasuki_core.engine import ops
from yasuki_core.engine.players import PlayerId
from yasuki_core.engine.table import TableState, ZoneKey, ZoneRole, DeckKey
from yasuki_core.game_pieces.constants import Side
from yasuki_core.game_pieces.fate import FateCard
from yasuki_core.game_pieces.dynasty import DynastyCard, DynastyHolding
from yasuki_core.game_pieces.pregame import StrongholdCard
from yasuki_core.engine.rules.state import GameState, Phase
from yasuki_core.engine.rules.decisions import DiscardToHandSize, DecisionResponse
from yasuki_core.engine.rules import flow


def _register(state: TableState, card):
    state.cards_by_id[card.id] = card
    return card


def _game(hand: int = 0, fate_deck: int = 1) -> GameState:
    """A two-seat game where P1 holds ``hand`` fate cards and each seat's fate deck holds
    ``fate_deck`` cards."""
    state = TableState.empty_two_seat()
    for seat in PlayerId:
        state.decks[DeckKey(seat, Side.FATE)].cards = [
            _register(
                state, FateCard(id=f"{seat.name}-fd{i}", name="F", side=Side.FATE, owner=seat)
            )
            for i in range(fate_deck)
        ]
    hand_zone = state.zones[ZoneKey(PlayerId.P1, ZoneRole.HAND)]
    for i in range(hand):
        hand_zone.add(
            _register(state, FateCard(id=f"P1-h{i}", name="H", side=Side.FATE, owner=PlayerId.P1))
        )
    return GameState.start(state, PlayerId.P1)


def _advance_to_end_of_turn(game: GameState) -> None:
    flow.advance(game)  # Action -> Attack
    flow.advance(game)  # Attack -> Dynasty
    flow.advance(game)  # Dynasty -> end of turn


def test_advance_walks_the_three_phases():
    game = _game()
    assert game.phase is Phase.ACTION
    flow.advance(game)
    assert game.phase is Phase.ATTACK
    flow.advance(game)
    assert game.phase is Phase.DYNASTY


def test_advance_past_dynasty_draws_fate_and_passes_the_turn():
    game = _game(hand=0, fate_deck=1)

    _advance_to_end_of_turn(game)

    assert game.turn == 2
    assert game.active is PlayerId.P2
    assert game.phase is Phase.ACTION
    assert len(game.table.zones[ZoneKey(PlayerId.P1, ZoneRole.HAND)].cards) == 1
    # Only the active player draws at their turn-end; the opponent's hand is untouched.
    assert game.table.zones[ZoneKey(PlayerId.P2, ZoneRole.HAND)].cards == []


def test_empty_fate_deck_draws_nothing_and_still_passes_the_turn():
    game = _game(hand=0, fate_deck=0)

    _advance_to_end_of_turn(game)

    assert game.turn == 2 and game.active is PlayerId.P2
    assert game.table.zones[ZoneKey(PlayerId.P1, ZoneRole.HAND)].cards == []


def test_advance_empties_the_gold_pool_on_each_phase_change():
    game = _game()
    game.add_gold(PlayerId.P1, 5)
    flow.advance(game)
    assert game.gold[PlayerId.P1] == 0


def test_overfull_hand_pauses_for_discard_then_resumes():
    game = _game(hand=flow.MAX_HAND_SIZE, fate_deck=1)  # 8 held + 1 drawn = 9

    _advance_to_end_of_turn(game)

    assert game.awaiting_decision
    assert isinstance(game.pending, DiscardToHandSize) and game.pending.count == 1
    # The request offers the whole hand as candidates.
    hand_cards = game.table.zones[ZoneKey(PlayerId.P1, ZoneRole.HAND)].cards
    assert set(game.pending.candidates) == {card.id for card in hand_cards}
    assert game.turn == 1 and game.active is PlayerId.P1  # turn not yet passed

    hand = game.table.zones[ZoneKey(PlayerId.P1, ZoneRole.HAND)]
    victim = hand.cards[0].id
    flow.submit(game, DecisionResponse((victim,)))

    assert not game.awaiting_decision
    assert game.turn == 2 and game.active is PlayerId.P2
    assert len(hand.cards) == flow.MAX_HAND_SIZE
    discard = game.table.zones[ZoneKey(PlayerId.P1, ZoneRole.FATE_DISCARD)]
    assert any(card.id == victim for card in discard.cards)


def test_cannot_advance_while_a_decision_is_pending():
    game = _game(hand=flow.MAX_HAND_SIZE, fate_deck=1)
    _advance_to_end_of_turn(game)
    assert game.awaiting_decision
    with pytest.raises(RuntimeError):
        flow.advance(game)


def test_submit_rejects_a_malformed_or_illegal_answer():
    game = _game(hand=flow.MAX_HAND_SIZE, fate_deck=1)
    _advance_to_end_of_turn(game)

    with pytest.raises(ValueError):  # wrong count: must discard exactly one
        flow.submit(game, DecisionResponse(()))
    with pytest.raises(ValueError):  # right count, but the card is not in hand
        flow.submit(game, DecisionResponse(("not-in-hand",)))
    assert game.awaiting_decision  # both rejections leave the game paused


def _bowed_on_battlefield(state: TableState, seat: PlayerId, card_id: str):
    card = _register(state, DynastyCard(id=card_id, name="B", side=Side.DYNASTY, owner=seat))
    card.bow()
    state.battlefield.add(card)
    return card


def _facedown_in_province(state: TableState, seat: PlayerId, card_id: str):
    card = _register(state, DynastyCard(id=card_id, name="P", side=Side.DYNASTY, owner=seat))
    card.turn_face_down()
    state.zones[ops.create_province(state, seat)].add(card)
    return card


def test_begin_game_straightens_and_reveals_only_the_active_board():
    state = TableState.empty_two_seat()
    mine_bowed = _bowed_on_battlefield(state, PlayerId.P1, "P1-bf")
    mine_facedown = _facedown_in_province(state, PlayerId.P1, "P1-pv")
    foe_bowed = _bowed_on_battlefield(state, PlayerId.P2, "P2-bf")
    foe_facedown = _facedown_in_province(state, PlayerId.P2, "P2-pv")

    game = GameState.start(state, PlayerId.P1)
    flow.begin_game(game)

    assert mine_bowed.bowed is False and mine_facedown.face_up is True
    # The opponent's board is untouched at the active player's start of turn.
    assert foe_bowed.bowed is True and foe_facedown.face_up is False


def _game_with_stronghold_clan(clan: str | None) -> GameState:
    state = TableState.empty_two_seat()
    state.battlefield.add(
        _register(
            state,
            StrongholdCard(
                id="P1-SH", name="SH", side=Side.STRONGHOLD, owner=PlayerId.P1, clan=clan
            ),
        )
    )
    return GameState.start(state, PlayerId.P1)


def test_recruit_cost_adds_the_off_clan_surcharge_only_for_a_different_clan():
    game = _game_with_stronghold_clan("crab")
    same = DynastyHolding(
        id="h1", name="H", side=Side.DYNASTY, owner=PlayerId.P1, gold_cost=4, clan="crab"
    )
    other = DynastyHolding(
        id="h2", name="H", side=Side.DYNASTY, owner=PlayerId.P1, gold_cost=4, clan="crane"
    )

    assert flow.recruit_cost(game, same) == 4
    assert flow.recruit_cost(game, other) == 4 + flow.OFF_CLAN_SURCHARGE


def test_recruit_cost_charges_no_surcharge_when_clan_alignment_is_unknown():
    game = _game_with_stronghold_clan(None)
    holding = DynastyHolding(
        id="h", name="H", side=Side.DYNASTY, owner=PlayerId.P1, gold_cost=4, clan="crane"
    )
    assert flow.recruit_cost(game, holding) == 4  # no Stronghold clan to compare against


def _discount_game(*, clan=None, first_player=PlayerId.P1, in_play=()):
    state = TableState.empty_two_seat()
    state.battlefield.add(
        _register(
            state,
            StrongholdCard(
                id="P1-SH", name="SH", side=Side.STRONGHOLD, owner=PlayerId.P1, clan=clan
            ),
        )
    )
    for card in in_play:
        state.battlefield.add(_register(state, card))
    return GameState.start(state, first_player)


def _holding(printed_id: str, gold_cost: int, keywords=()) -> DynastyHolding:
    return DynastyHolding(
        id=f"{printed_id}-inst",
        name="H",
        side=Side.DYNASTY,
        owner=PlayerId.P1,
        printed_id=printed_id,
        gold_cost=gold_cost,
        keywords=keywords,
    )


def test_colonial_farm_discounts_one_for_a_lion_player():
    farm = _holding("colonial_farm", gold_cost=6)
    assert flow.recruit_cost(_discount_game(clan="Lion"), farm) == 5
    assert flow.recruit_cost(_discount_game(clan="Crab"), farm) == 6  # no discount off-clan


def test_fantastic_gardens_discounts_two_for_a_crane_player():
    gardens = _holding("fantastic_gardens", gold_cost=7)
    assert flow.recruit_cost(_discount_game(clan="Crane"), gardens) == 5
    assert flow.recruit_cost(_discount_game(clan="Lion"), gardens) == 7


def test_moto_traders_discounts_with_another_merchant_caravan_in_play():
    caravan = DynastyHolding(
        id="mc", name="C", side=Side.DYNASTY, owner=PlayerId.P1, keywords=("Merchant Caravan",)
    )
    traders = _holding("moto_traders", gold_cost=5)
    assert flow.recruit_cost(_discount_game(in_play=(caravan,)), traders) == 4
    assert flow.recruit_cost(_discount_game(), traders) == 5


def test_shrine_of_courtesy_discounts_three_when_you_went_second():
    shrine = _holding("shrine_of_courtesy", gold_cost=4)
    assert (
        flow.recruit_cost(_discount_game(first_player=PlayerId.P2), shrine) == 1
    )  # P1 went second
    assert flow.recruit_cost(_discount_game(first_player=PlayerId.P1), shrine) == 4


def test_recruit_discount_floors_the_cost_at_zero():
    cheap = _holding("shrine_of_courtesy", gold_cost=2)  # a -3 discount would go negative
    assert flow.recruit_cost(_discount_game(first_player=PlayerId.P2), cheap) == 0
