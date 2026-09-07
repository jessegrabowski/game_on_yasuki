import pytest

from yasuki_core.engine.players import PlayerId
from yasuki_core.engine.rules.effects import Ask, GrantModifier
from yasuki_core.engine.rules.events import ProducingGold
from yasuki_core.engine.rules.state import once_per_turn
from yasuki_core.engine.rules.triggers import CHOICE_RESOLVERS, TriggerContext, _TRIGGERS
from yasuki_core.engine.rules.economy import (
    effective_gold_production,
    gold_handler,
    GOLD_HANDLERS,
    GOLD_SELF_GRANT,
    maximum_gold_production,
    recruit_discount,
    RECRUIT_DISCOUNTS,
    register_self_grant,
    SELF_GRANT,
)
from yasuki_core.engine.rules.modifiers import Stat
from yasuki_core.game_pieces.constants import Side
from yasuki_core.game_pieces.cards import L5RCard
from yasuki_core.game_pieces.prints import PersonalityPrint, StrongholdPrint

from tests.yasuki_core.engine.builders import two_seat_game

from tests.yasuki_core.engine.builders import holding, put_in_play, stronghold


def test_effective_gold_production_falls_back_to_printed_without_a_handler():
    game = two_seat_game()
    mine = put_in_play(game, holding("P1-mine", owner=PlayerId.P1, gold_production=3))
    assert effective_gold_production(game, mine) == 3


def test_a_non_producer_yields_zero_with_or_without_wealth_counters():
    game = two_seat_game()
    hero = put_in_play(
        game,
        L5RCard.of(
            PersonalityPrint, id="P1-hero", name="Hero", side=Side.DYNASTY, owner=PlayerId.P1
        ),
    )
    assert effective_gold_production(game, hero) == 0  # personalities have no gold_production

    # Wealth raises Gold Production; with no such stat there is nothing to raise, so a tokened
    # personality must not become a bowable gold source.
    hero.adjust_counter("wealth", 2)
    assert effective_gold_production(game, hero) == 0


def test_a_registered_handler_overrides_with_the_game_the_seat_and_targets():
    game = two_seat_game()
    me_sh = put_in_play(game, stronghold(PlayerId.P1, gold_production=8))
    put_in_play(game, stronghold(PlayerId.P2, gold_production=5))
    probe = put_in_play(
        game, holding("P1-h", owner=PlayerId.P1, printed_id="probe_holding", gold_production=2)
    )

    seen = {}

    @gold_handler("probe_holding")
    def _probe(card, game_, seat, targets):
        seen["call"] = (card, game_, seat, targets)
        return 99

    try:
        result = effective_gold_production(game, probe, targets=(me_sh,))
    finally:
        GOLD_HANDLERS.pop("probe_holding", None)

    assert result == 99
    card, seen_game, seat, targets = seen["call"]
    assert card is probe
    assert seen_game is game
    assert seat is PlayerId.P1
    assert targets == (me_sh,)


def _ancestral_estate(seat):
    return holding(
        f"{seat.name}-estate", owner=seat, printed_id="ancestral_estate", gold_production=3
    )


def test_ancestral_estate_gains_a_gold_while_outproduced():
    game = two_seat_game()
    put_in_play(game, stronghold(PlayerId.P1, gold_production=3))
    put_in_play(game, stronghold(PlayerId.P2, gold_production=5))
    estate = put_in_play(game, _ancestral_estate(PlayerId.P1))
    assert effective_gold_production(game, estate) == 4


def test_ancestral_estate_stays_at_base_against_an_equal_stronghold():
    # "higher", not "at least as high": a mirror match grants nothing to either seat.
    game = two_seat_game()
    put_in_play(game, stronghold(PlayerId.P1, gold_production=3))
    put_in_play(game, stronghold(PlayerId.P2, gold_production=3))
    estate = put_in_play(game, _ancestral_estate(PlayerId.P1))
    assert effective_gold_production(game, estate) == 3


def test_ancestral_estate_stays_at_base_while_outproducing():
    game = two_seat_game()
    put_in_play(game, stronghold(PlayerId.P1, gold_production=6))
    put_in_play(game, stronghold(PlayerId.P2, gold_production=2))
    estate = put_in_play(game, _ancestral_estate(PlayerId.P1))
    assert effective_gold_production(game, estate) == 3


