import pytest

from yasuki_core.engine.players import PlayerId
from yasuki_core.engine.rules.effects import AdjustCounter, Effect
from yasuki_core.engine.rules.events import CounterGained, EnteredPlay
from yasuki_core.engine.rules.triggers import TriggerContext, fire, on
from yasuki_core.game_pieces.counters import WEALTH

from tests.yasuki_core.engine.builders import holding, put_in_play, two_seat_game


@on(CounterGained, "loop_forever")
def _loop_forever(ctx: TriggerContext) -> list[Effect]:
    """Reacts to its own wealth by granting itself more — the card-logic bug the guard exists for."""
    if ctx.event.card_id != ctx.card.id:
        return []
    return [AdjustCounter(ctx.card.id, WEALTH, 1)]


@on(EnteredPlay, "loop_forever")
def _loop_forever_starts(ctx: TriggerContext) -> list[Effect]:
    if ctx.event.card_id != ctx.card.id:
        return []
    return [AdjustCounter(ctx.card.id, WEALTH, 1)]


def test_a_non_converging_cascade_names_its_repeating_cycle():
    game = two_seat_game()
    card = put_in_play(game, holding("loop", owner=PlayerId.P1, printed_id="loop_forever"))

    with pytest.raises(RuntimeError, match="did not converge") as raised:
        fire(game, EnteredPlay(card.id))

    message = str(raised.value)

    assert "CounterGained" in message
    assert "loop_forever (loop) reacts" in message
    assert "+1 Wealth on loop" in message
    assert "repeating" in message


def test_the_trace_is_short_enough_to_read():
    # A thousand events is the bound; a thousand lines is not a diagnosis. The cycle collapses.
    game = two_seat_game()
    card = put_in_play(game, holding("loop", owner=PlayerId.P1, printed_id="loop_forever"))

    with pytest.raises(RuntimeError) as raised:
        fire(game, EnteredPlay(card.id))

    assert len(str(raised.value).splitlines()) <= 12


def test_a_converging_cascade_raises_nothing():
    game = two_seat_game()
    card = put_in_play(game, holding("quiet", owner=PlayerId.P1, printed_id="no_trigger_here"))

    fire(game, EnteredPlay(card.id))

    assert card.counters.get(WEALTH.key, 0) == 0
