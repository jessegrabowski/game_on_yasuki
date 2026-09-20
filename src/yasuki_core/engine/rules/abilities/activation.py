from dataclasses import dataclass, replace

from yasuki_core.engine.rules import triggers
from yasuki_core.engine.rules.abilities.model import Ability, once_tag
from yasuki_core.engine.rules.abilities.registry import ability_for
from yasuki_core.engine.rules.effects import Effect
from yasuki_core.engine.rules.vocabulary.game_events import GameEvent
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
    ability = ability_for(game, card, ability_key)
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
        ability = ability_for(game, source, self.ability_key)
        _record_targets(game, self.target_ids)
        effects = [
            effect
            for target_id in self.target_ids
            for effect in ability.effects(game, source, game.table.cards_by_id[target_id])
        ]
        triggers.resolve_action_effects(game, effects)


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


@dataclass(frozen=True, slots=True)
class ResolveAbility(Effect):
    """An ability about to resolve against the target its seat chose: the action's targeting, held
    at the Interrupt step ahead of everything the ability does (CR, Action Sequence step D).

    Performing it records the target as the action's and hands the ability's effects against
    that target on as its follow-on. The effects are built once, as the target is chosen, so what
    the Interrupt window forecasts is what resolves and an Interrupt bound to one of them finds
    it. An Interrupt that substitutes targeting replaces this effect with one naming the new
    target and no built effects, so the ability is built afresh against that target.

    Attributes
    ----------
    card_id : str
        The card whose ability is resolving.
    target_id : str
        The card the ability targets.
    ability_key : str, optional
        Names the ability among the several the card prints. Default None, the card's only
        ability.
    effects : tuple of Effect, optional
        The ability's effects against the target, built as the target was chosen. Default None,
        built when first read.
    """

    card_id: str
    target_id: str
    ability_key: str | None = None
    effects: tuple[Effect, ...] | None = None

    def describe(self) -> str:
        return f"{self.card_id} targets {self.target_id}"

    def narrate(self, game: GameState) -> str:
        by_id = game.table.cards_by_id
        return f"{by_id[self.card_id].name} targets {by_id[self.target_id].name}"

    def perform(self, game: GameState) -> list[GameEvent]:
        _record_targets(game, (self.target_id,))
        return []

    def follow_on(self, game: GameState) -> tuple[Effect, ...]:
        return self.effects if self.effects is not None else self._build(game)

    def built(self, game: GameState) -> "ResolveAbility":
        """This targeting with the ability's effects built against its target on the board as it
        stands."""
        return replace(self, effects=self._build(game))

    def _build(self, game: GameState) -> tuple[Effect, ...]:
        source = game.table.cards_by_id[self.card_id]
        ability = ability_for(game, source, self.ability_key)
        return tuple(ability.effects(game, source, game.table.cards_by_id[self.target_id]))


def apply_ability_target(
    game: GameState, request: ChooseAbilityTarget, response: DecisionResponse
) -> None:
    targeting = ResolveAbility(request.source_card_id, response.choices[0], request.ability_key)
    triggers.resolve_action_effects(game, [targeting.built(game)])


def _record_targets(game: GameState, target_ids: tuple[str, ...]) -> None:
    """Add ``target_ids`` to the resolving action's record, unless the ability is a Response: the
    record then belongs to the action being responded to, which every responder reads."""
    if game.round.kind is not RoundKind.RESPONSE:
        game.action_targets += target_ids
