import pytest

from yasuki_core import ruleset
from yasuki_core.engine.players import PlayerId, Rulebook
from yasuki_core.engine.rules.rulebook import recruit
from yasuki_core.engine.rules.turn import action_sequence, sequence
from yasuki_core.engine.rules.turn.structure import (
    END_OF_BATTLE,
    END_OF_TURN,
    ActionRound,
    RoundKind,
)
from yasuki_core.engine.rules.vocabulary.modifiers import (
    Condition,
    ConditionalModifier,
    Duration,
    LobbyModifier,
    Modifier,
    Negation,
    Stat,
)
from yasuki_core.engine.rules.vocabulary.decisions import (
    Confirm,
    ChooseCards,
    ChooseDiscard,
    ChooseNextTrigger,
    DecisionResponse,
)
from yasuki_core.engine.rules.gold.production import effective_gold_production
from yasuki_core.engine.rules.vocabulary.game_events import (
    Bowed,
    CardDiscarded,
    ConditionFulfilled,
    CounterChanged,
    Destroyed,
    Destroying,
    DuelDeclared,
    EnteredPlay,
    HonorChanged,
    NextTime,
    ProducingGold,
    TurnBoundary,
)
from yasuki_core.engine.rules.vocabulary.segments import Boundary
from yasuki_core.engine.rules.vocabulary.locations import CardLocation
from yasuki_core.engine.rules.vocabulary.work import Provenance
from yasuki_core.engine.rules.projection import project
from yasuki_core.engine.rules.state import GameState
from yasuki_core.engine.rules.effects import (
    Ask,
    AdjustCounter,
    Adjustment,
    ApplyEffects,
    Banish,
    Choose,
    DelayedEffect,
    Destroy,
    Discard,
    DiscardFromHand,
    GainHonor,
    GrantModifier,
    GrantNegation,
    Bow,
    MoveToHand,
    Negated,
    PutIntoPlay,
    Simultaneously,
    To,
)
from yasuki_core.engine.rules.triggers import (
    CHOICE_RESOLVERS,
    EffectsFrame,
    EventsFrame,
    ResumeCascade,
    apply_effect,
    choice_resolver,
    enforce_state_based_actions,
    fire,
    fire_all,
    lapse_ongoing,
    on,
    reach_moment,
    resolve_delayed,
    resolve_action_effects,
    resolve_effects,
    resume_paused_cascade,
)
from yasuki_core.engine.rules.interrupts import Replacement, forecast
from yasuki_core.engine.table import DeckKey, Location, ZoneKey, ZoneRole
from yasuki_core.game_pieces.constants import Side
from yasuki_core.game_pieces.counters import WEALTH, counter_from_key
from yasuki_core.game_pieces.cards import L5RCard
from yasuki_core.game_pieces.prints import FatePrint, HoldingPrint, PersonalityPrint

