import inspect

import pytest

from yasuki_core.engine.players import PlayerId
from yasuki_core.engine.rules import effects
from yasuki_core.engine.rules.effects import (
    AdjustCounter,
    BanishTopFate,
    Bow,
    Choose,
    Effect,
)
from yasuki_core.engine.table import DeckKey
from yasuki_core.game_pieces.constants import Side
from yasuki_core.game_pieces.counters import WEALTH

from tests.yasuki_core.engine.builders import fate_card, holding, put_in_play, two_seat_game


def _effect_types():
    """Every concrete Effect the module defines. Discovered rather than listed, so a new effect is
    covered by these tests the moment it is written."""
    return [
        value
        for value in vars(effects).values()
        if inspect.isclass(value) and issubclass(value, Effect) and value is not Effect
    ]


def test_every_effect_implements_perform():
    missing = [
        cls.__name__
        for cls in _effect_types()
        if getattr(cls.perform, "__isabstractmethod__", False)
    ]
    assert missing == []


def test_the_module_defines_the_effects_the_engine_expects():
    # Guards the discovery above: if it silently found nothing, the other tests would pass vacuously.
    assert len(_effect_types()) == 10


def test_an_effect_cannot_be_defined_without_perform():
    with pytest.raises(TypeError, match="abstract"):

        class Forgetful(Effect):
            pass

        Forgetful()


def test_effects_stay_frozen_hashable_and_slotted():
    # Replay compares rebuilt effects by value and stashes them on the work stack, so an effect that
    # lost frozen-ness or value equality would break resumption silently.
    bow = Bow("card")
    assert bow == Bow("card") and hash(bow) == hash(Bow("card"))
    assert not hasattr(bow, "__dict__")
    with pytest.raises(Exception):
        bow.card_id = "other"


def test_is_payable_defaults_to_true():
    game = two_seat_game()
    assert effects.DrawCard(PlayerId.P1).is_payable(game) is True


def test_bow_is_not_payable_for_an_already_bowed_card():
    game = two_seat_game()
    card = put_in_play(game, holding("P1-h"))
    assert Bow(card.id).is_payable(game) is True
    card.bow()
    assert Bow(card.id).is_payable(game) is False


def test_bow_is_not_payable_for_a_card_that_is_not_there():
    assert Bow("nonexistent").is_payable(two_seat_game()) is False


def test_removing_a_counter_needs_enough_of_it():
    game = two_seat_game()
    card = put_in_play(game, holding("P1-h", counters={"wealth": 1}))
    assert AdjustCounter(card.id, WEALTH, -1).is_payable(game) is True
    assert AdjustCounter(card.id, WEALTH, -2).is_payable(game) is False


def test_granting_a_counter_always_applies():
    game = two_seat_game()
    card = put_in_play(game, holding("P1-h"))
    assert AdjustCounter(card.id, WEALTH, 1).is_payable(game) is True


def test_banishing_needs_a_fate_card_to_banish():
    game = two_seat_game()
    assert BanishTopFate(PlayerId.P1).is_payable(game) is False
    deck = game.table.decks[DeckKey(PlayerId.P1, Side.FATE)]
    deck.cards = [fate_card("P1-fd", PlayerId.P1)]
    assert BanishTopFate(PlayerId.P1).is_payable(game) is True


def test_choose_refuses_to_be_committed_directly():
    choice = Choose(PlayerId.P1, ("a",), 0, 1, "resolver", "src")
    with pytest.raises(RuntimeError, match="pauses the trigger cascade"):
        choice.perform(two_seat_game())
