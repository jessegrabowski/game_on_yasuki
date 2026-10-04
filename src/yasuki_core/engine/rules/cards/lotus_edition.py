from yasuki_core.engine.rules.abilities.model import Ability, CardLocation
from yasuki_core.engine.rules.abilities.registry import register_ability
from yasuki_core.engine.rules.board.queries import personalities_in_play
from yasuki_core.engine.rules.vocabulary.actions import ActionTiming
from yasuki_core.engine.rules.abilities.idioms import declarable_gold, declare_amount
from yasuki_core.engine.rules.gold.cost import unit_gold_cost
from yasuki_core.engine.rules.effects import Destroy, Effect, GainHonor
from yasuki_core.engine.rules.state import GameState
from yasuki_core.game_pieces.cards import L5RCard


# --- Hired Killer ---


# "equals the amount paid minus 2" and "Lose 3 Honor", as the card prints them.
HONOR_LOST = 3
PAID_ABOVE_UNIT_COST = 2


def _hired_killer_amounts(game: GameState, source: L5RCard) -> tuple[int, ...]:
    """Every amount the seat could spend, from nothing up to what it can declare.

    The seat names its own amount rather than picking from the ones that reach a legal target.
    Which Personality an amount reaches is the card's own arithmetic, so an amount that reaches
    none of them is a legal announcement that destroys nothing.

    A board with no Personality on it offers no amount at all: nothing there can be targeted, and a
    cost with no amount to choose is not payable (CR, Good Faith).
    """
    if not personalities_in_play(game):
        return ()
    return tuple(range(declarable_gold(game, source) + 1))


def _hired_killer_cost(game: GameState, source: L5RCard) -> list[Effect]:
    """The amount is the cost block, settled before the target is chosen, since the legal targets
    are shaped by it (CR, Action Sequence steps B and C)."""
    return [
        declare_amount(
            source,
            _hired_killer_amounts(game, source),
            "How much Gold do you spend on Hired Killer?",
        )
    ]


def _hired_killer_targets(game: GameState, source: L5RCard) -> list[str]:
    """The Personalities whose unit's Gold Cost is the amount paid minus two. More than one unit
    can cost the same, so a choice remains once the amount is settled. An amount that reaches none
    targets nothing, and the card does nothing more, the Honor loss included (CR, Action Sequence
    step E)."""
    if game.amount_declared is None:
        return []
    return [
        card.id
        for card in personalities_in_play(game)
        if unit_gold_cost(game, card) == game.amount_declared - PAID_ABOVE_UNIT_COST
    ]


def _hired_killer_effects(game: GameState, source: L5RCard, target: L5RCard) -> list[Effect]:
    """Destroy the target, then lose the Honor, in the order the card prints them."""
    return [
        Destroy(target.id, source.owner),
        GainHonor(source.owner, -HONOR_LOST, source_id=source.id),
    ]


register_ability(
    "hired_killer",
    Ability(
        timings=(ActionTiming.OPEN,),
        cost=_hired_killer_cost,
        targets=_hired_killer_targets,
        effects=_hired_killer_effects,
        located_at=(CardLocation.HAND,),
        targeting_message="a Personality to destroy",
        targets_after_cost=True,
    ),
)
