from yasuki_core.engine.rules.abilities import Ability, no_cost, register_ability
from yasuki_core.engine.rules.actions import ActionTiming
from yasuki_core.engine.rules.effects import AdjustCounter, Effect
from yasuki_core.engine.rules.events import CardDiscarded
from yasuki_core.engine.rules.state import GameState
from yasuki_core.engine.rules.triggers import action_did, at_cap
from yasuki_core.game_pieces.cards import L5RCard
from yasuki_core.game_pieces.constants import Side
from yasuki_core.game_pieces.counters import WEALTH


# --- Caravansary ---

WEALTH_CAP = 3


def _caravansary_targets(game: GameState, source: L5RCard) -> list[str]:
    """Itself, once the action just resolved was its controller's and discarded a Fate card.

    A Response reads the action rather than the board: the discarded card is already in a pile by
    the time the Step opens, and nothing on the board says whose action put it there.
    """
    if at_cap(source, WEALTH, WEALTH_CAP):
        return []
    mine = any(
        event.side is Side.FATE and event.cause is source.owner
        for event in action_did(game, CardDiscarded)
    )
    return [source.id] if mine else []


def _caravansary_effects(game: GameState, source: L5RCard, target: L5RCard) -> list[Effect]:
    return [AdjustCounter(source.id, WEALTH, 1)]


register_ability(
    "caravansary",
    Ability(
        timings=(ActionTiming.RESPONSE,),
        label="Response: take a +1GP Wealth token for the Fate card your action discarded",
        cost=no_cost,
        targets=_caravansary_targets,
        effects=_caravansary_effects,
        all_targets=True,
    ),
)
