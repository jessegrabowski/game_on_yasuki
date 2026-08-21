import pytest

from yasuki_core.engine.players import PlayerId, Rulebook
from yasuki_core.engine.rules import flow
from yasuki_core.engine.rules.decisions import ChooseCards, DecisionResponse
from yasuki_core.engine.rules.economy import effective_gold_production
from yasuki_core.engine.rules.events import CardDiscarded, Destroyed, EnteredPlay, TurnStarted
from yasuki_core.engine.rules.effects import (
    AdjustCounter,
    Choose,
    Destroy,
    Discard,
    IgnoreHonorRequirements,
)
from yasuki_core.engine.rules.triggers import (
    CHOICE_RESOLVERS,
    apply_effect,
    choice_resolver,
    enforce_state_rules,
    fire,
    on,
    resolve_effects,
)
from yasuki_core.engine.table import DeckKey, ZoneKey, ZoneRole
from yasuki_core.game_pieces.constants import Side
from yasuki_core.game_pieces.counters import WEALTH
from yasuki_core.game_pieces.cards import L5RCard
from yasuki_core.game_pieces.prints import HoldingPrint, PersonalityPrint

from tests.yasuki_core.engine.builders import (
    fate_card,
    holding,
    province_card,
    put_in_play,
    two_seat_game,
)


# A test-only trigger: any card printed as "test_probe" gives itself a Wealth token when a card
# enters play. It lets a co-firing subscriber do observable work, which no real EnteredPlay card
# pairs with Wheat Farm to do.
@on(EnteredPlay, "test_probe")
def _probe_gains_wealth(ctx):
    return [AdjustCounter(ctx.card.id, WEALTH, 1)]


# A test-only trigger that takes a Wealth token for any discard at all, whatever caused it. The
# real discard-watcher, Caravansary, filters on the cause, so it cannot double as a probe for
# whether the event fired.
@on(CardDiscarded, "test_discard_probe")
def _probe_sees_any_discard(ctx):
    return [AdjustCounter(ctx.card.id, WEALTH, 1)]


# A test-only trigger writing what caused each destruction onto its own card, the way the probes
# above do observable work on theirs. No shipped card reads the cause yet — the one Destroyed
# subscriber, Rural Market, filters on the destroyed card's owner — and a Personality cannot watch
# its own death while triggers are collected from the battlefield.
@on(Destroyed, "test_death_probe")
def _probe_records_the_cause(ctx):
    ctx.card.set_note(ctx.event.cause.name)
    return []


# A test-only trigger returning effects on both sides of a Choose: a token to itself, the choice,
# then a second token to itself. Proves the effects after a Choose still resolve on resume.
@on(EnteredPlay, "test_sandwich")
def _sandwich_around_a_choice(ctx):
    return [
        AdjustCounter(ctx.card.id, WEALTH, 1),
        Choose(ctx.card.owner, (), 0, 0, "test_sandwich", ctx.card.id),
        AdjustCounter(ctx.card.id, WEALTH, 1),
    ]


@choice_resolver("test_sandwich")
def _sandwich_grant(game, source_id, chosen, seat):
    return [AdjustCounter(source_id, WEALTH, 1)]


def test_ignore_honor_requirements_effect_sets_the_seat_flag():
    game = two_seat_game()
    assert game.table.seats[PlayerId.P1].ignores_honor_requirements is False
    apply_effect(game, IgnoreHonorRequirements(PlayerId.P1))
    assert game.table.seats[PlayerId.P1].ignores_honor_requirements is True
    assert game.table.seats[PlayerId.P2].ignores_honor_requirements is False


def _rice_farm(game, seat=PlayerId.P1, card_id="P1-farm"):
    # Rice Farm's printed Gold Production is 0; its output is entirely the Wealth tokens it accrues.
    farm = holding(
        card_id,
        printed_id="rice_farm",
        name="Rice Farm",
        owner=seat,
        gold_production=0,
    )
    put_in_play(game, farm)
    return farm


