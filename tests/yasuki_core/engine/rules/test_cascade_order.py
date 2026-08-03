import pytest

from yasuki_core.engine.players import PlayerId
from yasuki_core.engine.rules.events import CounterGained, EnteredPlay
from yasuki_core.engine.table import DeckKey, ZoneKey, ZoneRole
from yasuki_core.game_pieces.constants import Side
from yasuki_core.engine.rules.decisions import ChoosePayment, DecisionResponse
from yasuki_core.engine.rules.effects import AdjustCounter, RecruitCard, Then
from yasuki_core.engine.rules.flow import run_stack, submit
from yasuki_core.engine.rules.triggers import fire, on, resolve_effects
from yasuki_core.game_pieces.counters import SINCERITY, WEALTH

from tests.yasuki_core.engine.builders import (
    holding,
    province_card,
    register,
    put_in_play,
    two_seat_game,
)

# Characterization tests: these pin the *order* the cascade resolves in, which the outcome-focused
# suites do not. A refactor that reorders decisions can leave every final board state identical, so
# without these the reordering ships silently.

FIRING_ORDER: list[str] = []


@on(EnteredPlay, "order_two_effects")
def _two_effects(ctx):
    """Emit two counter adjustments; the first raises a CounterGained that has its own subscriber."""
    return [
        AdjustCounter(ctx.card.id, WEALTH, 1),
        AdjustCounter(ctx.card.id, SINCERITY, 1),
    ]


@on(CounterGained, "order_watcher")
def _watch_counter_gain(ctx):
    gainer = ctx.game.table.cards_by_id[ctx.event.card_id]
    FIRING_ORDER.append(("watcher", gainer.id, dict(gainer.counters)))
    return []


@on(EnteredPlay, "order_recorder")
def _record_firing(ctx):
    FIRING_ORDER.append(("recorder", ctx.card.id))
    return []


@pytest.fixture(autouse=True)
def order_log():
    """Clear the shared firing log around every test, so one test's cascade cannot leak into the
    next. Autouse because forgetting it would produce a passing test that asserts the wrong thing."""
    FIRING_ORDER.clear()
    yield FIRING_ORDER
    FIRING_ORDER.clear()


def test_every_effect_from_one_trigger_applies_before_its_derived_events_fire():
    # The worklist drains the effects in hand before popping the event queue, so the subscriber sees
    # both adjustments already committed — and each gain raises its own event, so it fires twice.
    game = two_seat_game()
    source = put_in_play(game, holding("P1-source", printed_id="order_two_effects"))
    put_in_play(game, holding("P1-watcher", printed_id="order_watcher"))

    fire(game, EnteredPlay(source.id))

    both_counters = ("watcher", "P1-source", {"wealth": 1, "sincerity": 1})
    assert FIRING_ORDER == [both_counters, both_counters]


def test_triggers_for_one_event_fire_in_canonical_owner_then_id_order():
    # Insertion order into the battlefield must not decide firing order, or replay drifts.
    game = two_seat_game()
    put_in_play(game, holding("P2-z", printed_id="order_recorder", owner=PlayerId.P2))
    put_in_play(game, holding("P1-b", printed_id="order_recorder"))
    put_in_play(game, holding("P1-a", printed_id="order_recorder"))

    fire(game, EnteredPlay("P1-a"))

    assert FIRING_ORDER == [("recorder", "P1-a"), ("recorder", "P1-b"), ("recorder", "P2-z")]


def test_a_second_subscriber_still_fires_after_the_first_ones_effects_resolve():
    game = two_seat_game()
    source = put_in_play(game, holding("P1-a-source", printed_id="order_two_effects"))
    put_in_play(game, holding("P1-b-recorder", printed_id="order_recorder"))
    put_in_play(game, holding("P1-c-watcher", printed_id="order_watcher"))

    fire(game, EnteredPlay(source.id))

    # Every EnteredPlay subscriber runs before the derived CounterGained events are dequeued.
    both_counters = ("watcher", "P1-a-source", {"wealth": 1, "sincerity": 1})
    assert FIRING_ORDER == [("recorder", "P1-b-recorder"), both_counters, both_counters]


def test_then_defers_its_effects_until_the_cascade_has_finished_reacting():
    # An effect placed inline runs before the events already queued behind it. Then exists for the
    # step that must follow another card's reaction to what just happened.
    game = two_seat_game()
    source = put_in_play(game, holding("P1-source"))
    put_in_play(game, holding("P1-watcher", printed_id="order_watcher"))

    resolve_effects(
        game,
        [
            AdjustCounter(source.id, WEALTH, 1),
            Then((AdjustCounter(source.id, SINCERITY, 1),)),
        ],
    )

    assert FIRING_ORDER == [("watcher", "P1-source", {"wealth": 1})]  # reacted already
    assert source.counters.get("sincerity") is None  # deferred effect has not run

    run_stack(game)

    assert source.counters["sincerity"] == 1


def test_recruit_card_pauses_for_payment_and_brings_the_card_in():
    game = two_seat_game()
    put_in_play(game, holding("P1-gold", gold_production=8))
    target = province_card(game, "P1-target", gold_cost=2)

    resolve_effects(game, [RecruitCard(target.id)])

    assert isinstance(game.pending, ChoosePayment)
    assert game.pending.amount == 2  # the target's gold cost

    submit(game, DecisionResponse(("P1-gold",)))

    assert target in game.table.battlefield.cards


def test_recruit_card_refills_the_vacated_province_face_up_with_renew():
    game = two_seat_game()
    put_in_play(game, holding("P1-gold", gold_production=8))
    target = province_card(game, "P1-target", gold_cost=2)
    game.table.decks[DeckKey(PlayerId.P1, Side.DYNASTY)].cards = [
        register(game.table, holding("P1-refill"))
    ]

    resolve_effects(game, [RecruitCard(target.id, renew=True)])
    submit(game, DecisionResponse(("P1-gold",)))

    refill = game.table.zones[ZoneKey(PlayerId.P1, ZoneRole.PROVINCE, 0)].cards[-1]
    assert refill.face_up


def test_recruit_card_leaves_the_province_face_down_without_renew():
    game = two_seat_game()
    put_in_play(game, holding("P1-gold", gold_production=8))
    target = province_card(game, "P1-target", gold_cost=2)
    game.table.decks[DeckKey(PlayerId.P1, Side.DYNASTY)].cards = [
        register(game.table, holding("P1-refill"))
    ]

    resolve_effects(game, [RecruitCard(target.id)])
    submit(game, DecisionResponse(("P1-gold",)))

    refill = game.table.zones[ZoneKey(PlayerId.P1, ZoneRole.PROVINCE, 0)].cards[-1]
    assert not refill.face_up
