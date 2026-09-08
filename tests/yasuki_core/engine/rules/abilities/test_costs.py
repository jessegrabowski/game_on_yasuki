from yasuki_core.engine.players import PlayerId
from yasuki_core.engine.rules.abilities.model import Ability
from yasuki_core.engine.rules.abilities.registry import register_ability
from yasuki_core.engine.rules.actions import ActionTiming, ActivateAbility
from yasuki_core.engine.rules.decisions import (
    ChooseAbilityTarget,
    ChooseCards,
    DecisionResponse,
)
from yasuki_core.engine.rules.effects import AdjustCounter, Choose
from yasuki_core.engine.rules.log import replay
from yasuki_core.engine.rules.triggers import choice_resolver
from yasuki_core.engine.session import EngineSession
from yasuki_core.engine.table import TableState
from yasuki_core.game_pieces.counters import WEALTH

from tests.yasuki_core.engine.builders import holding, put_in_play


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