def test_turn_start_gives_the_rice_farm_a_wealth_token():
    game = two_seat_game()
    farm = _rice_farm(game)

    fire(game, TurnStarted(PlayerId.P1))

    assert farm.counters == {"wealth": 1}


def test_the_same_card_awaiting_recruitment_in_a_province_does_not_react():
    # Triggers key on printed_id, so the unbought copy in a Province is indistinguishable from the
    # one in play except by where collection looks — and Rice Farm's guard reads the seat and the
    # cap, never whether it is in play. Scanning past the battlefield would accrue Gold Production
    # on a card nobody paid for; a trigger would first have to declare where it functions.
    game = two_seat_game()
    in_play = _rice_farm(game, card_id="P1-farm")
    unbought = province_card(game, "P1-unbought", seat=PlayerId.P1, printed_id="rice_farm")

    fire(game, TurnStarted(PlayerId.P1))

    assert in_play.counters == {"wealth": 1}
    assert unbought.counters == {}


def test_wealth_accrues_each_turn_up_to_the_cap_of_four():
    game = two_seat_game()
    farm = _rice_farm(game)

    for _ in range(6):
        fire(game, TurnStarted(PlayerId.P1))

    assert farm.counters == {"wealth": 4}  # "will not have more than four Wealth tokens"


def test_one_event_fans_out_to_every_subscribed_card():
    game = two_seat_game()
    first = _rice_farm(game, card_id="P1-farm-a")
    second = _rice_farm(game, card_id="P1-farm-b")

    fire(game, TurnStarted(PlayerId.P1))

    assert first.counters == {"wealth": 1} and second.counters == {"wealth": 1}


def test_the_token_only_lands_on_the_turn_players_own_farm():
    game = two_seat_game()
    farm = _rice_farm(game)  # owned by P1

    fire(game, TurnStarted(PlayerId.P2))  # "after your turn begins" — not P1's turn

    assert farm.counters == {}


def test_accrued_wealth_raises_the_farms_effective_gold_production():
    game = two_seat_game()
    farm = _rice_farm(game)
    assert effective_gold_production(game, farm) == 0

    fire(game, TurnStarted(PlayerId.P1))
    fire(game, TurnStarted(PlayerId.P1))

    assert effective_gold_production(game, farm) == 2  # printed 0 + two Wealth tokens


def test_flow_emits_the_turn_start_event_from_begin_turn():
    # The wiring test: begin_game runs _begin_turn, which must fire TurnStarted.
    game = two_seat_game()
    farm = _rice_farm(game)

    flow.begin_game(game)

    assert farm.counters == {"wealth": 1}


def _caravansary(game, seat=PlayerId.P1, card_id="P1-caravansary"):
    caravansary = holding(
        card_id,
        printed_id="caravansary",
        name="Caravansary",
        owner=seat,
        gold_production=2,
    )
    put_in_play(game, caravansary)
    return caravansary


def test_flow_emits_the_discard_event_from_the_end_of_turn_discard():
    # The wiring test: _apply_discard moves a hand card to the discard and must fire CardDiscarded.
    game = two_seat_game()
    probe = holding("P1-probe", printed_id="test_discard_probe", owner=PlayerId.P1)
    put_in_play(game, probe)
    fate = fate_card("P1-f", PlayerId.P1)
    game.table.cards_by_id[fate.id] = fate
    game.table.zones[ZoneKey(PlayerId.P1, ZoneRole.HAND)].add(fate)

    flow._apply_discard(game, PlayerId.P1, ("P1-f",))

    assert probe.counters == {"wealth": 1}


def _aoki(game, seat=PlayerId.P1, card_id="P1-aoki"):
    aoki = L5RCard.of(
        PersonalityPrint,
        id=card_id,
        printed_id="shosuro_aoki_yoritomo_kayoko_experienced",
        name="Shosuro Aoki",
        side=Side.DYNASTY,
        owner=seat,
        chi=3,
    )
    put_in_play(game, aoki)
    return aoki


