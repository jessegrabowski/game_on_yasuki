from yasuki_core.engine.rules import triggers
from yasuki_core.engine.rules.abilities.model import Ability
from yasuki_core.engine.rules.abilities.registry import ability_for
from yasuki_core.engine.rules.actions import ActionTiming
from yasuki_core.engine.rules.decisions import ChooseAbilityTarget, DecisionResponse
from yasuki_core.engine.rules.legality import legal_targets
from yasuki_core.engine.rules.state import GameState
from yasuki_core.engine.rules.work import ApplyAbilityEffects, SelectAbilityTarget
from yasuki_core.game_pieces.cards import L5RCard


def activate(game: GameState, card_id: str, ability_key: str | None = None) -> None:
    """Announce an activated ability: pay its cost, then resolve its target — a single chosen card,
    or every card it hits for a ``hits_every_target`` ability. The ability is guaranteed registered
    and to have a legal target — ``legal_actions`` only offers it then.

    Resolving the target is deferred behind the cost on the stack, so a cost whose own cascade pauses
    for a decision resolves fully first — which is the CR's order, since targets are chosen in step C
    of the Action Sequence, after costs are paid in step B. Good Faith is what makes the deferral
    safe: an action may only be announced when it could find a legal target, so the candidates
    ``legal_actions`` validated are still there to hit."""
    card = game.table.cards_by_id[card_id]
    ability = ability_for(card, ability_key)
    if ActionTiming.RESPONSE in ability.timings:
        game.responded.add(card_id)
    defer_ability(game, card, ability)


def defer_ability(game: GameState, card: L5RCard, ability: Ability) -> None:
    """Stack ``ability``'s effects behind its cost, and pay the cost.

    The cost resolves first and targeting follows it (CR, Action Sequence steps B and C), and an
    ``hits_every_target`` ability hits every one it found rather than pausing to be pointed at one.
    """
    targets = tuple(legal_targets(game, card, ability))
    game.stack.append(
        ApplyAbilityEffects(card.id, targets, ability.key)
        if ability.hits_every_target
        else SelectAbilityTarget(card.id, targets, ability.key)
    )
    triggers.resolve_effects(game, ability.cost(game, card))


def apply_ability_target(
    game: GameState, request: ChooseAbilityTarget, response: DecisionResponse
) -> None:
    source = game.table.cards_by_id[request.source_card_id]
    target = game.table.cards_by_id[response.choices[0]]
    ability = ability_for(source, request.ability_key)
    game.pending = None
    triggers.resolve_effects(game, ability.effects(game, source, target))
