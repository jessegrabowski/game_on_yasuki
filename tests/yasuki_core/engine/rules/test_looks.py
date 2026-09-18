import pytest

from yasuki_core.engine.players import PlayerId
from yasuki_core.engine.rules.abilities.model import Ability, itself
from yasuki_core.engine.rules.abilities.registry import register_ability
from yasuki_core.engine.rules.board.queries import remaining_look, top_of_deck
from yasuki_core.engine.rules.effects import Choose, EndLook, LookAtTop, MoveToDeck, MoveToHand
from yasuki_core.engine.rules.triggers import choice_resolver
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