def _seed_fate_deck(game, seat, count):
    deck = game.table.decks[DeckKey(seat, Side.FATE)]
    deck.cards = [fate_card(f"{seat.name}-fd{i}", seat) for i in range(count)]
    for card in deck.cards:
        game.table.cards_by_id[card.id] = card


def _hand_size(game, seat):
    return len(game.table.zones[ZoneKey(seat, ZoneRole.HAND)].cards)


def test_gaining_wealth_cascades_into_aokis_draw():
    # The cascade: turn start -> Rice Farm gains wealth -> CounterGained -> Aoki draws a card.
    game = two_seat_game()
    _rice_farm(game)
    _aoki(game)
    _seed_fate_deck(game, PlayerId.P1, 3)
    assert _hand_size(game, PlayerId.P1) == 0

    fire(game, TurnStarted(PlayerId.P1))

    assert _hand_size(game, PlayerId.P1) == 1


def test_aoki_draws_at_most_once_per_turn():
    game = two_seat_game()
    _rice_farm(game, card_id="P1-farm-a")
    _rice_farm(game, card_id="P1-farm-b")  # two wealth gains in one turn
    _aoki(game)
    _seed_fate_deck(game, PlayerId.P1, 3)

    fire(game, TurnStarted(PlayerId.P1))

    assert _hand_size(game, PlayerId.P1) == 1  # two CounterGained events, one draw


def test_aoki_draws_again_on_the_next_turn():
    # The once-per-turn claim is turn-scoped: a fresh turn re-arms Aoki's draw.
    game = two_seat_game()
    _rice_farm(game)
    _aoki(game)
    _seed_fate_deck(game, PlayerId.P1, 3)

    fire(game, TurnStarted(PlayerId.P1))
    game.turn += 1
    fire(game, TurnStarted(PlayerId.P1))

    assert _hand_size(game, PlayerId.P1) == 2


def test_aoki_ignores_wealth_gained_on_an_opponents_holding():
    game = two_seat_game()
    _aoki(game, seat=PlayerId.P1)
    _rice_farm(game, seat=PlayerId.P2, card_id="P2-farm")
    _seed_fate_deck(game, PlayerId.P1, 3)

    fire(game, TurnStarted(PlayerId.P2))  # P2's farm gains wealth — not Aoki's Holding

    assert _hand_size(game, PlayerId.P1) == 0


def _rural_market(game, seat=PlayerId.P1, card_id="P1-rural"):
    market = holding(
        card_id,
        printed_id="rural_market",
        name="Rural Market",
        owner=seat,
        gold_production=0,
    )
    put_in_play(game, market)
    return market


def _keyworded_farm(game, seat=PlayerId.P1, card_id="P1-a-farm"):
    farm = holding(
        card_id,
        printed_id="a_farm",
        name="A Farm",
        owner=seat,
        gold_production=1,
        keywords=("Farm",),
    )
    put_in_play(game, farm)
    return farm


def test_destroy_effect_discards_the_card_and_emits_destroyed():
    game = two_seat_game()
    farm = _keyworded_farm(game)

    events = apply_effect(game, Destroy(farm.id, PlayerId.P1))

    assert events == [Destroyed(farm.id, PlayerId.P1)]
    assert farm not in game.table.battlefield.cards
    assert farm in game.table.zones[ZoneKey(PlayerId.P1, ZoneRole.DYNASTY_DISCARD)].cards


def test_destroy_routes_a_fate_card_to_the_fate_discard():
    game = two_seat_game()
    follower = fate_card("P1-follower", PlayerId.P1)
    put_in_play(game, follower)

    apply_effect(game, Destroy(follower.id, PlayerId.P1))

    assert follower in game.table.zones[ZoneKey(PlayerId.P1, ZoneRole.FATE_DISCARD)].cards


