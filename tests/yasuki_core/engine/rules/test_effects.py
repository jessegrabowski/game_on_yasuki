import inspect
from dataclasses import FrozenInstanceError, dataclass

import pytest

from yasuki_core.engine.players import PlayerId
from yasuki_core.engine.rules import effects
from yasuki_core.engine.rules.decisions import ChooseCards, DecisionResponse
from yasuki_core.engine.rules.flow import submit
from yasuki_core.engine.rules.triggers import choice_resolver, resolve_effects
from yasuki_core.engine.rules.effects import (
    AdjustCounter,
    BanishTopFate,
    Bow,
    Choose,
    Destroy,
    Discard,
    PlaceInProvince,
    Effect,
    InterruptingEffect,
)
from yasuki_core.engine.rules.events import CardDiscarded
from yasuki_core.engine.table import DeckKey, ZoneKey, ZoneRole
from yasuki_core.game_pieces.constants import Side
from yasuki_core.game_pieces.counters import WEALTH

from tests.yasuki_core.engine.builders import (
    fate_card,
    holding,
    province_card,
    put_in_play,
    two_seat_game,
)


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


@pytest.mark.parametrize(
    "side, role",
    [(Side.FATE, ZoneRole.FATE_DISCARD), (Side.DYNASTY, ZoneRole.DYNASTY_DISCARD)],
    ids=["fate", "dynasty"],
)
def test_a_discard_lands_in_the_pile_for_its_side(side, role):
    # Destroy and Discard pick the pile the same way. Drift between them would strand a Fate card
    # in the Dynasty discard, where nothing that searches for it would look.
    game = two_seat_game()
    card = fate_card("P1-f", PlayerId.P1) if side is Side.FATE else holding("P1-h")
    put_in_play(game, card)

    events = Discard(card.id, PlayerId.P1).perform(game)

    assert card in game.table.zones[ZoneKey(PlayerId.P1, role)].cards
    assert events == [CardDiscarded(card.id, side, PlayerId.P1)]


def test_placing_into_a_full_province_is_a_no_op():
    # The placement is deferred behind the reactions to the discard, so something can fill the
    # Province in between. Checking capacity first is what keeps the card where it is: the move
    # would take it out of play before the full Province refused it, leaving it nowhere at all.
    game = two_seat_game()
    province = ZoneKey(PlayerId.P1, ZoneRole.PROVINCE, 0)
    sitting = province_card(game, "P1-sitting", seat=PlayerId.P1)
    card = put_in_play(game, holding("P1-late"))

    assert PlaceInProvince(card.id, province).perform(game) == []
    assert [c.id for c in game.table.zones[province].cards] == [sitting.id]
    assert card in game.table.battlefield.cards  # not swallowed on the way


@dataclass(frozen=True, slots=True)
class _AskToDiscard(InterruptingEffect):
    """A second interrupting effect, defined only here. Nothing in the engine knows it exists."""

    seat: PlayerId
    candidates: tuple[str, ...]

    def describe(self) -> str:
        return f"{self.seat.name} is asked to discard"

    def request(self, game) -> ChooseCards:
        return ChooseCards(
            seat=self.seat,
            candidates=self.candidates,
            minimum=0,
            maximum=0,
            resolver="test_ask_to_discard",
        )


@choice_resolver("test_ask_to_discard")
def _ask_to_discard_resolved(game, source_id, chosen, seat):
    return []


def test_a_new_interrupting_effect_pauses_the_cascade_without_engine_changes():
    # The point of the category: the walker stashes on any InterruptingEffect, so an effect the
    # engine has never heard of pauses the cascade correctly.
    game = two_seat_game()
    card = put_in_play(game, holding("P1-h"))

    resolve_effects(
        game, [_AskToDiscard(PlayerId.P1, (card.id,)), AdjustCounter(card.id, WEALTH, 1)]
    )

    assert isinstance(game.pending, ChooseCards)
    assert card.counters.get("wealth") is None  # the effect after it has not run yet


def test_the_stashed_remainder_resumes_after_the_answer():
    game = two_seat_game()
    card = put_in_play(game, holding("P1-h"))
    resolve_effects(
        game, [_AskToDiscard(PlayerId.P1, (card.id,)), AdjustCounter(card.id, WEALTH, 1)]
    )

    submit(game, DecisionResponse(()))

    assert card.counters["wealth"] == 1  # the effect queued behind the pause ran on resume


_SOURCES_SEEN: list[str | None] = []


@choice_resolver("test_sourceless")
def _record_the_source(game, source_id, chosen, seat):
    _SOURCES_SEEN.append(source_id)
    return []


def test_a_choice_raised_by_no_card_reaches_its_resolver_with_none():
    # A rulebook ability has no card to name, and no card id can stand in for one: every string is
    # a perfectly good id that simply never matches, leaving a resolver unable to tell "no source"
    # from "a source I have not heard of".
    _SOURCES_SEEN.clear()
    game = two_seat_game()
    card = put_in_play(game, holding("P1-h"))

    resolve_effects(game, [Choose(PlayerId.P1, (card.id,), 0, 1, "test_sourceless")])
    submit(game, DecisionResponse((card.id,)))

    assert _SOURCES_SEEN == [None]


_SEATS_SEEN: list[PlayerId] = []


@choice_resolver("test_answering_seat")
def _record_the_seat(game, source_id, chosen, seat):
    _SEATS_SEEN.append(seat)
    return []


def test_a_resolver_is_told_which_seat_answered():
    """A choice can be put to a seat other than the one whose action raised it, and a declining
    answer names no card — so the seat cannot be recovered from the source or the chosen ids."""
    _SEATS_SEEN.clear()
    game = two_seat_game()
    card = put_in_play(game, holding("P2-h", owner=PlayerId.P2))

    resolve_effects(game, [Choose(PlayerId.P2, (card.id,), 0, 1, "test_answering_seat")])
    submit(game, DecisionResponse(()))  # declined: nothing chosen to infer a seat from

    assert _SEATS_SEEN == [PlayerId.P2]


def test_an_interrupting_effect_refuses_to_be_committed_directly():
    effect = _AskToDiscard(PlayerId.P1, ("a",))
    with pytest.raises(RuntimeError, match="never applied directly"):
        effect.perform(two_seat_game())
