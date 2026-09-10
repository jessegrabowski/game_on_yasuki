from yasuki_core.engine.players import PlayerId
from yasuki_core.engine.rules.stats.keyword_grants import (
    effective_keywords,
)
from yasuki_core.engine.rules.vocabulary.modifiers import Duration, KeywordGrant

from tests.yasuki_core.engine.builders import holding, put_in_play, two_seat_game


def _shrine_of_courtesy(seat):
    return holding(
        f"{seat.name}-courtesy",
        owner=seat,
        printed_id="shrine_of_courtesy",
        keywords=("Temple", "Unique"),
        gold_production=2,
        gold_cost=4,
    )


def test_a_card_without_a_grant_carries_only_its_printed_keywords():
    game = two_seat_game()
    plain = put_in_play(game, holding("P1-mine", owner=PlayerId.P1, keywords=("Farm",)))
    assert effective_keywords(game, plain) == frozenset({"Farm"})


def test_a_recorded_grant_gives_a_card_a_keyword_it_does_not_print():
    game = two_seat_game()
    plain = put_in_play(game, holding("P1-mine", owner=PlayerId.P1, keywords=("Farm",)))
    game.ongoing.append(KeywordGrant("P1-source", plain.id, "Cavalry", Duration.UNTIL_END_OF_TURN))

    assert effective_keywords(game, plain) == frozenset({"Farm", "Cavalry"})


def test_a_while_source_in_play_keyword_grant_drops_when_its_source_leaves():
    """The same lifetime a stat modifier gets: the CR files both under ongoing effects."""
    game = two_seat_game()
    plain = put_in_play(game, holding("P1-mine", owner=PlayerId.P1, keywords=("Farm",)))
    game.ongoing.append(
        KeywordGrant("gone", plain.id, "Cavalry", Duration.WHILE_SOURCE_IN_PLAY)
    )  # "gone" was never put into play

    assert effective_keywords(game, plain) == frozenset({"Farm"})


def test_shrine_of_courtesy_gains_legacy_while_you_went_second():
    game = two_seat_game()  # first_player is P1, so P2 went second
    shrine = put_in_play(game, _shrine_of_courtesy(PlayerId.P2))
    assert effective_keywords(game, shrine) == frozenset({"Temple", "Unique", "Legacy"})


def test_shrine_of_courtesy_keeps_its_printed_keywords_while_you_went_first():
    game = two_seat_game()
    shrine = put_in_play(game, _shrine_of_courtesy(PlayerId.P1))
    assert effective_keywords(game, shrine) == frozenset({"Temple", "Unique"})


def test_an_ownerless_card_falls_back_to_its_printed_keywords():
    # A grant reads its controller's position, which a card not yet dealt to a seat does not have.
    game = two_seat_game()
    orphan = holding("loose", printed_id="shrine_of_courtesy", keywords=("Temple",))
    assert effective_keywords(game, orphan) == frozenset({"Temple"})