def test_destroying_your_farm_gives_rural_market_a_wealth_token():
    game = two_seat_game()
    rural = _rural_market(game)
    farm = _keyworded_farm(game)

    fire(game, Destroyed(farm.id, PlayerId.P1))

    assert rural.counters == {"wealth": 1}


def test_rural_market_ignores_a_non_farm_destruction():
    game = two_seat_game()
    rural = _rural_market(game)
    holding = _caravansary(game)  # a Holding, but not a Farm

    fire(game, Destroyed(holding.id, PlayerId.P1))

    assert rural.counters == {}


def test_rural_market_ignores_an_opponents_farm():
    game = two_seat_game()
    rural = _rural_market(game, seat=PlayerId.P1)
    farm = _keyworded_farm(game, seat=PlayerId.P2, card_id="P2-a-farm")

    fire(game, Destroyed(farm.id, PlayerId.P1))

    assert rural.counters == {}


def test_rural_market_gains_wealth_when_it_enters_play():
    game = two_seat_game()
    rural = _rural_market(game)

    fire(game, EnteredPlay(rural.id))

    assert rural.counters == {"wealth": 1}


def test_rural_market_ignores_another_cards_entry():
    game = two_seat_game()
    rural = _rural_market(game)
    other = _keyworded_farm(game)  # some other Holding entering play

    fire(game, EnteredPlay(other.id))

    assert rural.counters == {}  # "after THIS Holding enters play" — only its own entry


def test_flow_emits_entered_play_from_recruit_resolution():
    # The wiring test: _resolve_recruit moves the card into play and must fire EnteredPlay.
    game = two_seat_game()
    rural = holding(
        "P1-rural",
        printed_id="rural_market",
        name="Rural Market",
        owner=PlayerId.P1,
        gold_production=0,
    )
    game.table.cards_by_id[rural.id] = rural  # being recruited, not yet on the battlefield

    flow._resolve_recruit(game, PlayerId.P1, rural.id)

    assert rural in game.table.battlefield.cards
    assert rural.counters == {"wealth": 1}


def _wheat_farm(game, seat=PlayerId.P1, card_id="P1-wheat"):
    farm = holding(
        card_id,
        printed_id="wheat_farm",
        name="Wheat Farm",
        owner=seat,
        gold_production=2,
        keywords=("Farm",),
    )
    put_in_play(game, farm)
    return farm


def test_wheat_farm_offers_no_choice_without_other_farms():
    game = two_seat_game()
    wheat = _wheat_farm(game)

    fire(game, EnteredPlay(wheat.id))

    assert game.pending is None
    assert wheat.counters == {}  # it seeds no token on itself


def test_wheat_farm_pauses_to_choose_among_your_other_farms():
    game = two_seat_game()
    wheat = _wheat_farm(game)
    other = _keyworded_farm(game, card_id="P1-other-farm")

    fire(game, EnteredPlay(wheat.id))

    pending = game.pending
    assert isinstance(pending, ChooseCards)
    assert pending.seat is PlayerId.P1
    assert pending.candidates == (other.id,)  # excludes the Wheat Farm itself
    assert (pending.minimum, pending.maximum) == (0, 1)  # zero to two, capped by the one candidate


def test_wheat_farm_excludes_non_farms_and_opponents_farms():
    game = two_seat_game()
    wheat = _wheat_farm(game)
    _caravansary(game)  # a Holding, but not a Farm
    _keyworded_farm(game, seat=PlayerId.P2, card_id="P2-farm")  # a Farm, but the opponent's

    fire(game, EnteredPlay(wheat.id))

    assert game.pending is None  # no eligible target — no choice raised


