import pytest

from yasuki_core import ruleset
from yasuki_core.engine.players import PlayerId
from yasuki_core.engine.rules.abilities import owned_holdings
from yasuki_core.engine.rules.effects import Ask, GrantModifier
from yasuki_core.engine.rules.events import ProducingGold
from yasuki_core.engine.rules.state import once_per_turn
from yasuki_core.engine.rules.triggers import CHOICE_RESOLVERS, TriggerContext, _TRIGGERS
from yasuki_core.engine.rules.economy import (
    GOLD_HANDLERS,
    GOLD_SELF_GRANT,
    SELF_GRANT,
    KEYWORD_GRANTS,
    RECRUIT_DISCOUNTS,
    effective_gold_production,
    effective_keywords,
    gold_handler,
    maximum_gold_production,
    keyword_grant,
    opposing_states,
    is_clan,
    player_state,
    recruit_discount,
    register_self_grant,
)
from yasuki_core.engine.rules.modifiers import Duration, KeywordGrant, Stat
from yasuki_core.game_pieces.constants import Side
from yasuki_core.game_pieces.cards import L5RCard
from yasuki_core.game_pieces.prints import PersonalityPrint, StrongholdPrint

from tests.yasuki_core.engine.builders import two_seat_game

from tests.yasuki_core.engine.builders import holding, put_in_play, stronghold


def test_player_state_exposes_stronghold_holdings_gold_and_honor():
    game = two_seat_game()
    sh = put_in_play(game, stronghold(PlayerId.P1, gold_production=8))
    market = put_in_play(game, holding("P1-market", owner=PlayerId.P1, keywords=("Market",)))
    put_in_play(
        game, stronghold(PlayerId.P2, gold_production=5)
    )  # an opponent's card must not leak into me.in_play
    game.table.seats[PlayerId.P1].honor = 12
    game.gold[PlayerId.P1] = 3

    me = player_state(game, PlayerId.P1)

    assert me.stronghold is sh
    assert me.holdings == (market,)
    assert me.gold == 3 and me.honor == 12
    assert set(me.in_play) == {sh, market}


@pytest.mark.parametrize(
    "printed, asked, expected",
    [
        ("Lion", ruleset.LION, True),
        ("Lion Clan", ruleset.LION, True),
        ("Naga", ruleset.AKASHA, True),
        ("Akasha", ruleset.NAGA, True),
        ("Lion", ruleset.CRANE, False),
        ("Fox", "fox", False),
    ],
    ids=[
        "plain",
        "spelled-in-full",
        "naga-is-akasha",
        "akasha-is-naga",
        "other-clan",
        "no-alignment",
    ],
)
def test_is_clan_compares_alignments_rather_than_strings(printed, asked, expected):
    # Two cards print their clan as "Lion Clan" where 555 print "Lion", and the arc holds Naga and
    # Akasha to be one alignment. A string comparison would read all three as different clans, and
    # a discount keyed on one would quietly never apply.
    game = two_seat_game()
    put_in_play(game, stronghold(PlayerId.P1, clan=printed))

    assert is_clan(player_state(game, PlayerId.P1), asked) is expected


def test_a_seat_with_no_stronghold_plays_no_clan():
    game = two_seat_game()

    assert is_clan(player_state(game, PlayerId.P1), ruleset.LION) is False


def test_went_second_is_true_only_for_the_non_first_player():
    game = two_seat_game()  # first_player is P1
    assert player_state(game, PlayerId.P1).went_second is False
    assert player_state(game, PlayerId.P2).went_second is True


def test_controls_matches_a_keyword_and_can_exclude_a_card():
    game = two_seat_game()
    dockside = put_in_play(game, holding("P1-dockside", owner=PlayerId.P1, keywords=("Market",)))
    put_in_play(game, holding("P1-other-market", owner=PlayerId.P1, keywords=("Market",)))

    me = player_state(game, PlayerId.P1)

    assert me.controls("Market") is True
    assert me.controls("Port") is False
    # "another Market" — excluding the asking card still finds the second one.
    assert me.controls("Market", other_than=dockside) is True


def test_controls_other_than_the_only_match_is_false():
    game = two_seat_game()
    lone = put_in_play(game, holding("P1-lone", owner=PlayerId.P1, keywords=("Market",)))
    me = player_state(game, PlayerId.P1)
    assert me.controls("Market", other_than=lone) is False


def test_opposing_states_are_every_other_seat():
    game = two_seat_game()
    put_in_play(game, stronghold(PlayerId.P1, gold_production=8))
    opp_sh = put_in_play(game, stronghold(PlayerId.P2, gold_production=5))

    opponents = opposing_states(game, PlayerId.P1)

    assert [o.seat for o in opponents] == [PlayerId.P2]
    assert opponents[0].stronghold is opp_sh


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


