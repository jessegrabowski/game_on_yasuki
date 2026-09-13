import pytest

from yasuki_core.engine import ops
from yasuki_core.engine.players import PlayerId
from yasuki_core.engine.table import TableState, ZoneKey, ZoneRole, DeckKey
from yasuki_core.game_pieces.constants import Side
from yasuki_core.game_pieces.cards import L5RCard
from yasuki_core.game_pieces.prints import (
    DynastyPrint,
    FatePrint,
)
from yasuki_core.engine.rules.state import GameState
from yasuki_core.engine.rules.rulebook import recruit
from yasuki_core.engine.rules.turn import sequence
from yasuki_core.engine.rules.vocabulary.game_events import (
    CardDiscarded,
)

from tests.yasuki_core.engine.builders import (
    end_phase,
    holding,
    put_in_play,
    register,
)
from yasuki_core.game_pieces.prints import HoldingPrint
from yasuki_core.game_pieces.prints import StrongholdPrint


def _game(hand: int = 0, fate_deck: int = 1) -> GameState:
    """A two-seat game where P1 holds ``hand`` fate cards and each seat's fate deck holds
    ``fate_deck`` cards."""
    state = TableState.empty_two_seat()
    for seat in PlayerId:
        state.decks[DeckKey(seat, Side.FATE)].cards = [
            register(
                state,
                L5RCard.of(
                    FatePrint, id=f"{seat.name}-fd{i}", name="F", side=Side.FATE, owner=seat
                ),
            )
            for i in range(fate_deck)
        ]
    hand_zone = state.zones[ZoneKey(PlayerId.P1, ZoneRole.HAND)]
    for i in range(hand):
        hand_zone.add(
            register(
                state,
                L5RCard.of(FatePrint, id=f"P1-h{i}", name="H", side=Side.FATE, owner=PlayerId.P1),
            )
        )
    return GameState.start(state, PlayerId.P1)


def _advance_to_end_of_turn(game: GameState) -> None:
    sequence.advance(game)  # Action -> Battle
    sequence.advance(game)  # Battle -> Dynasty
    sequence.advance(game)  # Dynasty -> end of turn


def _bowed_on_battlefield(state: TableState, seat: PlayerId, card_id: str):
    card = register(
        state, L5RCard.of(DynastyPrint, id=card_id, name="B", side=Side.DYNASTY, owner=seat)
    )
    card.bow()
    state.battlefield.add(card)
    return card


def _facedown_in_province(state: TableState, seat: PlayerId, card_id: str):
    card = register(
        state, L5RCard.of(DynastyPrint, id=card_id, name="P", side=Side.DYNASTY, owner=seat)
    )
    card.turn_face_down()
    state.zones[ops.create_province(state, seat)].add(card)
    return card


def test_recruit_rejects_invest_and_proclaim_together():
    # legal_actions never offers the pair, but a decoded tape could still carry it; recruit must
    # fail loudly rather than silently drop the Proclaim.
    game = _discount_game(clan="Crab")
    holding = register(game.table, _holding("teahouse", gold_cost=2))
    with pytest.raises(ValueError, match="Invest and Proclaim"):
        recruit.recruit(game, holding.id, invest=True, proclaim=True)


# --- the Response Step ---


def _responder_game() -> GameState:
    """A game whose active seat holds one Response: a Caravansary answering its own Fate discard."""
    state = TableState.empty_two_seat()
    put_in_play(
        state,
        holding(
            "caravansary",
            printed_id="caravansary",
            name="Caravansary",
            owner=PlayerId.P1,
            gold_production=2,
        ),
    )
    game = GameState.start(state, PlayerId.P1)
    game.action_events[:] = [CardDiscarded("some-fate", Side.FATE, PlayerId.P1)]
    return game


def _advance_turns(session, count: int) -> None:
    """Pass until ``count`` further turns have opened."""
    target = session.game.turn + count
    for _ in range(4 * count + 4):
        if session.game.turn == target:
            return
        end_phase(session)
    raise AssertionError(f"stuck on turn {session.game.turn}, wanted {target}")


def _discount_game(*, clan=None, first_player=PlayerId.P1, in_play=()):
    state = TableState.empty_two_seat()
    put_in_play(
        state,
        L5RCard.of(
            StrongholdPrint,
            id="P1-SH",
            name="SH",
            side=Side.STRONGHOLD,
            owner=PlayerId.P1,
            clan=clan,
        ),
    )
    for card in in_play:
        put_in_play(state, card)
    return GameState.start(state, first_player)


def _holding(printed_id: str, gold_cost: int, clan: str | None = None) -> L5RCard:
    return L5RCard.of(
        HoldingPrint,
        id=f"{printed_id}-inst",
        name="H",
        side=Side.DYNASTY,
        owner=PlayerId.P1,
        printed_id=printed_id,
        gold_cost=gold_cost,
        clan=clan,
    )