def test_wheat_farm_grants_a_token_to_each_chosen_farm():
    game = two_seat_game()
    wheat = _wheat_farm(game)
    first = _keyworded_farm(game, card_id="P1-farm-a")
    second = _keyworded_farm(game, card_id="P1-farm-b")

    fire(game, EnteredPlay(wheat.id))
    flow.submit(game, DecisionResponse((first.id, second.id)))

    assert first.counters == {"wealth": 1} and second.counters == {"wealth": 1}
    assert wheat.counters == {}
    assert game.pending is None


def test_wheat_farm_choice_is_optional():
    game = two_seat_game()
    wheat = _wheat_farm(game)
    other = _keyworded_farm(game, card_id="P1-other-farm")

    fire(game, EnteredPlay(wheat.id))
    flow.submit(game, DecisionResponse(()))  # decline — give none

    assert other.counters == {}
    assert game.pending is None


def test_wheat_farm_token_cascades_into_aokis_draw():
    game = two_seat_game()
    wheat = _wheat_farm(game)
    other = _keyworded_farm(game, card_id="P1-other-farm")
    _aoki(game)
    _seed_fate_deck(game, PlayerId.P1, 3)

    fire(game, EnteredPlay(wheat.id))
    flow.submit(game, DecisionResponse((other.id,)))

    assert _hand_size(game, PlayerId.P1) == 1  # the granted token drew Aoki a card


def test_wheat_farm_caps_the_choice_at_two_farms():
    game = two_seat_game()
    wheat = _wheat_farm(game)
    for i in range(3):
        _keyworded_farm(game, card_id=f"P1-farm-{i}")

    fire(game, EnteredPlay(wheat.id))

    pending = game.pending
    assert isinstance(pending, ChooseCards)
    assert len(pending.candidates) == 3
    assert pending.maximum == 2  # "zero to two" — capped however many Farms you control


def _probe(game, seat=PlayerId.P1, card_id="P1-z-probe"):
    probe = L5RCard.of(
        HoldingPrint,
        id=card_id,
        printed_id="test_probe",
        name="Probe",
        side=Side.DYNASTY,
        owner=seat,
    )
    put_in_play(game, probe)
    return probe


def test_a_trigger_stashed_by_the_choice_still_applies_its_effect_on_resume():
    # The probe also fires on the Wheat Farm's entry but sorts after it, so the pausing choice stashes
    # the probe's trigger; resuming must run it and land its Wealth token, not merely drain the stack.
    game = two_seat_game()
    wheat = _wheat_farm(game, card_id="P1-a-wheat")
    other = _keyworded_farm(game, card_id="P1-other-farm")
    probe = _probe(game)

    fire(game, EnteredPlay(wheat.id))
    assert isinstance(game.pending, ChooseCards)  # paused with the probe's trigger stashed
    flow.submit(game, DecisionResponse((other.id,)))

    assert other.counters == {"wealth": 1}  # the choice resolved
    assert probe.counters == {"wealth": 1}  # the stashed trigger resumed and applied its effect
    assert game.stack == []


def test_effects_after_a_choice_in_the_same_trigger_still_resolve():
    game = two_seat_game()
    sandwich = holding(
        "P1-sandwich", printed_id="test_sandwich", name="Sandwich", owner=PlayerId.P1
    )
    put_in_play(game, sandwich)

    fire(game, EnteredPlay(sandwich.id))
    assert isinstance(game.pending, ChooseCards)
    flow.submit(game, DecisionResponse(()))

    # One token before the choice, one from the resolver, one after: none dropped at the pause.
    assert sandwich.counters == {"wealth": 3}


def test_a_second_resolver_for_one_choice_kind_is_refused():
    # A pending decision names its resolver by string; a silent overwrite would change what an
    # already-paused choice resolves to.
    @choice_resolver("guard_probe")
    def _first(game, source_id, chosen, seat):
        return []

    try:
        with pytest.raises(ValueError, match="guard_probe already has a choice resolver"):

            @choice_resolver("guard_probe")
            def _second(game, source_id, chosen, seat):
                return []
    finally:
        CHOICE_RESOLVERS.pop("guard_probe", None)


