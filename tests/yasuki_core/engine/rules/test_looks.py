import pytest

from yasuki_core.engine.players import PlayerId
from yasuki_core.engine.rules.abilities.model import Ability, itself
from yasuki_core.engine.rules.abilities.registry import register_ability
from yasuki_core.engine.rules.board.queries import remaining_look, top_of_deck
from yasuki_core.engine.rules.effects import (
    Arrange,
    Choose,
    EndLook,
    LookAtTop,
    MoveToDeck,
    MoveToHand,
    PlaceOnDeck,
)
from yasuki_core.engine.rules.rulebook.looks import PUT_BACK_ON_TOP
from yasuki_core.engine.rules.triggers import CHOICE_RESOLVERS, choice_resolver, resolve_effects
from yasuki_core.engine.rules.vocabulary.actions import ActionTiming, ActivateAbility
from yasuki_core.engine.rules.vocabulary.decisions import ChooseAbilityTarget, ChooseCards
from yasuki_core.engine.rules.vocabulary.decisions import DecisionResponse
from yasuki_core.engine.rules.vocabulary.looks import Look
from yasuki_core.engine.session import EngineSession
from yasuki_core.engine.table import DeckKey, TableState, ZoneKey, ZoneRole
from yasuki_core.game_pieces.constants import Side

from tests.yasuki_core.engine.builders import (
    fate_card,
    holding,
    put_in_play,
    register,
    two_seat_game,
)

P1 = PlayerId.P1
FATE = DeckKey(P1, Side.FATE)


def _stack_fate(table: TableState, *ids: str) -> None:
    """Put ``ids`` in P1's Fate deck, the first named on top."""
    table.decks[FATE].cards = [register(table, fate_card(card_id, P1)) for card_id in reversed(ids)]


def test_looking_opens_a_look_at_the_top_cards_top_first():
    game = two_seat_game()
    _stack_fate(game.table, "top", "second", "third", "deep")

    LookAtTop(P1, FATE, 3).perform(game)

    assert game.look == Look(P1, FATE, ("top", "second", "third"))
    assert game.table.decks[FATE].cards[-1].id == "top"  # nothing moved


def test_looking_marks_the_seat_as_a_peeker_of_each_card():
    game = two_seat_game()
    _stack_fate(game.table, "top", "second")

    LookAtTop(P1, FATE, 1).perform(game)

    assert P1 in game.table.cards_by_id["top"].peekers
    assert P1 not in game.table.cards_by_id["second"].peekers


def test_a_short_deck_shows_what_it_has():
    game = two_seat_game()
    _stack_fate(game.table, "only")

    LookAtTop(P1, FATE, 4).perform(game)

    assert game.look.card_ids == ("only",)


def test_an_empty_deck_is_nothing_to_look_at():
    game = two_seat_game()
    assert LookAtTop(P1, FATE, 1).is_payable(game) is False


def test_ending_the_look_closes_it_and_leaves_the_peekers():
    game = two_seat_game()
    _stack_fate(game.table, "top")
    LookAtTop(P1, FATE, 1).perform(game)

    EndLook().perform(game)

    assert game.look is None
    assert P1 in game.table.cards_by_id["top"].peekers


def test_the_top_of_a_deck_reads_top_first():
    game = two_seat_game()
    _stack_fate(game.table, "top", "second", "third")

    assert top_of_deck(game, FATE, 2) == ("top", "second")


def test_the_remaining_look_drops_a_card_that_left_the_deck():
    game = two_seat_game()
    _stack_fate(game.table, "top", "second", "third")
    LookAtTop(P1, FATE, 3).perform(game)

    MoveToHand("second", P1).perform(game)

    assert remaining_look(game) == ("top", "third")


def test_the_remaining_look_drops_a_card_put_on_the_bottom_of_the_same_deck():
    """Putting a card on the bottom puts it back in the deck it was looked at in, so being in the
    deck is not enough: what says it left the pool is that entering a deck scrubbed the seat's
    peek."""
    game = two_seat_game()
    _stack_fate(game.table, "top", "second", "third", "deep")
    LookAtTop(P1, FATE, 3).perform(game)

    MoveToDeck("second", FATE, from_bottom=0).perform(game)

    assert remaining_look(game) == ("top", "third")


def test_the_remaining_look_is_empty_outside_a_look():
    assert remaining_look(two_seat_game()) == ()


@choice_resolver("test_look_take", prompt="Choose a card to put in your hand")
def _take(game, source_id, chosen, seat):
    return [MoveToHand(card_id, seat) for card_id in chosen] + [EndLook()]


register_ability(
    "test_looker",
    Ability(
        timings=(ActionTiming.LIMITED,),
        label="look",
        cost=lambda game, source: [],
        targets=itself,
        effects=lambda game, source, target: [
            LookAtTop(P1, FATE, 2),
            Choose(P1, top_of_deck(game, FATE, 2), 0, 1, "test_look_take", source.id),
        ],
    ),
)


def _looking_session() -> EngineSession:
    state = TableState.empty_two_seat()
    put_in_play(state, holding("looker", printed_id="test_looker"))
    _stack_fate(state, "top", "second", "third")
    session = EngineSession.start(state, P1)
    session.act(P1, ActivateAbility("looker"))
    assert isinstance(session.game.pending, ChooseAbilityTarget)
    session.submit(P1, DecisionResponse(("looker",)))
    return session


