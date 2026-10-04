from yasuki_core.engine.players import PlayerId
from yasuki_core.engine.rules.abilities.costs import (
    BOW_WAIVERS,
    bow_cost,
    declare_amount,
    ignoring_bow_costs,
    register_bow_waiver,
)
from yasuki_core.engine.rules.abilities.model import Ability
from yasuki_core.engine.rules.abilities.registry import register_ability
from yasuki_core.engine.rules.vocabulary.actions import ActionTiming, ActivateAbility
from yasuki_core.engine.rules.vocabulary.decisions import (
    ChooseAbilityTarget,
    ChooseCards,
    ChoosePayment,
    DecisionResponse,
)
from yasuki_core.engine.rules.effects import AdjustCounter, AskAmount, Bow, Choose, PayGold
from yasuki_core.engine.replay.game_log import replay
from yasuki_core.engine.rules.state import GameState
from yasuki_core.engine.rules.triggers import choice_resolver, resolve_effects
from yasuki_core.engine.rules.turn.action_sequence import submit
from yasuki_core.engine.session import EngineSession
from yasuki_core.engine.table import TableState
from yasuki_core.game_pieces.counters import WEALTH

from tests.yasuki_core.engine.builders import (
    attached,
    attachment,
    holding,
    personality,
    put_in_play,
    two_seat_game,
)


@choice_resolver("test_cost_pauses")
def _test_cost_grant(game, source_id, chosen, seat):
    return [AdjustCounter(card_id, WEALTH, 1) for card_id in chosen]


# A synthetic ability whose cost pauses for a choice. It exercises the deferred target selection:
# the cost's own decision must resolve before the ability's target is asked, neither clobbering the
# other. No real card pays a cost that pauses yet.
register_ability(
    "test_cost_pauses",
    Ability(
        timings=(ActionTiming.OPEN,),
        label="test",
        cost=lambda game, source: [
            Choose(source.owner, (source.id,), 0, 1, "test_cost_pauses", source.id)
        ],
        targets=lambda game, card: [
            c.id
            for c in game.table.battlefield.cards
            if c.owner is card.owner and c is not card and "Farm" in c.keywords
        ],
        effects=lambda game, source, target: [AdjustCounter(target.id, WEALTH, 1)],
    ),
)


def test_a_cost_that_pauses_resolves_before_the_ability_target():
    state = TableState.empty_two_seat()
    put_in_play(state, holding("src", printed_id="test_cost_pauses"))
    put_in_play(
        state, holding("tgt", printed_id="plain_farm", keywords=("Farm",), gold_production=2)
    )
    session = EngineSession.start(state, PlayerId.P1)

    session.act(PlayerId.P1, ActivateAbility("src"))
    assert isinstance(session.game.pending, ChooseCards)  # the cost's choice comes first
    assert session.game.pending.candidates == ("src",)

    session.submit(PlayerId.P1, DecisionResponse(("src",)))
    pending = session.game.pending
    assert isinstance(pending, ChooseAbilityTarget)  # the target, deferred until the cost resolved
    assert pending.candidates == ("tgt",)
    assert session.game.table.cards_by_id["src"].counters == {"wealth": 1}  # cost choice applied

    session.submit(PlayerId.P1, DecisionResponse(("tgt",)))
    assert session.game.pending is None
    assert session.game.table.cards_by_id["tgt"].counters == {"wealth": 1}  # ability effect applied
    assert replay(session.log) == session.game  # the deferred-cost chain replays deterministically


@choice_resolver("amount_probe")
def _amount_probe(game, source_id, chosen, seat):
    return []


def _answer_two(ask) -> GameState:
    game = two_seat_game()
    source = put_in_play(game, holding("source", owner=PlayerId.P1))
    resolve_effects(game, [ask(source)])
    submit(game, DecisionResponse(("2",)))
    return game


def test_naming_an_amount_charges_nothing_its_resolver_does_not():
    game = _answer_two(
        lambda source: AskAmount(PlayerId.P1, (1, 2), "How many?", "amount_probe", source.id)
    )

    assert game.amount_declared == 2
    assert game.pending is None


def test_a_declared_amount_of_gold_is_charged():
    game = _answer_two(lambda source: declare_amount(source, (1, 2), "How much?"))

    assert game.amount_declared == 2
    assert isinstance(game.pending, ChoosePayment) and game.pending.amount == 2


def _bow_and_pay(game, source):
    return [PayGold(source.owner, 2, source.name), Bow(source.id)]


def test_ignoring_bow_costs_drops_the_bow_and_keeps_the_rest():
    game = two_seat_game()
    farm = put_in_play(game, holding("farm"))

    assert ignoring_bow_costs(_bow_and_pay)(game, farm) == [PayGold(PlayerId.P1, 2, "farm")]


def test_ignoring_bow_costs_drops_the_waiver_a_bow_would_ask_about():
    game = two_seat_game()
    monk = put_in_play(game, personality("monk"))
    attached(game, attachment("waiver", printed_id="waiver_probe"), "monk")
    register_bow_waiver("waiver_probe")
    try:
        assert len(bow_cost(game, monk)) == 1
        assert ignoring_bow_costs(bow_cost)(game, monk) == []
    finally:
        BOW_WAIVERS.discard("waiver_probe")