def test_ancestral_estate_ignores_turn_order():
    """The bonus reads Stronghold production, not seating. P2 went second and gains nothing here."""
    game = two_seat_game()
    put_in_play(game, stronghold(PlayerId.P1, gold_production=3))
    put_in_play(game, stronghold(PlayerId.P2, gold_production=3))
    estate = put_in_play(game, _ancestral_estate(PlayerId.P2))
    assert effective_gold_production(game, estate) == 3


def test_ancestral_estate_treats_a_missing_stronghold_as_producing_nothing():
    game = two_seat_game()  # neither seat has a stronghold in play
    estate = put_in_play(game, _ancestral_estate(PlayerId.P1))
    assert effective_gold_production(game, estate) == 3

    put_in_play(game, stronghold(PlayerId.P2, gold_production=1))
    assert effective_gold_production(game, estate) == 4


def test_an_opponent_without_a_stronghold_never_grants_the_bonus():
    """A Sensei folds its Gold Production delta into the Stronghold, so a seat's own production can
    be negative. An absent opponent Stronghold still has nothing to compare and must not read as
    zero, which would clear a negative and grant the bonus."""
    game = two_seat_game()
    put_in_play(game, stronghold(PlayerId.P1, gold_production=-1))  # P2 holds no stronghold
    estate = put_in_play(game, _ancestral_estate(PlayerId.P1))
    assert effective_gold_production(game, estate) == 3


def test_dockside_market_adds_for_a_port_and_for_another_market():
    game = two_seat_game()
    dockside = put_in_play(
        game,
        holding(
            "P1-dockside",
            owner=PlayerId.P1,
            printed_id="dockside_market",
            keywords=("Market",),
            gold_production=2,
        ),
    )
    assert effective_gold_production(game, dockside) == 2  # alone

    put_in_play(game, holding("P1-port", owner=PlayerId.P1, keywords=("Port",)))
    assert effective_gold_production(game, dockside) == 3  # +1 for the Port

    put_in_play(game, holding("P1-market2", owner=PlayerId.P1, keywords=("Market",)))
    assert effective_gold_production(game, dockside) == 4  # +1 for another Market


def _jade_works(seat):
    return holding(
        f"{seat.name}-jadeworks",
        owner=seat,
        printed_id="jade_works",
        keywords=("Jade",),
        gold_production=3,
    )


def test_jade_works_adds_two_when_paying_for_a_jade_card():
    game = two_seat_game()
    works = put_in_play(game, _jade_works(PlayerId.P1))
    jade_target = holding("a-jade-card", owner=PlayerId.P1, keywords=("Jade",))
    produced = effective_gold_production(game, works, targets=(jade_target,))
    assert produced == works.gold_production + 2


def test_jade_works_produces_its_base_for_a_non_jade_card():
    game = two_seat_game()
    works = put_in_play(game, _jade_works(PlayerId.P1))
    plain = holding("a-plain-card", owner=PlayerId.P1, keywords=())
    assert effective_gold_production(game, works, targets=(plain,)) == 3


def test_jade_works_produces_its_base_with_no_target():
    game = two_seat_game()
    works = put_in_play(game, _jade_works(PlayerId.P1))
    assert effective_gold_production(game, works) == 3


def _shrine(seat):
    return holding(
        f"{seat.name}-shrine",
        owner=seat,
        printed_id="shrine_of_sincerity",
        keywords=("Temple",),
        gold_production=2,  # the base its Sincerity bonus is measured against
    )


def test_shrine_of_sincerity_adds_one_for_a_token_bearing_sincerity_card():
    game = two_seat_game()
    shrine = put_in_play(game, _shrine(PlayerId.P1))
    target = holding("a-sincerity-card", owner=PlayerId.P1, keywords=("Sincerity",))
    target.adjust_counter("sincerity", 2)
    assert effective_gold_production(game, shrine, targets=(target,)) == shrine.gold_production + 1


def test_shrine_produces_its_base_for_a_sincerity_card_without_tokens():
    game = two_seat_game()
    shrine = put_in_play(game, _shrine(PlayerId.P1))
    target = holding("a-sincerity-card", owner=PlayerId.P1, keywords=("Sincerity",))  # no tokens
    assert effective_gold_production(game, shrine, targets=(target,)) == 2