def test_a_registered_handler_overrides_with_the_live_views_and_targets():
    game = two_seat_game()
    me_sh = put_in_play(game, stronghold(PlayerId.P1, gold_production=8))
    opp_sh = put_in_play(game, stronghold(PlayerId.P2, gold_production=5))
    probe = put_in_play(
        game, holding("P1-h", owner=PlayerId.P1, printed_id="probe_holding", gold_production=2)
    )

    seen = {}

    @gold_handler("probe_holding")
    def _probe(card, me, opponents, targets):
        seen["call"] = (card, me, opponents, targets)
        return 99

    try:
        result = effective_gold_production(game, probe, targets=(me_sh,))
    finally:
        GOLD_HANDLERS.pop("probe_holding", None)

    assert result == 99
    card, me, opponents, targets = seen["call"]
    assert card is probe
    assert me.stronghold is me_sh
    assert [o.stronghold for o in opponents] == [opp_sh]
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
    def _first(card, me, opponents, targets):
        return 0

    try:
        with pytest.raises(ValueError, match="guard_probe already has a gold handler"):

            @gold_handler("guard_probe")
            def _second(card, me, opponents, targets):
                return 1
    finally:
        GOLD_HANDLERS.pop("guard_probe", None)


def test_a_second_recruit_discount_for_one_card_is_refused():
    @recruit_discount("guard_probe")
    def _first(card, me, opponents):
        return 0

    try:
        with pytest.raises(ValueError, match="guard_probe already has a recruit discount"):

            @recruit_discount("guard_probe")
            def _second(card, me, opponents):
                return 1
    finally:
        RECRUIT_DISCOUNTS.pop("guard_probe", None)


# --- conditionally granted keywords ----------------------------------------------------------------


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


def test_a_stronghold_printing_several_clans_plays_them_all():
    """A Stronghold is a card, and a card may print more than one clan — so the seat answers to each
    of them, the way a multi-clan Personality answers to each of its own."""
    game = two_seat_game()
    put_in_play(game, stronghold(PlayerId.P1, clans=("Lion", "Crane")))
    me = player_state(game, PlayerId.P1)

    assert is_clan(me, "Lion")
    assert is_clan(me, "Crane")
    assert not is_clan(me, "Scorpion")


def test_a_recorded_grant_gives_a_card_a_keyword_it_does_not_print():
    game = two_seat_game()
    plain = put_in_play(game, holding("P1-mine", owner=PlayerId.P1, keywords=("Farm",)))
    game.modifiers.append(
        KeywordGrant("P1-source", plain.id, "Cavalry", Duration.UNTIL_END_OF_TURN)
    )

    assert effective_keywords(game, plain) == frozenset({"Farm", "Cavalry"})


def test_a_while_source_in_play_keyword_grant_drops_when_its_source_leaves():
    """The same lifetime a stat modifier gets: the CR files both under ongoing effects."""
    game = two_seat_game()
    plain = put_in_play(game, holding("P1-mine", owner=PlayerId.P1, keywords=("Farm",)))
    game.modifiers.append(
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


def test_a_second_keyword_grant_for_one_card_is_refused():
    @keyword_grant("guard_probe")
    def _first(card, me, opponents):
        return ()

    try:
        with pytest.raises(ValueError, match="guard_probe already has a keyword grant"):

            @keyword_grant("guard_probe")
            def _second(card, me, opponents):
                return ("Legacy",)
    finally:
        KEYWORD_GRANTS.pop("guard_probe", None)


def test_owned_holdings_without_a_keyword_takes_them_all():
    """Kitsu Watanabe spends "your target Holding", any of them, so the lookup answers that too
    rather than making the card scan the battlefield for itself."""
    game = two_seat_game()
    quay = put_in_play(game, holding("P1-quay", owner=PlayerId.P1, keywords=("Port",)))
    plain = put_in_play(game, holding("P1-plain", owner=PlayerId.P1))
    put_in_play(game, holding("P2-theirs", owner=PlayerId.P2))
    put_in_play(game, stronghold(PlayerId.P1, gold_production=5))

    assert owned_holdings(game, PlayerId.P1) == [quay, plain]


def test_a_keyword_lookup_sees_a_keyword_the_card_grants_itself():
    """Keyword lookups read effective keywords, so a card whose own condition grants one is found by
    the same searches as a card that prints it. Registered here rather than leaning on a real card:
    today only Shrine of Courtesy grants anything, and it grants Legacy, which no lookup asks for."""
    game = two_seat_game()
    granted = put_in_play(game, holding("P1-docks", owner=PlayerId.P1, printed_id="keyword_probe"))
    printed = put_in_play(game, holding("P1-quay", owner=PlayerId.P1, keywords=("Port",)))

    assert owned_holdings(game, PlayerId.P1, "Port") == [printed]

    @keyword_grant("keyword_probe")
    def _grants_port(card, me, opponents):
        return ("Port",)

    try:
        assert owned_holdings(game, PlayerId.P1, "Port") == [granted, printed]
    finally:
        KEYWORD_GRANTS.pop("keyword_probe", None)


def test_maximum_gold_production_adds_the_declared_grant():
    """What affordability asks: the most a card could yield if its controller took what it offers."""
    GOLD_SELF_GRANT["granting_probe"] = 2

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
    GOLD_SELF_GRANT["granting_probe"] = 2

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
    GOLD_SELF_GRANT["granting_probe"] = 2

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
    GOLD_SELF_GRANT["granting_probe"] = 2

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
    """
    game = two_seat_game()
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

    assert granted == GOLD_SELF_GRANT[printed_id]


def _window_effects(game, producer):
    """What ``producer``'s registered ``ProducingGold`` triggers return for its own window."""
    event = ProducingGold(producer.id, producer.owner)
    return [
        effect
        for trigger in _TRIGGERS.get(ProducingGold, {}).get(producer.printed_id, [])
        for effect in trigger(TriggerContext(game, producer, event))
    ]
