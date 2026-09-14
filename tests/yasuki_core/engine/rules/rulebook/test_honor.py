import pytest

from yasuki_core.engine.players import PlayerId
from yasuki_core.engine.rules import legality
from yasuki_core.engine.rules.effects import GainHonor
from yasuki_core.engine.rules.state import GameState
from yasuki_core.engine.rules.triggers import resolve_effects
from yasuki_core.engine.rules.turn import action_sequence, sequence
from yasuki_core.engine.rules.turn.structure import ActionRound, RoundTimings
from yasuki_core.engine.rules.vocabulary.actions import (
    ActionTiming,
    HonorInterrupt,
    KharmicDraw,
    Pass,
)
from yasuki_core.engine.table import ZoneKey, ZoneRole
from yasuki_core.game_pieces.cards import L5RCard
from yasuki_core.game_pieces.constants import Side
from yasuki_core.game_pieces.prints import FatePrint

from tests.yasuki_core.engine.builders import fate_card, register, two_seat_game

INTERRUPT_TIMINGS = RoundTimings(
    active=frozenset({ActionTiming.INTERRUPT}), others=frozenset({ActionTiming.INTERRUPT})
)


def _interrupt_step(honor_cards: int = 1, *, seat: PlayerId = PlayerId.P1) -> GameState:
    """A game paused in an Interrupt step with ``seat`` holding the opportunity and ``honor_cards``
    Honor cards in hand."""
    game = two_seat_game()
    hand = game.table.zones[ZoneKey(seat, ZoneRole.HAND)]
    for index in range(honor_cards):
        hand.add(
            register(
                game.table,
                L5RCard.of(
                    FatePrint,
                    id=f"{seat.name}-h{index}",
                    name="Honor Fate",
                    side=Side.FATE,
                    owner=seat,
                    keywords=("Honor",),
                ),
            )
        )
    game.round = ActionRound(timings=INTERRUPT_TIMINGS, priority=seat)
    return game


def test_an_interrupt_is_offered_per_honor_card_seat_and_direction():
    game = _interrupt_step()

    offered = [action for action in legality.legal_actions(game, PlayerId.P1) if action != Pass()]

    assert offered == [
        HonorInterrupt("P1-h0", PlayerId.P1, 1),
        HonorInterrupt("P1-h0", PlayerId.P1, -1),
        HonorInterrupt("P1-h0", PlayerId.P2, 1),
        HonorInterrupt("P1-h0", PlayerId.P2, -1),
    ]


def test_the_interrupt_is_withheld_outside_an_interrupt_step():
    game = _interrupt_step()
    sequence.open_round(game)

    assert not any(
        isinstance(action, HonorInterrupt) for action in legality.legal_actions(game, PlayerId.P1)
    )


def test_a_card_without_the_keyword_cannot_be_spent():
    game = _interrupt_step(honor_cards=0)
    plain = register(game.table, fate_card("plain", PlayerId.P1))
    game.table.zones[ZoneKey(PlayerId.P1, ZoneRole.HAND)].add(plain)

    assert legality.legal_actions(game, PlayerId.P1) == [Pass()]


def test_taking_the_interrupt_discards_the_card_and_adjusts_the_next_gain():
    game = _interrupt_step()

    action_sequence.perform(game, HonorInterrupt("P1-h0", PlayerId.P2, -1))
    before = game.table.seats[PlayerId.P2].honor
    resolve_effects(game, [GainHonor(PlayerId.P2, 3)])

    assert "P1-h0" in [
        card.id for card in game.table.zones[ZoneKey(PlayerId.P1, ZoneRole.FATE_DISCARD)].cards
    ]
    assert game.table.seats[PlayerId.P2].honor == before + 2
    assert game.honor_adjustments == {}


def test_a_seat_may_interrupt_once_per_action():
    game = _interrupt_step(honor_cards=2)

    action_sequence.perform(game, HonorInterrupt("P1-h0", PlayerId.P2, 1))
    game.round = ActionRound(timings=INTERRUPT_TIMINGS, priority=PlayerId.P1)

    assert legality.legal_actions(game, PlayerId.P1) == [Pass()]


@pytest.mark.parametrize("delta", [1, -1])
def test_is_legal_agrees_with_the_enumeration(delta):
    game = _interrupt_step()

    assert legality.is_legal(game, PlayerId.P1, HonorInterrupt("P1-h0", PlayerId.P2, delta))
    assert not legality.is_legal(game, PlayerId.P1, HonorInterrupt("P1-h0", PlayerId.P2, 2))


def test_the_next_action_forgets_the_adjustments():
    game = _interrupt_step()
    action_sequence.perform(game, HonorInterrupt("P1-h0", PlayerId.P2, 1))

    sequence.open_round(game)

    assert game.honor_adjustments == {}
    assert game.honor_interrupted == set()


def test_an_interrupt_leaves_the_interrupted_action_on_record():
    game = _interrupt_step()
    game.action = KharmicDraw("interrupted")

    action_sequence.perform(game, HonorInterrupt("P1-h0", PlayerId.P2, 1))

    assert game.action == KharmicDraw("interrupted")


def test_interrupts_from_both_seats_accumulate_against_one_action():
    game = _interrupt_step()
    hand = game.table.zones[ZoneKey(PlayerId.P2, ZoneRole.HAND)]
    hand.add(
        register(
            game.table,
            L5RCard.of(
                FatePrint,
                id="P2-h0",
                name="Honor Fate",
                side=Side.FATE,
                owner=PlayerId.P2,
                keywords=("Honor",),
            ),
        )
    )

    action_sequence.perform(game, HonorInterrupt("P1-h0", PlayerId.P2, 1))
    game.round = ActionRound(timings=INTERRUPT_TIMINGS, priority=PlayerId.P2)
    action_sequence.perform(game, HonorInterrupt("P2-h0", PlayerId.P2, 1))

    assert game.honor_adjustments == {PlayerId.P2: 2}
    assert game.honor_interrupted == {PlayerId.P1, PlayerId.P2}
