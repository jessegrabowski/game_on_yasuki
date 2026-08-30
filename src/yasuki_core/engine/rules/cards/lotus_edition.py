from yasuki_core.engine.players import PlayerId
from yasuki_core.engine.rules.abilities import (
    Ability,
    CardLocation,
    itself,
    personalities_in_play,
    register_ability,
)
from yasuki_core.engine.rules.actions import ActionTiming
from yasuki_core.engine.rules.economy import unit_gold_cost
from yasuki_core.engine.rules.effects import (
    AskAmount,
    Choose,
    Destroy,
    Effect,
    GainHonor,
    PayGold,
)
from yasuki_core.engine.rules.legality import reachable_gold
from yasuki_core.engine.rules.state import GameState
from yasuki_core.engine.rules.triggers import choice_resolver
from yasuki_core.game_pieces.cards import L5RCard


# --- Hired Killer ---


# "equals the amount paid minus 2" and "Lose 3 Honor", as the card prints them.
HONOR_LOST = 3
PAID_ABOVE_UNIT_COST = 2


def _hired_killer_amounts(game: GameState, source: L5RCard) -> tuple[int, ...]:
    """Every amount the seat could spend, from nothing up to what it can raise.

    The seat names its own amount rather than picking from the ones that reach a legal target.
    Which Personality an amount reaches is the card's own arithmetic, so an amount that reaches
    none of them is a legal announcement that destroys nothing.

    A board with no Personality on it offers no amount at all: nothing there can be targeted, and a
    cost with no amount to choose is not payable (CR, Good Faith).
    """
    if not personalities_in_play(game):
        return ()
    return tuple(range(reachable_gold(game, source.owner) + 1))


def _hired_killer_cost(game: GameState, source: L5RCard) -> list[Effect]:
    """Settle the amount before the target is chosen: the amount is the cost block, and the legal
    targets are shaped by it (CR, Action Sequence steps B and C)."""
    return [
        AskAmount(
            source.owner,
            _hired_killer_amounts(game, source),
            "How much Gold do you spend on Hired Killer?",
            "hired_killer",
            source.id,
        )
    ]


@choice_resolver("hired_killer")
def _resolve_hired_killer(
    game: GameState, source_id: str, chosen: tuple[str, ...], seat: PlayerId
) -> list[Effect]:
    """Pay the amount, then choose among the Personalities it reaches. More than one unit can cost
    the same, so the choice remains after the amount is settled.

    An amount that reaches no Personality destroys nothing: the Gold is spent in the cost step and
    the effects after it do not happen, the Honor loss included, because an effect that requires a
    target and cannot find one stops the effects that follow it (CR, Action Sequence step E).
    """
    paid = int(chosen[0])
    targets = tuple(
        card.id
        for card in personalities_in_play(game)
        if unit_gold_cost(game, card) == paid - PAID_ABOVE_UNIT_COST
    )
    payment = PayGold(seat, paid, "Hired Killer")
    if not targets:
        return [payment]
    return [payment, Choose(seat, targets, 1, 1, "hired_killer_target", source_id)]


@choice_resolver("hired_killer_target", prompt="Choose a Personality to destroy")
def _resolve_hired_killer_target(
    game: GameState, source_id: str, chosen: tuple[str, ...], seat: PlayerId
) -> list[Effect]:
    """Destroy the target, then lose the Honor, in the order the card prints them."""
    return [Destroy(chosen[0], seat), GainHonor(seat, -HONOR_LOST)]


register_ability(
    "hired_killer",
    Ability(
        timings=(ActionTiming.OPEN,),
        label="Open: Spend Gold to destroy a target Personality",
        cost=_hired_killer_cost,
        targets=itself,
        effects=lambda game, source, target: [],
        all_targets=True,
        located_at=(CardLocation.HAND,),
    ),
)