from tests.yasuki_core.engine.builders import (
    attached,
    attachment,
    fate_card,
    holding,
    personality,
    province_card,
    put_in_play,
    register,
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
# above do observable work on theirs. No shipped card reads the cause yet: the one Destroyed
# subscriber, Rural Market, filters on the destroyed card's owner. A Personality cannot watch
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


def _resolve_a_held_effect(game):
    game.delayed = [(END_OF_TURN, GainHonor(PlayerId.P1, 1))]
    resolve_delayed(game, END_OF_TURN)


@pytest.mark.parametrize(
    ("driver", "drive"),
    [
        ("fire", lambda game: fire(game, TurnBoundary(PlayerId.P1, Boundary.BEGINNING))),
        ("fire_all", lambda game: fire_all(game, [TurnBoundary(PlayerId.P1, Boundary.BEGINNING)])),
        ("resolve_effects", lambda game: resolve_effects(game, [GainHonor(PlayerId.P1, 1)])),
        ("resolve_effects", _resolve_a_held_effect),
        ("enforce_state_based_actions", enforce_state_based_actions),
    ],
    ids=["fire", "fire_all", "resolve_effects", "resolve_delayed", "enforce_state_based_actions"],
)
def test_driving_a_cascade_mid_decision_raises_naming_driver_and_request(driver, drive):
    game = two_seat_game()
    game.pending = ChooseDiscard(
        PlayerId.P1, ("c1",), count=1, holder=PlayerId.P1, cause=Rulebook.MAXIMUM_HAND_SIZE
    )

    with pytest.raises(RuntimeError, match=f"{driver} drove a cascade while ChooseDiscard"):
        drive(game)


def test_resuming_a_choice_without_its_stash_on_top_raises():
    game = two_seat_game()
    game.stack.append(ApplyEffects(()))

    with pytest.raises(RuntimeError, match="without its stashed cascade"):
        resume_paused_cascade(game, [])


def test_each_paused_frame_resumes_under_its_own_provenance():
    game = two_seat_game()
    put_in_play(game, personality("paid"))
    put_in_play(game, personality("struck"))
    game.ongoing.append(Negation("ward", END_OF_TURN, effect_kind=Bow))
    paying = EffectsFrame((Bow("paid"),), Provenance(paying=True))
    triggered = EffectsFrame((Bow("struck"),), Provenance(triggered=True))
    game.stack.append(ResumeCascade((EventsFrame(()), paying, triggered)))

    resume_paused_cascade(game, [])

    # A cost's payment is no effect, so the negation passes it by; the trigger's bowing is negated.
    assert game.table.cards_by_id["paid"].bowed
    assert not game.table.cards_by_id["struck"].bowed


def test_a_resumed_cascade_drops_the_triggers_of_cards_gone_from_the_table(reacting):
    game = two_seat_game()
    put_in_play(game, personality("stayed", printed_id="resume_probe"))
    reacted = []

    def record(ctx):
        reacted.append(ctx.card.id)
        return []

    reacting(TurnBoundary, "resume_probe", record, boundary=Boundary.BEGINNING)
    boundary = TurnBoundary(PlayerId.P1, Boundary.BEGINNING)
    events = EventsFrame((), (("gone", record, boundary), ("stayed", record, boundary)))
    game.stack.append(ResumeCascade((events, EffectsFrame(()))))

    resume_paused_cascade(game, [])

    assert reacted == ["stayed"]


def test_resuming_a_stash_with_no_effects_frame_on_top_raises():
    game = two_seat_game()
    game.stack.append(ResumeCascade((EventsFrame(()),)))

    with pytest.raises(RuntimeError, match="no effects frame on top"):
        resume_paused_cascade(game, [])


def test_resuming_a_stash_with_no_events_frame_at_the_bottom_raises():
    game = two_seat_game()
    game.stack.append(ResumeCascade((EffectsFrame((GainHonor(PlayerId.P1, 1),)),)))

    with pytest.raises(RuntimeError, match="resumed with no events frame at the bottom"):
        resume_paused_cascade(game, [])


def test_a_negation_reaches_one_member_of_a_group_as_it_would_alone():
    game = two_seat_game()
    put_in_play(game, personality("struck"))
    put_in_play(game, personality("spared"))
    game.ongoing.append(Negation("ward", END_OF_TURN, effect_kind=Bow, subject_id="spared"))

    resolve_effects(game, [Simultaneously((Bow("struck"), Bow("spared")))])

    assert game.table.cards_by_id["struck"].bowed
    assert not game.table.cards_by_id["spared"].bowed


def test_an_interrupt_answers_a_member_of_an_actions_group():
    game = two_seat_game()
    hero = put_in_play(game, personality("hero"))
    put_in_play(game, personality("bystander"))
    destroy = Destroy(hero.id, PlayerId.P1)
    game.modifications.append(
        Replacement(bound=destroy, card_id="ward", replacement=Negated(destroy))
    )
    game.interrupts_offered = True

    resolve_action_effects(game, [Simultaneously((destroy, Bow("bystander")))])

    assert hero in game.table.battlefield.cards
    assert game.table.cards_by_id["bystander"].bowed
    assert game.modifications == []


def test_the_interrupt_step_foresees_each_member_of_a_group():
    game = two_seat_game()
    put_in_play(game, personality("a"))
    put_in_play(game, personality("b"))

    foreseen = forecast(game, (Simultaneously((Bow("a"), Bow("b"))),))

    assert foreseen == (Bow("a"), Bow("b"))


def test_a_question_inside_a_group_resumes_the_rest_of_the_group():
    game = two_seat_game()
    put_in_play(game, personality("asker"))
    put_in_play(game, personality("other"))
    asking = Choose(PlayerId.P1, (), 0, 0, "test_sandwich", "asker")

    resolve_effects(game, [Simultaneously((asking, Bow("other")))])
    assert not game.table.cards_by_id["other"].bowed

    action_sequence.submit(game, DecisionResponse(()))

    assert game.table.cards_by_id["asker"].counters == {"wealth": 1}
    assert game.table.cards_by_id["other"].bowed


def test_a_groups_members_all_happen_before_anything_reacts_to_one(reacting):
    # CR, Timing Conflicts: "two Personalities being destroyed in battle resolution" happen at the
    # same time, so neither's destruction is reacted to while the other is still in play.
    game = two_seat_game()
    put_in_play(game, personality("probe", printed_id="destroyed_probe"))
    first = put_in_play(game, personality("first"))
    second = put_in_play(game, personality("second"))
    still_in_play: list[bool] = []

    def _record_the_pair(ctx):
        battlefield = ctx.game.table.battlefield.cards
        still_in_play.append(first in battlefield or second in battlefield)
        return []

    reacting(Destroyed, "destroyed_probe", _record_the_pair)

    resolve_effects(
        game, [Simultaneously((Destroy(first.id, PlayerId.P2), Destroy(second.id, PlayerId.P2)))]
    )

    assert still_in_play == [False, False]


def test_a_reaction_to_an_answer_inside_a_group_waits_for_the_rest_of_the_group(reacting):
    game = two_seat_game()
    put_in_play(game, personality("asker", printed_id="counter_probe"))
    put_in_play(game, personality("other"))
    other_bowed: list[bool] = []

    def _record_other(ctx):
        other_bowed.append(ctx.game.table.cards_by_id["other"].bowed)
        return []

    reacting(CounterChanged, "counter_probe", _record_other)
    asking = Choose(PlayerId.P1, (), 0, 0, "test_sandwich", "asker")

    resolve_effects(game, [Simultaneously((asking, Bow("other")))])
    action_sequence.submit(game, DecisionResponse(()))

    assert other_bowed == [True]


def test_what_depends_on_an_effect_applies_after_the_reactions_to_it(reacting):
    game = two_seat_game()
    put_in_play(game, personality("probe", printed_id="bow_probe"))
    samurai = put_in_play(game, personality("samurai"))
    honor_when_bowed: list[int] = []

    def _record_honor(ctx):
        honor_when_bowed.append(ctx.game.table.seats[PlayerId.P1].honor)
        return []

    reacting(Bowed, "bow_probe", _record_honor)

    resolve_effects(game, [To(Bow(samurai.id), (GainHonor(PlayerId.P1, 2),))])

    assert honor_when_bowed == [0]
    assert game.table.seats[PlayerId.P1].honor == 2


def test_what_depends_on_a_banish_applies_though_nothing_reacts_to_it():
    game = two_seat_game()
    card = register(game.table, _fate("held", printed_id="held"))
    game.table.zones[ZoneKey(PlayerId.P1, ZoneRole.HAND)].add(card)

    resolve_effects(game, [To(Banish(card.id), (GainHonor(PlayerId.P1, 2),))])

    assert game.table.seats[PlayerId.P1].honor == 2


def test_discarding_a_card_already_in_the_discard_pile_is_nothing_to_depend_on():
    game = two_seat_game()
    card = register(game.table, _fate("gone", printed_id="gone"))
    game.table.zones[ZoneKey(PlayerId.P1, ZoneRole.FATE_DISCARD)].add(card)

    resolve_effects(game, [To(Discard(card.id, PlayerId.P1), (GainHonor(PlayerId.P1, 2),))])

    assert game.table.seats[PlayerId.P1].honor == 0


def test_an_effect_an_interrupt_substituted_did_not_happen():
    # CR, Independence of Effects: no draw "if something prevented him from bowing".
    game = two_seat_game()
    samurai = put_in_play(game, personality("samurai"))
    other = put_in_play(game, personality("other"))
    game.modifications.append(
        Replacement(bound=Bow(samurai.id), card_id="ward", replacement=Bow(other.id))
    )
    game.interrupts_offered = True

    resolve_action_effects(game, [To(Bow(samurai.id), (GainHonor(PlayerId.P1, 2),))])

    assert other.bowed
    assert game.table.seats[PlayerId.P1].honor == 0


def test_an_effect_an_interrupt_adjusted_still_happened():
    game = two_seat_game()
    gain = GainHonor(PlayerId.P1, 1)
    game.modifications.append(Adjustment(gain, 1))
    game.interrupts_offered = True

    resolve_action_effects(game, [To(gain, (GainHonor(PlayerId.P1, 2),))])

    assert game.table.seats[PlayerId.P1].honor == 4


def test_the_interrupt_step_does_not_foresee_what_depends_on_a_negated_effect():
    game = two_seat_game()
    samurai = put_in_play(game, personality("samurai"))
    game.ongoing.append(Negation("ring", END_OF_TURN, effect_kind=Bow))

    assert forecast(game, (To(Bow(samurai.id), (GainHonor(PlayerId.P1, 2),)),)) == ()


def test_the_interrupt_step_does_not_foresee_what_depends_on_a_substituted_effect():
    game = two_seat_game()
    samurai = put_in_play(game, personality("samurai"))
    other = put_in_play(game, personality("other"))
    game.modifications.append(
        Replacement(bound=Bow(samurai.id), card_id="ward", replacement=Bow(other.id))
    )

    foreseen = forecast(game, (To(Bow(samurai.id), (GainHonor(PlayerId.P1, 2),)),))

    assert foreseen == (Bow(samurai.id),)


def test_a_question_cannot_be_what_another_effect_depends_on():
    asking = Choose(PlayerId.P1, (), 0, 0, "test_sandwich", "asker")

    with pytest.raises(TypeError, match="cannot be what another effect depends on"):
        To(asking, (Bow("other"),))


def test_what_depends_on_an_effect_that_did_not_happen_does_not_apply():
    # CR, Independence of Effects: "Bow your Samurai to draw two cards" means the player doesn't draw
    # the cards if the Samurai was already bowed at the time.
    game = two_seat_game()
    samurai = put_in_play(game, personality("samurai"))
    samurai.bow()

    resolve_effects(game, [To(Bow(samurai.id), (GainHonor(PlayerId.P1, 2),))])

    assert game.table.seats[PlayerId.P1].honor == 0


def test_a_group_inside_a_group_is_one_occurrence_with_it(reacting):
    game = two_seat_game()
    put_in_play(game, personality("probe", printed_id="bowed_probe"))
    for card_id in ("a", "b", "c"):
        put_in_play(game, personality(card_id))
    all_bowed: list[bool] = []

    def _record_all_bowed(ctx):
        all_bowed.append(all(ctx.game.table.cards_by_id[card_id].bowed for card_id in "abc"))
        return []

    reacting(Bowed, "bowed_probe", _record_all_bowed)

    resolve_effects(game, [Simultaneously((Simultaneously((Bow("a"), Bow("b"))), Bow("c")))])

    assert all_bowed == [True, True, True]


def test_discarding_a_card_already_in_the_discard_pile_announces_nothing(reacting):
    game = two_seat_game()
    card = register(game.table, _fate("gone", printed_id="gone"))
    game.table.zones[ZoneKey(PlayerId.P1, ZoneRole.FATE_DISCARD)].add(card)
    told: list[str] = []

    def _record_discard(ctx):
        told.append(ctx.event.card_id)
        return []

    reacting(CardDiscarded, "gone", _record_discard)

    resolve_effects(game, [Discard(card.id, PlayerId.P1)])

    assert told == []


def test_the_active_player_orders_the_opponents_trigger_and_the_opponent_answers_it(reacting):
    # CR, Timing Conflicts: "the active player decides the order", and CR, Choices: "In traits, the
    # choice belongs to the player whose card it is".
    game = two_seat_game()
    mine = put_in_play(game, personality("P1-asker", printed_id="asking_probe"))
    theirs = put_in_play(
        game, personality("P2-asker", printed_id="asking_probe", owner=PlayerId.P2)
    )

    def _ask_own_controller(ctx):
        return [Choose(ctx.card.owner, (), 0, 0, "test_sandwich", ctx.card.id)]

    reacting(Bowed, "asking_probe", _ask_own_controller)

    resolve_effects(game, [Simultaneously((Bow(mine.id), Bow(theirs.id)))])
    order = game.pending
    action_sequence.submit(game, DecisionResponse((theirs.id,)))

    assert isinstance(order, ChooseNextTrigger) and order.seat is PlayerId.P1
    assert set(order.candidates) == {mine.id, theirs.id}
    assert isinstance(game.pending, ChooseCards) and game.pending.seat is PlayerId.P2


def test_a_trigger_that_would_do_nothing_is_not_offered_to_order():
    game = two_seat_game()
    first = _rice_farm(game, card_id="P1-farm-a")
    second = _rice_farm(game, card_id="P1-farm-b")
    _rice_farm(game, seat=PlayerId.P2, card_id="P2-farm")

    fire(game, TurnBoundary(PlayerId.P1, Boundary.BEGINNING))

    assert isinstance(game.pending, ChooseNextTrigger)
    assert game.pending.candidates == (first.id, second.id)


def test_one_trigger_that_does_something_among_ones_that_do_not_is_not_asked_about():
    game = two_seat_game()
    farm = _rice_farm(game, card_id="P1-farm")
    _rice_farm(game, seat=PlayerId.P2, card_id="P2-farm")

    fire(game, TurnBoundary(PlayerId.P1, Boundary.BEGINNING))

    assert game.pending is None
    assert farm.counters == {"wealth": 1}


def _gain_one_honor(ctx):
    return [GainHonor(PlayerId.P1, 1)]


def test_a_card_in_a_hand_is_no_candidate_and_its_trigger_resolves_after_the_others(reacting):
    game = two_seat_game()
    mine = put_in_play(game, holding("P1-farm", printed_id="public_probe"))
    held = register(
        game.table,
        L5RCard.of(
            FatePrint,
            id="P2-held",
            name="F",
            printed_id="hand_probe",
            side=Side.FATE,
            owner=PlayerId.P2,
        ),
    )
    game.table.zones[ZoneKey(PlayerId.P2, ZoneRole.HAND)].add(held)

    def _ask_the_holder(ctx):
        return [Choose(PlayerId.P2, (), 0, 0, "test_sandwich", ctx.card.id)]

    reacting(EnteredPlay, "public_probe", lambda ctx: [AdjustCounter(ctx.card.id, WEALTH, 1)])
    reacting(EnteredPlay, "hand_probe", _ask_the_holder, where=(CardLocation.HAND,))

    fire(game, EnteredPlay("someone"))

    assert mine.counters == {"wealth": 1}
    assert isinstance(game.pending, ChooseCards) and game.pending.seat is PlayerId.P2


def test_a_trait_whose_condition_the_occurrence_did_not_meet_is_not_triggered_later(reacting):
    game = two_seat_game()
    enabler = put_in_play(game, holding("P1-a", printed_id="enabling_probe"))
    put_in_play(game, holding("P1-b", printed_id="waiting_probe"))

    def _gain_once_enabled(ctx):
        return [GainHonor(PlayerId.P1, 1)] if enabler.counters else []

    reacting(EnteredPlay, "enabling_probe", lambda ctx: [AdjustCounter(enabler.id, WEALTH, 1)])
    reacting(EnteredPlay, "waiting_probe", _gain_once_enabled)

    fire(game, EnteredPlay("someone"))

    assert enabler.counters == {"wealth": 1}
    assert game.table.seats[PlayerId.P1].honor == 0


def test_what_the_rules_demand_after_an_effect_is_the_next_occurrence(reacting):
    game = two_seat_game()
    doomed = put_in_play(game, personality("doomed", chi=1))
    put_in_play(game, holding("P1-counted", printed_id="counter_probe"))
    put_in_play(game, holding("P1-mourner", printed_id="death_probe"))
    reacting(CounterChanged, "counter_probe", _gain_one_honor)
    reacting(Destroyed, "death_probe", _gain_one_honor)

    resolve_effects(game, [AdjustCounter(doomed.id, counter_from_key("blood"), 1)])

    assert doomed not in game.table.battlefield.cards
    assert game.pending is None
    assert game.table.seats[PlayerId.P1].honor == 2


def test_what_the_rules_demand_after_a_group_follows_the_groups_own_occurrence(reacting):
    game = two_seat_game()
    doomed = put_in_play(game, personality("doomed", chi=1))
    other = put_in_play(game, personality("other"))
    put_in_play(game, holding("P1-counted", printed_id="counter_probe"))
    put_in_play(game, holding("P1-mourner", printed_id="death_probe"))
    reacting(CounterChanged, "counter_probe", _gain_one_honor)
    reacting(Destroyed, "death_probe", _gain_one_honor)
    blood = AdjustCounter(doomed.id, counter_from_key("blood"), 1)

    resolve_effects(game, [Simultaneously((blood, Bow(other.id)))])

    assert doomed not in game.table.battlefield.cards and other.bowed
    assert game.pending is None
    assert game.table.seats[PlayerId.P1].honor == 2


def test_a_moment_is_announced_after_what_its_lapse_left_has_been_reacted_to(reacting):
    game = two_seat_game()
    doomed = put_in_play(game, personality("doomed", chi=0))
    game.ongoing.append(Modifier("src", doomed.id, Stat.CHI, 1, Duration.UNTIL_END_OF_TURN))
    put_in_play(game, holding("P1-mourner", printed_id="death_probe"))
    put_in_play(game, holding("P1-ender", printed_id="end_probe"))
    reacting(Destroyed, "death_probe", _gain_one_honor)
    reacting(TurnBoundary, "end_probe", _gain_one_honor, boundary=Boundary.END)

    reach_moment(game, END_OF_TURN, TurnBoundary(PlayerId.P1, Boundary.END))

    assert doomed not in game.table.battlefield.cards
    assert game.pending is None
    assert game.table.seats[PlayerId.P1].honor == 2


def test_a_conflict_inside_a_chosen_trigger_is_ordered_before_the_outer_one_finishes(reacting):
    game = two_seat_game()
    first = put_in_play(game, holding("P1-a", printed_id="entry_probe"))
    put_in_play(game, holding("P1-b", printed_id="entry_probe"))
    put_in_play(game, holding("P1-c", printed_id="counter_watch"))
    put_in_play(game, holding("P1-d", printed_id="counter_watch"))

    def _watch_the_first(ctx):
        return [GainHonor(PlayerId.P1, 1)] if ctx.event.card_id == first.id else []

    reacting(EnteredPlay, "entry_probe", lambda ctx: [AdjustCounter(ctx.card.id, WEALTH, 1)])
    reacting(CounterChanged, "counter_watch", _watch_the_first)

    fire(game, EnteredPlay("someone"))
    outer = game.pending
    action_sequence.submit(game, DecisionResponse((first.id,)))
    inner = game.pending
    action_sequence.submit(game, DecisionResponse(("P1-d",)))

    assert isinstance(outer, ChooseNextTrigger) and outer.candidates == ("P1-a", "P1-b")
    assert isinstance(inner, ChooseNextTrigger) and inner.candidates == ("P1-c", "P1-d")
    assert game.pending is None and not game.stack
    assert game.table.seats[PlayerId.P1].honor == 2
    assert game.table.cards_by_id["P1-b"].counters == {"wealth": 1}


def test_the_active_player_is_asked_again_between_one_cards_two_triggers(reacting):
    game = two_seat_game()
    twice = put_in_play(game, holding("P1-a", printed_id="twice_probe"))
    once = put_in_play(game, holding("P1-b", printed_id="once_probe"))
    reacting(EnteredPlay, "twice_probe", lambda ctx: [AdjustCounter(ctx.card.id, WEALTH, 1)])
    reacting(EnteredPlay, "twice_probe", _gain_one_honor)
    reacting(EnteredPlay, "once_probe", lambda ctx: [AdjustCounter(ctx.card.id, WEALTH, 1)])

    fire(game, EnteredPlay("someone"))
    action_sequence.submit(game, DecisionResponse((twice.id,)))

    assert isinstance(game.pending, ChooseNextTrigger)
    assert game.pending.candidates == (twice.id, once.id)


def test_a_rulebook_effect_resolves_with_the_card_its_event_names(reacting):
    # The rulebook's Honor loss for a dishonorable death is that Personality's candidate, after
    # his own trait, so nobody is asked to order the two.
    game = two_seat_game()
    doomed = put_in_play(game, personality("doomed", printed_id="dying_probe", personal_honor=2))
    doomed.dishonor()

    def _gain_for_his_own_death(ctx):
        return [GainHonor(PlayerId.P2, 1)] if ctx.event.card_id == ctx.card.id else []

    reacting(Destroyed, "dying_probe", _gain_for_his_own_death)

    resolve_effects(game, [Destroy(doomed.id, PlayerId.P2)])

    assert game.pending is None
    assert game.table.seats[PlayerId.P1].honor == -2
    assert game.table.seats[PlayerId.P2].honor == 1


def test_a_trigger_whose_card_an_earlier_one_destroyed_does_not_resolve(reacting):
    game = two_seat_game()
    killer = put_in_play(game, personality("P1-killer", printed_id="killing_probe"))
    victim = put_in_play(game, personality("P1-victim", printed_id="victim_probe"))
    reacting(EnteredPlay, "killing_probe", lambda ctx: [Destroy(victim.id, PlayerId.P1)])
    reacting(EnteredPlay, "victim_probe", _gain_one_honor)

    fire(game, EnteredPlay("someone"))
    action_sequence.submit(game, DecisionResponse((killer.id,)))

    assert victim not in game.table.battlefield.cards
    assert game.table.seats[PlayerId.P1].honor == 0
    assert game.pending is None


def test_resolving_an_actions_own_effects_outside_the_interrupt_step_raises():
    with pytest.raises(ValueError, match="resolve_action_effects"):
        resolve_effects(two_seat_game(), [], provenance=Provenance(interruptible=True))


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

    fire(game, TurnBoundary(PlayerId.P1, Boundary.BEGINNING))

    assert farm.counters == {"wealth": 1}


def test_the_end_of_the_turn_gives_the_rice_farm_nothing():
    game = two_seat_game()
    farm = _rice_farm(game)

    fire(game, TurnBoundary(PlayerId.P1, Boundary.END))

    assert farm.counters == {}


def test_the_same_card_awaiting_recruitment_in_a_province_does_not_react():
    # Triggers key on printed_id, so the unbought copy in a Province is indistinguishable from the
    # one in play except by where collection looks. Rice Farm's guard reads the seat and the
    # cap, never whether it is in play. Scanning past the battlefield would accrue Gold Production
    # on a card nobody paid for; a trigger would first have to declare where it functions.
    game = two_seat_game()
    in_play = _rice_farm(game, card_id="P1-farm")
    unbought = province_card(game, "P1-unbought", seat=PlayerId.P1, printed_id="rice_farm")

    fire(game, TurnBoundary(PlayerId.P1, Boundary.BEGINNING))

    assert in_play.counters == {"wealth": 1}
    assert unbought.counters == {}


def test_wealth_accrues_each_turn_up_to_the_cap_of_four():
    game = two_seat_game()
    farm = _rice_farm(game)

    for _ in range(6):
        fire(game, TurnBoundary(PlayerId.P1, Boundary.BEGINNING))

    assert farm.counters == {"wealth": 4}  # "will not have more than four Wealth tokens"


def test_one_event_fans_out_to_every_subscribed_card():
    game = two_seat_game()
    first = _rice_farm(game, card_id="P1-farm-a")
    second = _rice_farm(game, card_id="P1-farm-b")

    fire(game, TurnBoundary(PlayerId.P1, Boundary.BEGINNING))
    action_sequence.submit(game, DecisionResponse((first.id,)))

    assert first.counters == {"wealth": 1} and second.counters == {"wealth": 1}


def test_the_token_only_lands_on_the_turn_players_own_farm():
    game = two_seat_game()
    farm = _rice_farm(game)  # owned by P1

    fire(
        game, TurnBoundary(PlayerId.P2, Boundary.BEGINNING)
    )  # "after your turn begins": not P1's turn

    assert farm.counters == {}


def test_accrued_wealth_raises_the_farms_effective_gold_production():
    game = two_seat_game()
    farm = _rice_farm(game)
    assert effective_gold_production(game, farm) == 0

    fire(game, TurnBoundary(PlayerId.P1, Boundary.BEGINNING))
    fire(game, TurnBoundary(PlayerId.P1, Boundary.BEGINNING))

    assert effective_gold_production(game, farm) == 2  # printed 0 + two Wealth tokens


def test_flow_emits_the_turn_start_event_from_begin_turn():
    # The wiring test: begin_game runs _begin_turn, which must announce the turn's beginning.
    game = two_seat_game()
    farm = _rice_farm(game)

    sequence.begin_game(game)

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
    # The wiring test: the maximum hand size's discard moves a hand card to the discard and must
    # fire CardDiscarded.
    game = two_seat_game()
    probe = holding("P1-probe", printed_id="test_discard_probe", owner=PlayerId.P1)
    put_in_play(game, probe)
    fate = fate_card("P1-f", PlayerId.P1)
    game.table.cards_by_id[fate.id] = fate
    game.table.zones[ZoneKey(PlayerId.P1, ZoneRole.HAND)].add(fate)

    resolve_effects(
        game,
        [
            DiscardFromHand(
                PlayerId.P1, 1, Rulebook.MAXIMUM_HAND_SIZE, PlayerId.P1, candidates=("P1-f",)
            )
        ],
    )

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
    # The cascade: turn start -> Rice Farm gains wealth -> CounterChanged -> Aoki draws a card.
    game = two_seat_game()
    _rice_farm(game)
    _aoki(game)
    _seed_fate_deck(game, PlayerId.P1, 3)
    assert _hand_size(game, PlayerId.P1) == 0

    fire(game, TurnBoundary(PlayerId.P1, Boundary.BEGINNING))

    assert _hand_size(game, PlayerId.P1) == 1


def test_aoki_draws_at_most_once_per_turn():
    game = two_seat_game()
    _rice_farm(game, card_id="P1-farm-a")
    _rice_farm(game, card_id="P1-farm-b")  # two wealth gains in one turn
    _aoki(game)
    _seed_fate_deck(game, PlayerId.P1, 3)

    fire(game, TurnBoundary(PlayerId.P1, Boundary.BEGINNING))
    action_sequence.submit(game, DecisionResponse(("P1-farm-a",)))

    assert _hand_size(game, PlayerId.P1) == 1  # two CounterChanged events, one draw


def test_aoki_draws_again_on_the_next_turn():
    # The once-per-turn claim is turn-scoped: a fresh turn re-arms Aoki's draw.
    game = two_seat_game()
    _rice_farm(game)
    _aoki(game)
    _seed_fate_deck(game, PlayerId.P1, 3)

    fire(game, TurnBoundary(PlayerId.P1, Boundary.BEGINNING))
    game.turn += 1
    fire(game, TurnBoundary(PlayerId.P1, Boundary.BEGINNING))

    assert _hand_size(game, PlayerId.P1) == 2


def test_aoki_ignores_wealth_gained_on_an_opponents_holding():
    game = two_seat_game()
    _aoki(game, seat=PlayerId.P1)
    _rice_farm(game, seat=PlayerId.P2, card_id="P2-farm")
    _seed_fate_deck(game, PlayerId.P1, 3)

    fire(
        game, TurnBoundary(PlayerId.P2, Boundary.BEGINNING)
    )  # P2's farm gains wealth: not Aoki's Holding

    assert _hand_size(game, PlayerId.P1) == 0


def test_aoki_ignores_wealth_removed_from_your_holding():
    game = two_seat_game()
    farm = _rice_farm(game)
    farm.adjust_counter(WEALTH.key, 2)
    _aoki(game)
    _seed_fate_deck(game, PlayerId.P1, 3)

    resolve_effects(game, [AdjustCounter(farm.id, WEALTH, -1)])

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

    assert events == [
        Destroyed(farm.id, PlayerId.P1, Location.home(PlayerId.P1), controller=PlayerId.P1)
    ]
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

    assert rural.counters == {}  # "after THIS Holding enters play": only its own entry


def test_flow_emits_entered_play_from_recruit_resolution():
    # The wiring test: a card's Recruit brings the card in, and entering must fire EnteredPlay.
    game = two_seat_game()
    rural = holding(
        "P1-rural",
        printed_id="rural_market",
        name="Rural Market",
        owner=PlayerId.P1,
        gold_production=0,
    )
    game.table.cards_by_id[rural.id] = rural  # being recruited, not yet on the battlefield

    resolve_effects(game, recruit.recruit_card(game, rural))
    sequence.run_stack(game)

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

    assert game.pending is None  # no eligible target, no choice raised


def test_wheat_farm_grants_a_token_to_each_chosen_farm():
    game = two_seat_game()
    wheat = _wheat_farm(game)
    first = _keyworded_farm(game, card_id="P1-farm-a")
    second = _keyworded_farm(game, card_id="P1-farm-b")

    fire(game, EnteredPlay(wheat.id))
    action_sequence.submit(game, DecisionResponse((first.id, second.id)))

    assert first.counters == {"wealth": 1} and second.counters == {"wealth": 1}
    assert wheat.counters == {}
    assert game.pending is None


def test_wheat_farm_choice_is_optional():
    game = two_seat_game()
    wheat = _wheat_farm(game)
    other = _keyworded_farm(game, card_id="P1-other-farm")

    fire(game, EnteredPlay(wheat.id))
    action_sequence.submit(game, DecisionResponse(()))  # decline: give none

    assert other.counters == {}
    assert game.pending is None


def test_wheat_farm_token_cascades_into_aokis_draw():
    game = two_seat_game()
    wheat = _wheat_farm(game)
    other = _keyworded_farm(game, card_id="P1-other-farm")
    _aoki(game)
    _seed_fate_deck(game, PlayerId.P1, 3)

    fire(game, EnteredPlay(wheat.id))
    action_sequence.submit(game, DecisionResponse((other.id,)))

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
    assert pending.maximum == 2  # "zero to two": capped however many Farms you control


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
    # The probe also fires on the Wheat Farm's entry, so the Wheat Farm's pausing choice stashes the
    # probe's trigger, and resuming must run it and land its Wealth token, not merely drain the stack.
    game = two_seat_game()
    wheat = _wheat_farm(game, card_id="P1-a-wheat")
    other = _keyworded_farm(game, card_id="P1-other-farm")
    probe = _probe(game)

    fire(game, EnteredPlay(wheat.id))
    action_sequence.submit(game, DecisionResponse((wheat.id,)))
    assert isinstance(game.pending, ChooseCards)
    action_sequence.submit(game, DecisionResponse((other.id,)))

    assert other.counters == {"wealth": 1}  # the choice resolved
    assert probe.counters == {"wealth": 1}  # the stashed trigger resumed and applied its effect
    assert game.stack == []


def test_a_trigger_that_asks_stashes_the_event_and_the_triggers_left_to_fire():
    game = two_seat_game()
    wheat = _wheat_farm(game, card_id="P1-a-wheat")
    _keyworded_farm(game, card_id="P1-other-farm")
    probe = _probe(game)

    fire(game, EnteredPlay(wheat.id))
    action_sequence.submit(game, DecisionResponse((wheat.id,)))

    stash = game.stack[-1]
    assert isinstance(stash, ResumeCascade)
    events, effects = stash.frames
    assert isinstance(events, EventsFrame) and isinstance(effects, EffectsFrame)
    assert events.queue == ()
    assert [(card_id, event) for card_id, _, event in events.firing] == [
        (probe.id, EnteredPlay(wheat.id))
    ]
    assert effects.provenance == Provenance(triggered=True)


def test_a_triggers_question_is_marked_as_the_triggers_own():
    game = two_seat_game()
    wheat = _wheat_farm(game)
    _keyworded_farm(game, card_id="P1-other-farm")

    fire(game, EnteredPlay(wheat.id))

    assert game.pending.triggered


def test_a_question_raised_outside_a_trigger_is_not_marked():
    game = two_seat_game()
    resolve_effects(game, [Choose(PlayerId.P1, (), 0, 0, "test_sandwich", None)])

    assert not game.pending.triggered


def test_a_question_asked_in_a_producers_window_is_not_marked(reacting):
    # ProducingGold opens a window before the bow: the payment step's own question, not a reaction.
    game = two_seat_game()
    producer = holding("P1-mine", printed_id="window_probe")
    put_in_play(game, producer)
    reacting(
        ProducingGold,
        "window_probe",
        lambda ctx: [Choose(ctx.card.owner, (), 0, 0, "test_sandwich", ctx.card.id)],
    )

    fire(game, ProducingGold(producer.id, PlayerId.P1))

    assert isinstance(game.pending, ChooseCards) and not game.pending.triggered


@pytest.mark.parametrize("boundary, marked", [(Boundary.BEGINNING, False), (Boundary.END, True)])
def test_only_the_opening_edge_of_a_duels_declaration_is_a_window(reacting, boundary, marked):
    # One event names both edges of the declaration, so what makes a question the step's own is the
    # boundary rather than the event type: at the opening edge the duel has not committed yet.
    game = two_seat_game()
    duelist = personality("P1-duelist", printed_id="duel_window_probe")
    put_in_play(game, duelist)
    reacting(
        DuelDeclared,
        "duel_window_probe",
        lambda ctx: [Choose(ctx.card.owner, (), 0, 0, "test_sandwich", ctx.card.id)],
        boundary=boundary,
    )

    fire(
        game,
        DuelDeclared(
            boundary=boundary,
            challenger=PlayerId.P1,
            challenged=PlayerId.P2,
            challenger_duelist="P1-duelist",
            challenged_duelist="P2-rival",
            source_card_id="P1-duelist",
            challenger_stat=2,
            challenged_stat=2,
        ),
    )

    assert isinstance(game.pending, ChooseCards) and game.pending.triggered is marked


# A test-only trigger asking twice, so the second question is raised from the stash the first
# left, not from the trigger's own effects.
@on(EnteredPlay, "test_two_questions")
def _two_questions(ctx):
    return [
        Choose(ctx.card.owner, (), 0, 0, "test_sandwich", ctx.card.id),
        Choose(ctx.card.owner, (), 0, 0, "test_sandwich", ctx.card.id),
    ]


def test_the_mark_follows_a_triggers_effects_through_the_stash():
    game = two_seat_game()
    asker = holding("P1-asker", printed_id="test_two_questions", name="Asker", owner=PlayerId.P1)
    put_in_play(game, asker)

    fire(game, EnteredPlay(asker.id))
    action_sequence.submit(game, DecisionResponse(()))

    assert isinstance(game.pending, ChooseCards) and game.pending.triggered


def test_effects_after_a_choice_in_the_same_trigger_still_resolve():
    game = two_seat_game()
    sandwich = holding(
        "P1-sandwich", printed_id="test_sandwich", name="Sandwich", owner=PlayerId.P1
    )
    put_in_play(game, sandwich)

    fire(game, EnteredPlay(sandwich.id))
    assert isinstance(game.pending, ChooseCards)
    action_sequence.submit(game, DecisionResponse(()))

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
        PersonalityPrint,
        id="doomed",
        printed_id="doomed",
        name="doomed",
        side=Side.DYNASTY,
        owner=PlayerId.P1,
        chi=0,
    )
    put_in_play(game, doomed)

    enforce_state_based_actions(game)

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
    does not, so a Personality a state-based action killed on sight cannot go on to take his
    enter-play trait, which is what settling those rules before announcing the arrival is for."""
    game = two_seat_game()
    doomed = put_in_play(game, holding("P1-doomed", printed_id="departure_probe"))
    seen: list[str] = []
    reacting(EnteredPlay, "departure_probe", lambda ctx: seen.append(ctx.event.card_id) or [])
    resolve_effects(game, [Destroy(doomed.id, PlayerId.P1)])

    fire(game, EnteredPlay(doomed.id))

    assert seen == []


def test_a_card_reacts_to_an_honor_gain(reacting):
    game = two_seat_game()
    put_in_play(game, holding("P1-watcher", printed_id="honor_probe"))
    seen: list[HonorChanged] = []
    reacting(HonorChanged, "honor_probe", lambda ctx: seen.append(ctx.event) or [])

    resolve_effects(game, [GainHonor(PlayerId.P2, 3), GainHonor(PlayerId.P1, -1)])

    assert seen == [HonorChanged(PlayerId.P2, 3), HonorChanged(PlayerId.P1, -1)]


@pytest.mark.parametrize("kind", [RoundKind.INTERRUPT, RoundKind.RESPONSE])
def test_an_event_inside_an_interrupt_or_response_round_is_not_the_actions(kind):
    game = two_seat_game()
    game.round = ActionRound(timings=game.round.timings, priority=PlayerId.P1, kind=kind)

    resolve_effects(game, [GainHonor(PlayerId.P1, 1)])

    assert game.table.seats[PlayerId.P1].honor == 1
    assert game.action_events == []


@choice_resolver("hand_probe_answer")
def _resolve_hand_probe_answer(game, source_id, chosen, seat):
    return []


def _held(game, card_id: str, owner: PlayerId = PlayerId.P1) -> L5RCard:
    card = L5RCard.of(
        FatePrint, id=card_id, name="Probe", printed_id="hand_probe", side=Side.FATE, owner=owner
    )
    game.table.zones[ZoneKey(owner, ZoneRole.HAND)].add(register(game.table, card))
    return card


def test_a_trigger_registered_for_the_hand_fires_for_a_card_in_hand(reacting):
    game = two_seat_game()
    _held(game, "held")
    put_in_play(game, holding("played", printed_id="hand_probe"))
    seen: list[str] = []
    reacting(
        TurnBoundary,
        "hand_probe",
        lambda ctx: seen.append(ctx.card.id) or [],
        where=(CardLocation.HAND,),
        boundary=Boundary.BEGINNING,
    )

    fire(game, TurnBoundary(PlayerId.P1, Boundary.BEGINNING))

    assert seen == ["held"]


def test_a_registration_for_both_zones_fires_in_each(reacting):
    game = two_seat_game()
    _held(game, "held")
    put_in_play(game, holding("played", printed_id="hand_probe"))
    seen: list[str] = []
    reacting(
        TurnBoundary,
        "hand_probe",
        lambda ctx: seen.append(ctx.card.id) or [],
        where=(CardLocation.BATTLEFIELD, CardLocation.HAND),
        boundary=Boundary.BEGINNING,
    )

    fire(game, TurnBoundary(PlayerId.P1, Boundary.BEGINNING))

    assert sorted(seen) == ["held", "played"]


def test_a_battlefield_registration_does_not_hear_from_hand(reacting):
    game = two_seat_game()
    _held(game, "held")
    seen: list[str] = []
    reacting(
        TurnBoundary,
        "hand_probe",
        lambda ctx: seen.append(ctx.card.id) or [],
        boundary=Boundary.BEGINNING,
    )

    fire(game, TurnBoundary(PlayerId.P1, Boundary.BEGINNING))

    assert seen == []


def test_a_hand_triggers_question_reaches_only_the_cards_owner(reacting):
    game = two_seat_game()
    _held(game, "held")
    reacting(
        TurnBoundary,
        "hand_probe",
        lambda ctx: [
            Ask(ctx.card.owner, "Put it into play?", "hand_probe_answer", source_id=ctx.card.id)
        ],
        where=(CardLocation.HAND,),
        boundary=Boundary.BEGINNING,
    )

    fire(game, TurnBoundary(PlayerId.P1, Boundary.BEGINNING))

    assert isinstance(game.pending, Confirm) and game.pending.seat is PlayerId.P1
    assert project(game, PlayerId.P1).pending == game.pending
    assert project(game, PlayerId.P2).pending is None


def test_a_trigger_registered_under_a_ruleset_fires_only_while_it_is_active(reacting, monkeypatch):
    game = two_seat_game()
    put_in_play(game, holding("played", printed_id="hand_probe"))
    seen: list[str] = []
    reacting(
        TurnBoundary,
        "hand_probe",
        lambda ctx: seen.append("onyx") or [],
        ruleset=ruleset.ONYX.name,
        boundary=Boundary.BEGINNING,
    )
    reacting(
        TurnBoundary,
        "hand_probe",
        lambda ctx: seen.append("she") or [],
        ruleset=ruleset.SHATTERED_EMPIRE.name,
        boundary=Boundary.BEGINNING,
    )

    fire(game, TurnBoundary(PlayerId.P1, Boundary.BEGINNING))
    monkeypatch.setattr(ruleset, "ACTIVE", ruleset.ONYX)
    fire(game, TurnBoundary(PlayerId.P1, Boundary.BEGINNING))

    assert seen == ["she", "onyx"]


def _watcher_game(watching) -> tuple[GameState, list[str]]:
    """P1 holding a watcher whose condition is "a marker is in play", with three markers in hand.
    Returns the game and the ids the watch has reacted for."""
    told: list[str] = []

    def record(ctx):
        told.append(ctx.card.id)
        return []

    watching(
        "watch_probe",
        lambda game, card: any(
            held.printed_id == "marker_probe" for held in game.table.battlefield.cards
        ),
        record,
    )
    game = two_seat_game()
    hand = game.table.zones[ZoneKey(PlayerId.P1, ZoneRole.HAND)]
    hand.add(register(game.table, _fate("watcher", printed_id="watch_probe")))
    for index in range(3):
        hand.add(register(game.table, _fate(f"marker{index}", printed_id="marker_probe")))
    return game, told


def _fate(card_id: str, *, printed_id: str) -> L5RCard:
    return L5RCard.of(
        FatePrint,
        id=card_id,
        name="F",
        printed_id=card_id if printed_id is None else printed_id,
        side=Side.FATE,
        owner=PlayerId.P1,
    )


def test_a_watched_condition_is_answered_each_time_it_becomes_true(watching):
    game, told = _watcher_game(watching)

    resolve_effects(game, [PutIntoPlay("marker0")])
    assert told == ["watcher"]

    resolve_effects(game, [PutIntoPlay("marker1")])
    assert told == ["watcher"]

    resolve_effects(game, [Destroy("marker0", PlayerId.P1), Destroy("marker1", PlayerId.P1)])
    resolve_effects(game, [PutIntoPlay("marker2")])
    assert told == ["watcher", "watcher"]


def test_a_watched_card_arriving_where_it_watches_while_its_condition_holds_is_answered(watching):
    game, told = _watcher_game(watching)
    resolve_effects(game, [PutIntoPlay("marker0")])
    resolve_effects(game, [Discard("watcher", PlayerId.P1)])
    assert told == ["watcher"]

    resolve_effects(game, [MoveToHand("watcher", PlayerId.P1)])

    assert told == ["watcher", "watcher"]


def test_a_watched_condition_is_answered_before_the_rest_of_the_text_that_fulfilled_it(watching):
    # CR 20F, Timing: the watch answers the entry before the discard written after it.
    game, _ = _watcher_game(watching)
    in_play_when_answered: list[bool] = []
    watching(
        "order_probe",
        lambda game, card: any(held.id == "marker0" for held in game.table.battlefield.cards),
        lambda ctx: in_play_when_answered.append(
            any(held.id == "marker0" for held in ctx.game.table.battlefield.cards)
        )
        or [],
    )
    game.table.zones[ZoneKey(PlayerId.P1, ZoneRole.HAND)].add(
        register(game.table, _fate("second", printed_id="order_probe"))
    )

    resolve_effects(game, [PutIntoPlay("marker0"), Discard("marker0", PlayerId.P1)])

    assert in_play_when_answered == [True]


def test_a_watch_is_not_answered_once_its_card_has_left_where_it_watches(watching):
    game, told = _watcher_game(watching)

    resolve_effects(
        game, [Simultaneously((PutIntoPlay("marker0"), Discard("watcher", PlayerId.P1)))]
    )

    assert told == []


def test_each_watch_on_a_card_is_remembered_apart(watching):
    told: list[str] = []
    watching(
        "twin_probe",
        lambda game, card: len(game.table.battlefield.cards) >= 1,
        lambda ctx: told.append(ctx.event.key) or [],
        key="one",
    )
    watching(
        "twin_probe",
        lambda game, card: len(game.table.battlefield.cards) >= 2,
        lambda ctx: told.append(ctx.event.key) or [],
        key="two",
    )
    game = two_seat_game()
    hand = game.table.zones[ZoneKey(PlayerId.P1, ZoneRole.HAND)]
    hand.add(register(game.table, _fate("twin", printed_id="twin_probe")))
    for index in range(2):
        hand.add(register(game.table, _fate(f"m{index}", printed_id="plain")))

    resolve_effects(game, [PutIntoPlay("m0")])
    resolve_effects(game, [PutIntoPlay("m1")])

    assert told == ["one", "two"]


def test_a_watch_can_look_from_play(watching):
    told: list[str] = []
    watching(
        "in_play_probe",
        lambda game, card: card.bowed,
        lambda ctx: told.append(ctx.card.id) or [],
        where=(CardLocation.BATTLEFIELD,),
    )
    game = two_seat_game()
    watcher = put_in_play(game, _fate("sentinel", printed_id="in_play_probe"))

    resolve_effects(game, [Bow(watcher.id)])

    assert told == ["sentinel"]


def test_registering_a_trigger_on_a_watched_condition_is_refused():
    with pytest.raises(ValueError, match="own watch"):
        on(ConditionFulfilled, "anything")


def test_a_record_lapses_at_its_own_moment_whatever_its_kind():
    game = two_seat_game()
    kept = LobbyModifier("src", PlayerId.P1, 1, END_OF_TURN)
    game.ongoing += [
        LobbyModifier("src", PlayerId.P1, 1, END_OF_BATTLE),
        ConditionalModifier("src", Condition.ATTACKING, Stat.FORCE, -1, END_OF_BATTLE),
        kept,
    ]

    lapse_ongoing(game, END_OF_BATTLE)

    assert game.ongoing == [kept]


def test_the_turns_end_lapses_every_record_but_those_that_outlast_it():
    game = two_seat_game()
    kept = [
        LobbyModifier("src", PlayerId.P1, 1, Duration.PERMANENT),
        LobbyModifier("src", PlayerId.P1, 1, Duration.WHILE_SOURCE_IN_PLAY),
    ]
    game.ongoing += [
        LobbyModifier("src", PlayerId.P1, 1, Duration.UNTIL_END_OF_TURN),
        ConditionalModifier("src", Condition.ATTACKING, Stat.FORCE, -1, END_OF_TURN),
        LobbyModifier("src", PlayerId.P1, 1, END_OF_BATTLE),
        *kept,
    ]

    lapse_ongoing(game, END_OF_TURN)

    assert game.ongoing == kept


def test_a_chi_bonus_lapsing_under_a_personality_kills_him():
    game = two_seat_game()
    hero = put_in_play(game, personality("hero", chi=0))
    game.ongoing.append(Modifier("src", hero.id, Stat.CHI, 1, END_OF_BATTLE))

    lapse_ongoing(game, END_OF_BATTLE)

    assert hero not in game.table.battlefield.cards


def test_resolving_the_effects_held_for_the_turns_end_leaves_ongoing_records_in_force():
    game = two_seat_game()
    penalty = ConditionalModifier("src", Condition.ATTACKING, Stat.FORCE, -1, END_OF_TURN)
    game.ongoing.append(penalty)

    resolve_delayed(game, END_OF_TURN)

    assert game.ongoing == [penalty]


def test_reaching_a_moment_lapses_what_lasted_until_it_before_resolving_what_waited_for_it():
    game = two_seat_game()
    farm = put_in_play(game, holding("farm"))
    game.ongoing.append(Negation("ring", END_OF_BATTLE, effect_kind=Bow, subject_id="farm"))
    game.delayed = [(END_OF_BATTLE, Bow("farm"))]

    reach_moment(game, END_OF_BATTLE)

    assert game.ongoing == []
    assert farm.bowed


def _standing(game, card):
    return any(held is card for held in game.table.battlefield.cards)


def test_a_trait_acting_before_a_destruction_resolves_while_the_card_stands(reacting):
    game = two_seat_game()
    dying = put_in_play(game, personality("dying", printed_id="before_probe"))
    reacting(
        Destroying,
        "before_probe",
        lambda ctx: [GainHonor(PlayerId.P1, 1)] if _standing(game, ctx.card) else [],
    )

    resolve_effects(game, [Destroy(dying.id, PlayerId.P2)])

    seen = [e for e in game.turn_events if isinstance(e, Destroying | HonorChanged | Destroyed)]
    assert [type(event) for event in seen] == [Destroying, HonorChanged, Destroyed]
    assert seen[0] == Destroying(dying.id, PlayerId.P2, Location.home(PlayerId.P1), PlayerId.P1)


def test_a_destruction_nothing_acts_before_is_not_announced():
    game = two_seat_game()
    dying = put_in_play(game, personality("dying"))
    before = len(game.turn_events)

    resolve_effects(game, [Destroy(dying.id, PlayerId.P2)])

    assert game.turn_events[before:] == (
        Destroyed(dying.id, PlayerId.P2, Location.home(PlayerId.P1), PlayerId.P1),
    )


def test_a_followers_trait_acts_before_its_personality_is_destroyed(reacting):
    game = two_seat_game()
    put_in_play(game, personality("hero"))
    follower = attached(game, attachment("follower", printed_id="before_probe"), "hero")
    reacting(
        Destroying,
        "before_probe",
        lambda ctx: [GainHonor(PlayerId.P1, 1)] if ctx.event.card_id == ctx.card.id else [],
    )

    resolve_effects(game, [Destroy("hero", PlayerId.P2)])

    assert game.table.seats[PlayerId.P1].honor == 1
    assert not _standing(game, follower)


def test_a_destruction_a_state_based_rule_demands_is_not_announced(reacting):
    game = two_seat_game()
    dying = put_in_play(game, personality("dying", printed_id="before_probe", chi=1))
    reacting(Destroying, "before_probe", lambda ctx: [GainHonor(PlayerId.P1, 1)])

    resolve_effects(
        game, [GrantModifier("curse", dying.id, Stat.CHI, -1, Duration.UNTIL_END_OF_TURN)]
    )

    assert not _standing(game, dying)
    assert not any(isinstance(event, Destroying) for event in game.turn_events)


def test_a_groups_destructions_are_announced_together_and_ordered_by_the_active_player(reacting):
    game = two_seat_game()
    first = put_in_play(game, personality("first", printed_id="before_probe"))
    second = put_in_play(game, personality("second", printed_id="before_probe"))
    reacting(
        Destroying,
        "before_probe",
        lambda ctx: [GainHonor(PlayerId.P1, 1)]
        if ctx.event.card_id == ctx.card.id and _standing(game, first) and _standing(game, second)
        else [],
    )

    resolve_effects(
        game,
        [
            Simultaneously(
                (
                    Destroy(first.id, PlayerId.P2),
                    GainHonor(PlayerId.P2, 1),
                    Destroy(second.id, PlayerId.P2),
                )
            )
        ],
    )
    assert isinstance(game.pending, ChooseNextTrigger)
    action_sequence.submit(game, DecisionResponse((second.id,)))

    announced = [e.card_id for e in game.turn_events if isinstance(e, Destroying)]
    assert announced == [first.id, second.id]
    assert game.table.seats[PlayerId.P1].honor == 2
    assert not _standing(game, first) and not _standing(game, second)


def test_a_group_paused_while_destroying_commits_each_member_once(reacting):
    game = two_seat_game()
    asking = put_in_play(game, personality("asking", printed_id="before_probe"))
    quiet = put_in_play(game, personality("quiet"))
    reacting(
        Destroying,
        "before_probe",
        lambda ctx: [Choose(ctx.card.owner, (), 0, 0, "test_sandwich", ctx.card.id)]
        if ctx.event.card_id == ctx.card.id
        else [],
    )

    resolve_effects(
        game,
        [Simultaneously((Destroy(asking.id, PlayerId.P2), Destroy(quiet.id, PlayerId.P2)))],
    )
    assert _standing(game, asking) and _standing(game, quiet)
    action_sequence.submit(game, DecisionResponse(()))

    destroyed = [e.card_id for e in game.turn_events if isinstance(e, Destroyed)]
    assert destroyed == [asking.id, quiet.id]


def test_a_group_member_the_forecast_missed_is_announced_before_it_commits(reacting):
    game = two_seat_game()
    first = put_in_play(game, personality("first", printed_id="returning_probe"))
    late = register(game.table, personality("late", printed_id="before_probe"))
    game.table.zones[ZoneKey(PlayerId.P1, ZoneRole.HAND)].add(late)
    reacting(
        Destroying,
        "returning_probe",
        lambda ctx: [PutIntoPlay(late.id)] if ctx.event.card_id == ctx.card.id else [],
    )
    reacting(
        Destroying,
        "before_probe",
        lambda ctx: [GainHonor(PlayerId.P1, 1)] if ctx.event.card_id == ctx.card.id else [],
    )

    resolve_effects(
        game,
        [Simultaneously((Destroy(first.id, PlayerId.P2), Destroy(late.id, PlayerId.P2)))],
    )

    announced = [e.card_id for e in game.turn_events if isinstance(e, Destroying)]
    assert announced == [first.id, late.id]
    assert game.table.seats[PlayerId.P1].honor == 1
    assert not _standing(game, late)


def test_a_trait_destroying_its_own_card_before_it_is_destroyed_never_settles(reacting):
    game = two_seat_game()
    dying = put_in_play(game, personality("dying", printed_id="before_probe"))
    reacting(Destroying, "before_probe", lambda ctx: [Destroy(ctx.card.id, PlayerId.P2)])

    with pytest.raises(RuntimeError, match="did not converge"):
        resolve_effects(game, [Destroy(dying.id, PlayerId.P2)])


def _negated_by_a_lasting_negation(game, destroy):
    game.ongoing.append(Negation("ward", END_OF_TURN, effect_kind=Destroy))
    resolve_effects(game, [destroy])


def _negated_by_an_interrupt(game, destroy):
    game.modifications.append(
        Replacement(bound=destroy, card_id="ward", replacement=Negated(destroy))
    )
    game.interrupts_offered = True
    resolve_action_effects(game, [destroy])


@pytest.mark.parametrize(
    "negate",
    [_negated_by_a_lasting_negation, _negated_by_an_interrupt],
    ids=["lasting-negation", "interrupt"],
)
def test_a_destruction_that_will_be_negated_is_not_announced(reacting, negate):
    game = two_seat_game()
    dying = put_in_play(game, personality("dying", printed_id="before_probe"))
    reacting(Destroying, "before_probe", lambda ctx: [GainHonor(PlayerId.P1, 1)])

    negate(game, Destroy(dying.id, PlayerId.P2))

    assert _standing(game, dying)
    assert game.table.seats[PlayerId.P1].honor == 0


def test_a_negation_granted_before_a_destruction_negates_it(reacting):
    game = two_seat_game()
    dying = put_in_play(game, personality("dying", printed_id="before_probe"))
    reacting(
        Destroying,
        "before_probe",
        lambda ctx: [
            GrantNegation(
                Negation(ctx.card.id, END_OF_TURN, effect_kind=Destroy, subject_id=ctx.card.id)
            )
        ],
    )

    resolve_effects(game, [Destroy(dying.id, PlayerId.P2)])

    assert _standing(game, dying)


def test_a_card_whose_announced_destruction_was_negated_is_announced_again(reacting):
    game = two_seat_game()
    dying = put_in_play(game, personality("dying", printed_id="before_probe"))
    reacting(
        Destroying,
        "before_probe",
        lambda ctx: [
            GrantNegation(
                Negation(
                    ctx.card.id, END_OF_TURN, effect_kind=Destroy, subject_id=ctx.card.id, once=True
                )
            )
        ],
    )

    resolve_effects(game, [Destroy(dying.id, PlayerId.P2), Destroy(dying.id, PlayerId.P2)])

    assert sum(isinstance(event, Destroying) for event in game.turn_events) == 2
    assert _standing(game, dying)


def test_a_question_asked_before_a_destruction_is_the_traits_own_and_the_card_dies_once(reacting):
    game = two_seat_game()
    dying = put_in_play(game, personality("dying", printed_id="before_probe"))
    reacting(
        Destroying,
        "before_probe",
        lambda ctx: [Choose(ctx.card.owner, (), 0, 0, "test_sandwich", ctx.card.id)],
    )

    resolve_effects(game, [Destroy(dying.id, PlayerId.P2)])

    assert game.pending.triggered and _standing(game, dying)
    action_sequence.submit(game, DecisionResponse(()))
    assert [e.card_id for e in game.turn_events if isinstance(e, Destroyed)] == [dying.id]


def test_an_announced_destruction_is_not_among_what_the_action_did(reacting):
    game = two_seat_game()
    dying = put_in_play(game, personality("dying", printed_id="before_probe"))
    reacting(Destroying, "before_probe", lambda ctx: [GainHonor(PlayerId.P1, 1)])

    resolve_action_effects(game, [Destroy(dying.id, PlayerId.P2)])

    assert any(isinstance(event, Destroying) for event in game.turn_events)
    assert not any(isinstance(event, Destroying) for event in game.action_events)


def test_an_effect_delayed_to_a_cards_destruction_waits_for_that_card_and_resolves_once():
    game = two_seat_game()
    put_in_play(game, personality("waited"))
    put_in_play(game, personality("other"))
    held = DelayedEffect(GainHonor(PlayerId.P1, 1), NextTime(Destroyed, "waited"))

    resolve_effects(game, [held, Destroy("other", PlayerId.P2)])
    assert game.table.seats[PlayerId.P1].honor == 0

    resolve_effects(game, [Destroy("waited", PlayerId.P2)])
    assert game.table.seats[PlayerId.P1].honor == 1
    assert game.delayed == []
