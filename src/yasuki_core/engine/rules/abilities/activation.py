from dataclasses import dataclass

from yasuki_core.engine.rules import triggers
from yasuki_core.engine.rules.abilities.model import Ability, once_tag
from yasuki_core.engine.rules.abilities.registry import ability_for
from yasuki_core.engine.rules.vocabulary.actions import ActionTiming
from yasuki_core.engine.rules.vocabulary.decisions import ChooseAbilityTarget, DecisionResponse
from yasuki_core.engine.rules.legality import legal_targets
from yasuki_core.engine.rules.state import GameState, claim_once_per_turn
from yasuki_core.engine.rules.turn.structure import RoundKind
from yasuki_core.game_pieces.cards import L5RCard


def activate(game: GameState, card_id: str, ability_key: str | None = None) -> None:
    """Announce an activated ability: pay its cost, then resolve its target, a single chosen card
    or every card it hits for a ``hits_every_target`` ability. The ability is guaranteed
    registered and to have a legal target. ``legal_actions`` only offers it then.

    Resolving the target is deferred behind the cost on the stack, so a cost whose own cascade
    pauses for a decision resolves fully first: the CR's order, since targets are chosen in step
    C of the Action Sequence, after costs are paid in step B. Good Faith is what makes the
    deferral safe: an action may only be announced when it could find a legal target, so the
    candidates ``legal_actions`` validated are still there to hit."""
    card = game.table.cards_by_id[card_id]
    ability = ability_for(card, ability_key)
    if ActionTiming.RESPONSE in ability.timings:
        game.responded.add(card_id)
    if not ability.repeatable:
        claim_once_per_turn(game, card, once_tag(ability))
    defer_ability(game, card, ability)


@dataclass(frozen=True, slots=True)
class SelectAbilityTarget:
    """Raise an activated ability's target choice once its cost has been paid. Deferred so a cost
    whose own cascade pauses for a decision resolves fully before the target is chosen.

    Attributes
    ----------
    card_id : str
        The card whose ability is resolving.
    candidates : tuple of str
        The ids the ability may target, fixed before paying so the choice is never left empty.
    ability_key : str, optional
        Names the ability among the several the card prints, so the one announced is the one
        that resolves. Default None, the card's only ability.
    """

    card_id: str
    candidates: tuple[str, ...]
    ability_key: str | None = None

    def resume(self, game: GameState) -> None:
        owner = game.table.cards_by_id[self.card_id].owner
        game.pending = ChooseAbilityTarget(
            seat=owner,
            candidates=self.candidates,
            source_card_id=self.card_id,
            ability_key=self.ability_key,
        )


@dataclass(frozen=True, slots=True)
class ApplyAbilityEffects:
    """Resolve an untargeted ability's effects against every card it hits, once its cost has been
    paid. The all-target counterpart of :class:`~.SelectAbilityTarget`, deferred for the same
    reason.

    Attributes
    ----------
    card_id : str
        The card whose ability is resolving.
    target_ids : tuple of str
        The cards the ability affects, fixed before paying.
    ability_key : str, optional
        Names the ability among the several the card prints, so the one announced is the one
        that resolves. Default None, the card's only ability.
    """

    card_id: str
    target_ids: tuple[str, ...]
    ability_key: str | None = None

    def resume(self, game: GameState) -> None:
        source = game.table.cards_by_id[self.card_id]
        ability = ability_for(source, self.ability_key)
        _record_targets(game, self.target_ids)
        effects = [
            effect
            for target_id in self.target_ids
            for effect in ability.effects(game, source, game.table.cards_by_id[target_id])
        ]
        triggers.resolve_effects(game, effects)


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
    _record_targets(game, (target.id,))
    triggers.resolve_effects(game, ability.effects(game, source, target))


def _record_targets(game: GameState, target_ids: tuple[str, ...]) -> None:
    """Add ``target_ids`` to the resolving action's record, unless the ability is a Response: the
    record then belongs to the action being responded to, which every responder reads."""
    if game.round.kind is not RoundKind.RESPONSE:
        game.action_targets += target_ids