def test_a_look_cannot_be_backed_out_of_once_the_cards_are_seen():
    session = _looking_session()
    pending = session.game.pending
    assert isinstance(pending, ChooseCards) and pending.cancellable

    with pytest.raises(ValueError, match="looked at"):
        session.cancel(P1)

    assert session.abort(P1) is False
    assert session.game.look == Look(P1, FATE, ("top", "second"))
    assert session.game.pending is pending


@choice_resolver("test_look_close_then_ask", prompt="Choose a card to keep looking at")
def _close_then_ask(game, source_id, chosen, seat):
    return [EndLook(), Choose(P1, top_of_deck(game, FATE, 1), 1, 1, "test_after_look", source_id)]


@choice_resolver("test_after_look", prompt="Choose a card")
def _after_look(game, source_id, chosen, seat):
    return []


register_ability(
    "test_look_asker",
    Ability(
        timings=(ActionTiming.LIMITED,),
        label="look, then ask",
        cost=lambda game, source: [],
        targets=itself,
        effects=lambda game, source, target: [
            LookAtTop(P1, FATE, 2),
            Choose(P1, top_of_deck(game, FATE, 2), 0, 1, "test_look_close_then_ask", source.id),
        ],
    ),
)


def test_a_question_after_the_look_closes_still_cannot_be_backed_out_of():
    state = TableState.empty_two_seat()
    put_in_play(state, holding("asker", printed_id="test_look_asker"))
    _stack_fate(state, "top", "second", "third")
    session = EngineSession.start(state, P1)
    session.act(P1, ActivateAbility("asker"))
    session.submit(P1, DecisionResponse(("asker",)))
    session.submit(P1, DecisionResponse(()))

    assert session.game.look is None
    assert session.game.pending.resolver == "test_after_look"
    assert not session.can_cancel(P1)


def test_taking_a_looked_at_card_closes_the_look_and_replays_equal():
    session = _looking_session()

    session.submit(P1, DecisionResponse(("second",)))

    hand = session.game.table.zones[ZoneKey(P1, ZoneRole.HAND)].cards
    assert [card.id for card in hand] == ["second"]
    assert session.game.look is None
    assert session.log.replay() == session.game


def test_declining_a_looked_at_card_leaves_the_deck_as_it_was():
    session = _looking_session()

    session.submit(P1, DecisionResponse(()))

    assert [card.id for card in session.game.table.decks[FATE].cards] == ["third", "second", "top"]
    assert session.game.look is None


def test_placing_on_top_leaves_the_last_named_on_top():
    game = two_seat_game()
    _stack_fate(game.table, "deep")
    for card_id in ("a", "b", "c"):
        register(game.table, fate_card(card_id, P1))
        game.table.zones[ZoneKey(P1, ZoneRole.HAND)].add(game.table.cards_by_id[card_id])

    PlaceOnDeck(("a", "b", "c"), FATE).perform(game)

    assert [card.id for card in reversed(game.table.decks[FATE].cards)] == ["c", "b", "a", "deep"]


def test_placing_on_the_bottom_leaves_the_last_named_at_the_bottom():
    game = two_seat_game()
    _stack_fate(game.table, "deep")
    for card_id in ("a", "b", "c"):
        register(game.table, fate_card(card_id, P1))
        game.table.zones[ZoneKey(P1, ZoneRole.HAND)].add(game.table.cards_by_id[card_id])

    PlaceOnDeck(("a", "b", "c"), FATE, to_bottom=True).perform(game)

    assert [card.id for card in reversed(game.table.decks[FATE].cards)] == ["deep", "a", "b", "c"]


def test_placing_a_vanished_card_skips_it():
    game = two_seat_game()
    _stack_fate(game.table, "deep")

    PlaceOnDeck(("gone",), FATE).perform(game)

    assert [card.id for card in game.table.decks[FATE].cards] == ["deep"]


def test_arranging_nothing_asks_nothing():
    game = two_seat_game()

    resolve_effects(game, [Arrange(P1, (), "r", None)])

    assert game.pending is None


def test_a_second_look_over_an_open_one_raises():
    game = two_seat_game()
    _stack_fate(game.table, "top", "second")
    LookAtTop(P1, FATE, 1).perform(game)

    with pytest.raises(RuntimeError, match="already open"):
        LookAtTop(P1, FATE, 2).perform(game)


@choice_resolver("test_look_forgets_to_end")
def _take_without_ending(game, source_id, chosen, seat):
    return [MoveToHand(card_id, seat) for card_id in chosen]


register_ability(
    "test_forgetful_looker",
    Ability(
        timings=(ActionTiming.LIMITED,),
        label="look and forget",
        cost=lambda game, source: [],
        targets=itself,
        effects=lambda game, source, target: [
            LookAtTop(P1, FATE, 1),
            Choose(P1, top_of_deck(game, FATE, 1), 1, 1, "test_look_forgets_to_end", source.id),
        ],
    ),
)


def test_a_look_left_open_when_its_action_ends_raises():
    """A resolver that forgets EndLook would otherwise refuse every later cancel, by either seat,
    for the rest of the game."""
    state = TableState.empty_two_seat()
    put_in_play(state, holding("forgetful", printed_id="test_forgetful_looker"))
    _stack_fate(state, "top")
    session = EngineSession.start(state, P1)
    session.act(P1, ActivateAbility("forgetful"))
    session.submit(P1, DecisionResponse(("forgetful",)))

    with pytest.raises(RuntimeError, match="look still open"):
        session.submit(P1, DecisionResponse(("top",)))


def test_the_put_back_resolvers_raise_outside_a_look():
    with pytest.raises(ValueError, match="no look"):
        CHOICE_RESOLVERS[PUT_BACK_ON_TOP](two_seat_game(), None, ("a",), P1)
