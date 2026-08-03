import inspect
from dataclasses import FrozenInstanceError

import pytest

from yasuki_core.engine.players import PlayerId
from yasuki_core.engine.rules import effects
from yasuki_core.engine.rules.effects import (
    AdjustCounter,
    BanishTopFate,
    Bow,
    Choose,
    Destroy,
    Effect,
    InterruptingEffect,
)
from yasuki_core.engine.table import DeckKey
from yasuki_core.game_pieces.constants import Side
from yasuki_core.game_pieces.counters import WEALTH

from tests.yasuki_core.engine.builders import fate_card, holding, put_in_play, two_seat_game


def _effect_types():
    """Every concrete Effect the module defines. Discovered rather than listed, so a new effect is
    covered by these tests the moment it is written; abstract bases are excluded."""
    return [
        value
        for value in vars(effects).values()
        if inspect.isclass(value) and issubclass(value, Effect) and not inspect.isabstract(value)
    ]


def test_every_effect_implements_perform():
    missing = [
        cls.__name__
        for cls in _effect_types()
        if getattr(cls.perform, "__isabstractmethod__", False)
    ]
    assert missing == []


def test_effect_discovery_finds_concrete_effects_and_excludes_the_base():
    # Guards the discovery above: if it silently found nothing, the other tests would pass vacuously.
    assert Bow in _effect_types()
    assert Effect not in _effect_types()
    assert InterruptingEffect not in _effect_types()


def test_effects_stay_frozen_hashable_and_slotted():
    # Replay compares rebuilt effects by value and stashes them on the work stack, so an effect that
    # lost frozen-ness or value equality would break resumption silently.
    bow = Bow("card")
    assert bow == Bow("card") and hash(bow) == hash(Bow("card"))
    assert not hasattr(bow, "__dict__")
    with pytest.raises(FrozenInstanceError):
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
    with pytest.raises(RuntimeError, match="never applied directly"):
        choice.perform(two_seat_game())


def _vanished(game, card_id):
    """Drop a card from the id map while leaving it on the battlefield, as a mid-cascade destroy
    does to any effect that bound it earlier."""
    del game.table.cards_by_id[card_id]


def test_adjusting_a_counter_on_a_vanished_card_is_a_no_op():
    game = two_seat_game()
    card = put_in_play(game, holding("P1-h"))
    _vanished(game, card.id)
    assert AdjustCounter(card.id, WEALTH, 1).perform(game) == []


def test_destroying_a_vanished_card_is_a_no_op():
    game = two_seat_game()
    card = put_in_play(game, holding("P1-h"))
    _vanished(game, card.id)
    assert Destroy(card.id).perform(game) == []


def test_destroying_an_unowned_card_is_a_no_op():
    # A card with no owner has no discard pile to go to.
    game = two_seat_game()
    card = put_in_play(game, holding("P1-h", owner=None))
    assert Destroy(card.id).perform(game) == []
