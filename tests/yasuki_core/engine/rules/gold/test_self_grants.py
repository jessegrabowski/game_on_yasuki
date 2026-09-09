import pytest

from yasuki_core.engine.players import PlayerId
from yasuki_core.engine.rules.effects import Ask, GrantModifier
from yasuki_core.engine.rules.vocabulary.events import ProducingGold
from yasuki_core.engine.rules.gold.production import effective_gold_production
from yasuki_core.engine.rules.gold.self_grants import (
    GOLD_SELF_GRANT,
    SELF_GRANT,
    maximum_gold_production,
    register_self_grant,
)
from yasuki_core.engine.rules.modifiers import Stat
from yasuki_core.engine.rules.state import claim_once_per_turn
from yasuki_core.engine.rules.triggers import CHOICE_RESOLVERS, TriggerContext, _TRIGGERS

from tests.yasuki_core.engine.builders import holding, put_in_play, two_seat_game


def test_maximum_gold_production_adds_the_declared_grant():
    """What affordability asks: the most a card could yield if its controller took what it offers."""
    register_self_grant("granting_probe", 2)

    try:
        game = two_seat_game()
        producer = put_in_play(game, holding("gp", printed_id="granting_probe", gold_production=2))

        assert effective_gold_production(game, producer) == 2
        assert maximum_gold_production(game, producer) == 4
    finally:
        GOLD_SELF_GRANT.pop("granting_probe", None)


def test_maximum_gold_production_composes_with_a_counter():
    """The declared number is a delta over what the card is worth now, not a ceiling of its own. A
    flat total would under-report the moment anything else raised the card."""
    register_self_grant("granting_probe", 2)

    try:
        game = two_seat_game()
        producer = put_in_play(
            game,
            holding("gp", printed_id="granting_probe", gold_production=2, counters={"wealth": 1}),
        )

        assert effective_gold_production(game, producer) == 3  # printed 2, plus the token
        assert maximum_gold_production(game, producer) == 5  # and the grant on top of that
    finally:
        GOLD_SELF_GRANT.pop("granting_probe", None)


def test_maximum_gold_production_matches_effective_for_a_card_that_declares_nothing():
    """Which is every producer but the handful that can raise their own yield."""
    game = two_seat_game()
    producer = put_in_play(game, holding("plain", gold_production=3))

    assert maximum_gold_production(game, producer) == effective_gold_production(game, producer)


def test_a_target_dependent_producer_needs_no_declaration():
    """Jade Works looks like the hard case and is not one: its yield varies with what it pays for,
    which `effective_gold_production` already handles, so its ceiling is that and nothing more."""
    game = two_seat_game()
    works = put_in_play(game, holding("jw", printed_id="jade_works", gold_production=2))
    jade = holding("jade", keywords=("Jade",))

    assert maximum_gold_production(game, works, targets=(jade,)) == effective_gold_production(
        game, works, targets=(jade,)
    )
    assert maximum_gold_production(game, works, targets=(jade,)) > maximum_gold_production(
        game, works
    )


def test_maximum_gold_production_stops_adding_a_grant_already_taken():
    """Once the card has granted itself, that Gold is inside what it is worth now. Adding the delta
    again would report a ceiling it cannot reach."""
    register_self_grant("granting_probe", 2)

    try:
        game = two_seat_game()
        producer = put_in_play(game, holding("gp", printed_id="granting_probe", gold_production=2))
        assert maximum_gold_production(game, producer) == 4

        claim_once_per_turn(game, producer, SELF_GRANT)

        assert maximum_gold_production(game, producer) == 2
    finally:
        GOLD_SELF_GRANT.pop("granting_probe", None)


def test_a_straightened_producer_does_not_regrant_itself():
    """The reason the tag is asked rather than `card.bowed`: a producer that bowed, granted itself
    and was straightened again is unbowed with the grant still live, and has nothing left to give."""
    register_self_grant("granting_probe", 2)

    try:
        game = two_seat_game()
        producer = put_in_play(game, holding("gp", printed_id="granting_probe", gold_production=2))
        claim_once_per_turn(game, producer, SELF_GRANT)
        producer.bow()
        producer.unbow()

        assert not producer.bowed
        assert maximum_gold_production(game, producer) == 2
    finally:
        GOLD_SELF_GRANT.pop("granting_probe", None)


@pytest.mark.parametrize("printed_id", sorted(GOLD_SELF_GRANT))
def test_every_declared_self_grant_matches_what_its_trigger_grants(printed_id):
    """The declared delta is a cached derivation, and this is what keeps the cache honest: run the
    card's own window trigger, answer its question yes, and sum what it actually grants.

    Derived on a board built for the test and thrown away, never on the live game. A trigger may
    claim a once-per-turn use as it fires, which is why affordability reads the declaration at
    runtime instead of deriving it — asking would spend the use.

    The owner went second so that a Courtesy card offers its grant at all; a board that failed a
    card's condition would compare nothing against nothing and pass whatever the card did.
    """
    game = two_seat_game(first_player=PlayerId.P2)
    producer = put_in_play(game, holding("probe", owner=PlayerId.P1, printed_id=printed_id))

    granted = 0
    for effect in _window_effects(game, producer):
        if isinstance(effect, Ask):
            effects = CHOICE_RESOLVERS[effect.resolver](
                game, effect.source_id, effect.subjects, effect.seat
            )
        else:
            effects = [effect]
        granted += sum(
            e.amount
            for e in effects
            if isinstance(e, GrantModifier)
            and e.stat is Stat.GOLD_PRODUCTION
            and e.target_id == producer.id
        )

    declared = GOLD_SELF_GRANT[printed_id](producer, game, PlayerId.P1)
    assert declared > 0, "the board does not satisfy this card's condition, so it proves nothing"
    assert granted == declared


def _window_effects(game, producer):
    """What ``producer``'s registered ``ProducingGold`` triggers return for its own window."""
    event = ProducingGold(producer.id, producer.owner)
    return [
        effect
        for trigger in _TRIGGERS.get(ProducingGold, {}).get(producer.printed_id, [])
        for effect in trigger(TriggerContext(game, producer, event))
    ]