def test_chi_death_names_the_rule_rather_than_a_seat():
    """No player killed him, so nothing that asks "was this my doing?" may claim it."""
    game = two_seat_game()
    probe = put_in_play(game, holding("P1-probe", printed_id="test_death_probe", owner=PlayerId.P1))
    doomed = L5RCard.of(
        PersonalityPrint, id="doomed", name="doomed", side=Side.DYNASTY, owner=PlayerId.P1, chi=0
    )
    put_in_play(game, doomed)

    enforce_state_rules(game)

    assert probe.note == Rulebook.CHI_DEATH.name


def test_a_card_driven_destruction_names_the_seat_whose_card_did_it():
    """The other half: a destruction someone chose still says who, which is what separates it from
    the rulebook's."""
    game = two_seat_game()
    probe = put_in_play(game, holding("P1-probe", printed_id="test_death_probe", owner=PlayerId.P1))
    victim = put_in_play(game, holding("victim", owner=PlayerId.P2))

    resolve_effects(game, [Destroy(victim.id, PlayerId.P1)])

    assert probe.note == PlayerId.P1.name


def test_a_card_reacts_to_its_own_destruction(reacting):
    """ "After this card is destroyed" is only reachable from the discard pile: the unit leaves play
    before the destruction is announced, so a card gone from the battlefield still has to be
    gathered for the event that named it."""
    game = two_seat_game()
    doomed = put_in_play(game, holding("P1-doomed", printed_id="departure_probe"))
    seen: list[str] = []
    reacting(Destroyed, "departure_probe", lambda ctx: seen.append(ctx.event.card_id) or [])

    resolve_effects(game, [Destroy(doomed.id, PlayerId.P1)])

    assert seen == [doomed.id]


def test_a_card_reacts_to_its_own_discard(reacting):
    """The other departure: a discard announces itself the same way a destruction does."""
    game = two_seat_game()
    doomed = put_in_play(game, holding("P1-doomed", printed_id="departure_probe"))
    seen: list[str] = []
    reacting(CardDiscarded, "departure_probe", lambda ctx: seen.append(ctx.event.card_id) or [])

    resolve_effects(game, [Discard(doomed.id, PlayerId.P1)])

    assert seen == [doomed.id]


def test_a_departed_card_reacts_to_nothing_but_its_own_leaving(reacting):
    """It answers for its own departure and stops there. A card in a discard pile is out of the
    game's business, and a rule that let it keep watching the board would pay it for destructions it
    is in no position to see."""
    game = two_seat_game()
    gone = put_in_play(game, holding("P1-gone", printed_id="departure_probe"))
    bystander = put_in_play(game, holding("P1-other", printed_id="plain_holding"))
    seen: list[str] = []
    reacting(Destroyed, "departure_probe", lambda ctx: seen.append(ctx.event.card_id) or [])
    resolve_effects(game, [Destroy(gone.id, PlayerId.P1)])
    seen.clear()

    resolve_effects(game, [Destroy(bystander.id, PlayerId.P1)])

    assert seen == []


def test_a_card_killed_as_it_arrives_still_takes_no_enter_play_trigger(reacting):
    """The narrowness is the point: only a departure reaches a card off the battlefield. An arrival
    does not, so a Personality a state rule killed on sight cannot go on to take his enter-play
    trait — which is what settling those rules before announcing the arrival is for."""
    game = two_seat_game()
    doomed = put_in_play(game, holding("P1-doomed", printed_id="departure_probe"))
    seen: list[str] = []
    reacting(EnteredPlay, "departure_probe", lambda ctx: seen.append(ctx.event.card_id) or [])
    resolve_effects(game, [Destroy(doomed.id, PlayerId.P1)])

    fire(game, EnteredPlay(doomed.id))

    assert seen == []