def test_shrine_produces_its_base_for_a_token_bearing_non_sincerity_card():
    game = two_seat_game()
    shrine = put_in_play(game, _shrine(PlayerId.P1))
    plain = holding("a-plain-card", owner=PlayerId.P1, keywords=())
    plain.adjust_counter("sincerity", 2)  # tokens but not a Sincerity card
    assert effective_gold_production(game, shrine, targets=(plain,)) == 2


def test_wealth_counters_raise_printed_production():
    game = two_seat_game()
    # A Rice-Farm-style holding: printed 0, so only its Wealth tokens make it a producer at all.
    farm = put_in_play(game, holding("P1-farm", owner=PlayerId.P1, gold_production=0))
    assert effective_gold_production(game, farm) == 0

    farm.adjust_counter("wealth", 2)
    assert effective_gold_production(game, farm) == 2


def test_wealth_counters_stack_on_a_handler_card():
    game = two_seat_game()
    put_in_play(game, stronghold(PlayerId.P1, gold_production=3))
    put_in_play(game, stronghold(PlayerId.P2, gold_production=5))  # outproduces P1
    estate = put_in_play(game, _ancestral_estate(PlayerId.P1))  # handler grants +1
    estate.adjust_counter("wealth", 1)
    assert effective_gold_production(game, estate) == 5  # printed 3 + outproduced 1 + wealth 1


def _clan_stronghold(seat, clan):
    return L5RCard.of(
        StrongholdPrint,
        id=f"{seat.name}-SH",
        name="SH",
        side=Side.STRONGHOLD,
        owner=seat,
        clan=clan,
    )


def test_teardrop_island_produces_three_for_mantis_two_otherwise():
    mantis = two_seat_game()
    put_in_play(mantis, _clan_stronghold(PlayerId.P1, "Mantis"))
    at_mantis = put_in_play(
        mantis, holding("tm", owner=PlayerId.P1, printed_id="teardrop_island", gold_production=0)
    )
    assert effective_gold_production(mantis, at_mantis) == 3

    other = two_seat_game()
    put_in_play(other, _clan_stronghold(PlayerId.P1, "Crab"))
    off_clan = put_in_play(
        other, holding("to", owner=PlayerId.P1, printed_id="teardrop_island", gold_production=0)
    )
    assert effective_gold_production(other, off_clan) == 2


def test_a_second_gold_handler_for_one_card_is_refused():
    # The dict would overwrite, leaving no trace of the handler that lost — so the check has to be at
    # registration, not on the registry afterwards.
    @gold_handler("guard_probe")
    def _first(card, game_, seat, targets):
        return 0

    try:
        with pytest.raises(ValueError, match="guard_probe already has a gold handler"):

            @gold_handler("guard_probe")
            def _second(card, game_, seat, targets):
                return 1
    finally:
        GOLD_HANDLERS.pop("guard_probe", None)


def test_a_second_recruit_discount_for_one_card_is_refused():
    @recruit_discount("guard_probe")
    def _first(card, game_, seat):
        return 0

    try:
        with pytest.raises(ValueError, match="guard_probe already has a recruit discount"):

            @recruit_discount("guard_probe")
            def _second(card, game_, seat):
                return 1
    finally:
        RECRUIT_DISCOUNTS.pop("guard_probe", None)


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

        once_per_turn(game, producer, SELF_GRANT)

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
        once_per_turn(game, producer, SELF_GRANT)
        producer.bow()
        producer.unbow()

        assert not producer.bowed
        assert maximum_gold_production(game, producer) == 2
    finally:
        GOLD_SELF_GRANT.pop("granting_probe", None)


def test_a_second_self_grant_for_one_card_is_refused():
    # A silent overwrite would leave affordability quoting whichever registration won the import
    # race, with no trace of the other.
    register_self_grant("guard_probe", 2)

    try:
        with pytest.raises(ValueError, match="guard_probe already grants itself"):
            register_self_grant("guard_probe", 3)
    finally:
        GOLD_SELF_GRANT.pop("guard_probe", None)


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
