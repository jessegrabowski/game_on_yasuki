from yasuki_core.engine.players import PlayerId
from yasuki_core.engine.rules.action_record import action_keywords
from yasuki_core.engine.rules.vocabulary import keywords
from yasuki_core.engine.rules.vocabulary.actions import (
    ActivateAbility,
    Lobby,
    Recruit,
    UseFavorAbility,
)

from tests.yasuki_core.engine.builders import holding, put_in_play, two_seat_game

P1 = PlayerId.P1


def test_no_action_has_no_keywords():
    assert action_keywords(two_seat_game()) == frozenset()


def test_an_ability_carries_the_keywords_its_registration_declares():
    game = two_seat_game()
    put_in_play(game, holding("court", printed_id="training_court"))
    game.action = ActivateAbility("court")

    assert action_keywords(game) == {keywords.POLITICAL}


def test_lobby_and_the_rulebook_favor_abilities_are_political():
    # ShE datasheet: "Political Open: ... Lobby" and "Political Open, (Favor): ... discard a Fate
    # card to draw a card".
    game = two_seat_game()

    game.action = Lobby()
    assert action_keywords(game) == {keywords.POLITICAL}
    game.action = UseFavorAbility("discard_to_draw")
    assert action_keywords(game) == {keywords.POLITICAL}


def test_a_recruit_carries_no_keywords():
    game = two_seat_game()
    game.action = Recruit("anything")

    assert action_keywords(game) == frozenset()
