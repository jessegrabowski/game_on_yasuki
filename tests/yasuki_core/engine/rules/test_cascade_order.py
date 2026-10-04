import pytest

from yasuki_core.engine.players import PlayerId
from yasuki_core.engine.rules.vocabulary.game_events import CounterChanged, EnteredPlay
from yasuki_core.engine.table import DeckKey, ZoneKey, ZoneRole
from yasuki_core.game_pieces.constants import Side
from yasuki_core.engine.rules.vocabulary.decisions import (
    ChooseNextTrigger,
    ChoosePayment,
    DecisionResponse,
)
from yasuki_core.engine.rules.effects import AdjustCounter
from yasuki_core.engine.rules.rulebook.recruit import recruit_card
from yasuki_core.engine.rules.turn.action_sequence import submit
from yasuki_core.engine.rules.turn.sequence import run_stack
from yasuki_core.engine.rules import triggers
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
    """Emit two counter adjustments. The first raises a CounterChanged that has its own
    subscriber."""
    return [
        AdjustCounter(ctx.card.id, WEALTH, 1),
        AdjustCounter(ctx.card.id, SINCERITY, 1),
    ]


@on(CounterChanged, "order_watcher")
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
    next. Autouse because forgetting it would produce a passing test that asserts the wrong
    thing."""
    FIRING_ORDER.clear()
    yield FIRING_ORDER
    FIRING_ORDER.clear()


def test_each_effect_of_a_trigger_is_reacted_to_before_the_next_applies():
    # CR 20F, Timing: "Once a triggered trait starts, activate all its costs, targeting, and effects
    # in sequence before proceeding, even if another action or triggered trait is under way."
    game = two_seat_game()
    source = put_in_play(game, holding("P1-source", printed_id="order_two_effects"))
    put_in_play(game, holding("P1-watcher", printed_id="order_watcher"))

    fire(game, EnteredPlay(source.id))

    assert FIRING_ORDER == [
        ("watcher", "P1-source", {"wealth": 1}),
        ("watcher", "P1-source", {"wealth": 1, "sincerity": 1}),
    ]


def test_each_effect_is_reacted_to_before_the_next_effect_in_its_list_applies():
    game = two_seat_game()
    source = put_in_play(game, holding("P1-source"))
    put_in_play(game, holding("P1-watcher", printed_id="order_watcher"))

    resolve_effects(
        game, [AdjustCounter(source.id, WEALTH, 1), AdjustCounter(source.id, SINCERITY, 1)]
    )

    assert FIRING_ORDER == [
        ("watcher", "P1-source", {"wealth": 1}),
        ("watcher", "P1-source", {"wealth": 1, "sincerity": 1}),
    ]


def test_triggers_for_one_event_fire_in_canonical_owner_then_id_order():
    # Insertion order into the battlefield must not decide firing order, or replay drifts.
    game = two_seat_game()
    put_in_play(game, holding("P2-z", printed_id="order_recorder", owner=PlayerId.P2))
    put_in_play(game, holding("P1-b", printed_id="order_recorder"))
    put_in_play(game, holding("P1-a", printed_id="order_recorder"))

    fire(game, EnteredPlay("P1-a"))

    assert FIRING_ORDER == [("recorder", "P1-a"), ("recorder", "P1-b"), ("recorder", "P2-z")]


def test_a_rulebook_trigger_fires_after_every_card_trigger_on_the_card_the_event_names():
    # A rulebook trigger is registered for the test only: the registry is module-global, and one
    # left behind would fire on every EnteredPlay in the process.
    def _rulebook_records(ctx):
        FIRING_ORDER.append(("rulebook", ctx.card.id))
        return []

    triggers.rulebook_trigger(EnteredPlay)(_rulebook_records)
    try:
        game = two_seat_game()
        put_in_play(game, holding("P2-z", printed_id="order_recorder", owner=PlayerId.P2))
        put_in_play(game, holding("P1-a", printed_id="order_recorder"))

        fire(game, EnteredPlay("P1-a"))
    finally:
        triggers._RULEBOOK_TRIGGERS[EnteredPlay].remove(_rulebook_records)

    assert FIRING_ORDER == [("recorder", "P1-a"), ("recorder", "P2-z"), ("rulebook", "P1-a")]


def test_the_active_player_orders_two_triggers_and_each_resolves_completely():
    # CR, Timing Conflicts: "the active player decides the order in which they happen", and each
    # resolves with everything it sets off before the next (CR 20F, Timing).
    game = two_seat_game()
    source = put_in_play(game, holding("P1-a-source", printed_id="order_two_effects"))
    rival = put_in_play(game, holding("P1-b-rival", printed_id="order_two_effects"))
    put_in_play(game, holding("P1-c-watcher", printed_id="order_watcher"))

    fire(game, EnteredPlay(source.id))
    order = game.pending
    submit(game, DecisionResponse((rival.id,)))

    assert isinstance(order, ChooseNextTrigger) and order.seat is game.active
    assert order.candidates == (source.id, rival.id)
    assert FIRING_ORDER == [
        ("watcher", "P1-b-rival", {"wealth": 1}),
        ("watcher", "P1-b-rival", {"wealth": 1, "sincerity": 1}),
        ("watcher", "P1-a-source", {"wealth": 1}),
        ("watcher", "P1-a-source", {"wealth": 1, "sincerity": 1}),
    ]


def test_recruit_card_pauses_for_payment_and_brings_the_card_in():
    game = two_seat_game()
    put_in_play(game, holding("P1-gold", gold_production=8))
    target = province_card(game, "P1-target", gold_cost=2)

    resolve_effects(game, recruit_card(game, target))

    assert isinstance(game.pending, ChoosePayment)
    assert game.pending.amount == 2  # the target's gold cost

    submit(game, DecisionResponse(("P1-gold",)))

    assert target in game.table.battlefield.cards


@on(EnteredPlay, "order_on_entry")
def _record_entry(ctx):
    if ctx.event.card_id == ctx.card.id:
        FIRING_ORDER.append(("entered", ctx.card.id))
    return []


def test_the_next_effect_runs_after_the_recruited_cards_entry_trait():
    # Both the entry trait and the next effect land in the same log, so this asserts their order
    # rather than merely that both happened.
    game = two_seat_game()
    put_in_play(game, holding("P1-gold", gold_production=8))
    put_in_play(game, holding("P1-watcher", printed_id="order_watcher"))
    target = province_card(game, "P1-target", gold_cost=2, printed_id="order_on_entry")

    resolve_effects(
        game,
        [
            *recruit_card(game, target),
            AdjustCounter("P1-watcher", WEALTH, 1),
        ],
    )
    submit(game, DecisionResponse(("P1-gold",)))

    assert FIRING_ORDER == [
        ("entered", "P1-target"),
        ("watcher", "P1-watcher", {"wealth": 1}),
    ]


def test_recruit_card_brings_in_a_card_that_costs_nothing_without_a_payment():
    game = two_seat_game()
    target = province_card(game, "P1-target", gold_cost=0)

    resolve_effects(game, recruit_card(game, target))
    run_stack(game)

    assert game.pending is None
    assert target in game.table.battlefield.cards


def test_the_next_effect_runs_after_a_free_recruited_cards_entry_trait():
    game = two_seat_game()
    put_in_play(game, holding("P1-watcher", printed_id="order_watcher"))
    target = province_card(game, "P1-target", gold_cost=0, printed_id="order_on_entry")

    resolve_effects(
        game,
        [
            *recruit_card(game, target),
            AdjustCounter("P1-watcher", WEALTH, 1),
        ],
    )
    run_stack(game)

    assert FIRING_ORDER == [
        ("entered", "P1-target"),
        ("watcher", "P1-watcher", {"wealth": 1}),
    ]


def test_recruit_card_refills_the_vacated_province_face_up_with_renew():
    game = two_seat_game()
    put_in_play(game, holding("P1-gold", gold_production=8))
    target = province_card(game, "P1-target", gold_cost=2)
    game.table.decks[DeckKey(PlayerId.P1, Side.DYNASTY)].cards = [
        register(game.table, holding("P1-refill"))
    ]

    resolve_effects(game, recruit_card(game, target, renew=True))
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

    resolve_effects(game, recruit_card(game, target))
    submit(game, DecisionResponse(("P1-gold",)))

    refill = game.table.zones[ZoneKey(PlayerId.P1, ZoneRole.PROVINCE, 0)].cards[-1]
    assert not refill.face_up
