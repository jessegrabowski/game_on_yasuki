from yasuki_core.engine.players import PlayerId
from yasuki_core.engine.rules.abilities.costs import no_cost
from yasuki_core.engine.rules.abilities.model import Ability, CardLocation
from yasuki_core.engine.rules.abilities.registry import register_ability
from yasuki_core.engine.rules.board.queries import (
    opposed_units_in_battle,
    opposing_units_in_battle,
)
from yasuki_core.engine.rules.effects import (
    Bow,
    Choose,
    DelayedEffect,
    Effect,
    Evaluate,
    GainHonor,
    GrantDuelStat,
    StartDuel,
)
from yasuki_core.engine.rules.duel.procedure import (
    challenge_can_be_made,
    challenge_costs,
    duel_decided_by,
)
from yasuki_core.engine.rules.state import GameState
from yasuki_core.engine.rules.triggers import choice_resolver
from yasuki_core.engine.rules.turn.structure import DUEL_CONSEQUENCES
from yasuki_core.engine.rules.vocabulary.actions import ActionTiming
from yasuki_core.engine.rules.vocabulary.modifiers import Stat
from yasuki_core.game_pieces.cards import L5RCard


# --- Test of Might ---

TEST_OF_MIGHT_HONOR = 3


def _test_of_might_targets(game: GameState, source: L5RCard) -> list[str]:
    """Your unbowed Personalities at the battle being fought, which the card has duel the target.

    A Personality opposed at the battlefield is one performing there. Each one offered has an enemy
    there it may challenge, so the enemy the next step picks among always exists.
    """
    enemies = opposing_units_in_battle(game, source.owner)
    return [
        card_id
        for card_id in opposed_units_in_battle(game, source.owner)
        if not game.table.cards_by_id[card_id].bowed
        and any(challenge_can_be_made(game, card_id, enemy) for enemy in enemies)
    ]


def _test_of_might_effects(game: GameState, source: L5RCard, target: L5RCard) -> list[Effect]:
    """Having targeted your own duelist, pick the enemy it duels. One ability takes one target, so
    the enemy Personality is a pick of its own, and the Strategy is carried to it."""
    enemies = tuple(
        enemy
        for enemy in opposing_units_in_battle(game, source.owner)
        if challenge_can_be_made(game, target.id, enemy)
    )
    if not enemies:
        return []
    return [
        Choose(
            seat=source.owner,
            candidates=enemies,
            minimum=1,
            maximum=1,
            resolver="test_of_might_duel",
            source_id=target.id,
            resolver_context=(source.id,),
        )
    ]


@choice_resolver("test_of_might_duel", prompt="Choose the enemy Personality to duel")
def _resolve_test_of_might_duel(
    game: GameState,
    source_id: str,
    chosen: tuple[str, ...],
    seat: PlayerId,
    resolver_context: tuple[str, ...] = (),
) -> list[Effect]:
    """Pay what cards in play add to the cost of the challenge, then have both Personalities duel
    on Force, which the CR names per Personality rather than per duel, so each is told to compare
    it (CR, Duel Stat).

    ``source_id`` is the seat's own duelist, picked as the card's target, and ``resolver_context``
    carries the Strategy, which the duel records as its source.
    """
    (strategy,) = resolver_context
    challenger, challenged = source_id, chosen[0]
    return [
        *challenge_costs(game, challenger, challenged),
        *(
            GrantDuelStat(strategy, duelist, Stat.FORCE, DUEL_CONSEQUENCES)
            for duelist in (challenger, challenged)
        ),
        StartDuel(challenger, challenged, strategy),
        DelayedEffect(Evaluate("test_of_might_outcome", strategy, seat), DUEL_CONSEQUENCES),
    ]


@choice_resolver("test_of_might_outcome")
def _resolve_test_of_might_outcome(
    game: GameState, source_id: str, chosen: tuple[str, ...], seat: PlayerId
) -> list[Effect]:
    """Honor the winner's controller and bow the loser, both read once the duel is decided. A tie is
    lost by both Personalities and won by neither, so it bows both and honors nobody."""
    duel = duel_decided_by(game, source_id)
    if duel is None:
        return []
    outcome = duel.outcome
    return [
        *(GainHonor(winner, TEST_OF_MIGHT_HONOR) for winner in outcome.winners),
        *(Bow(duel.duelist_of(loser)) for loser in outcome.losers),
    ]


register_ability(
    "test_of_might",
    Ability(
        timings=(ActionTiming.BATTLE,),
        cost=no_cost,
        targets=_test_of_might_targets,
        targeting_message="your performing unbowed Personality",
        effects=_test_of_might_effects,
        located_at=(CardLocation.HAND,),
    ),
)
