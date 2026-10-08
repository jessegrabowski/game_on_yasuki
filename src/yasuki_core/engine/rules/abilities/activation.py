from dataclasses import dataclass, replace

from yasuki_core.engine.rules import triggers
from yasuki_core.engine.rules.abilities.model import Ability
from yasuki_core.engine.rules.abilities.registry import ability_for, use_tags
from yasuki_core.engine.rules.effects import Effect
from yasuki_core.engine.rules.negation import action_provenance
from yasuki_core.engine.rules.vocabulary.game_events import GameEvent
from yasuki_core.engine.rules.vocabulary.actions import ActionTiming
from yasuki_core.engine.rules.vocabulary.decisions import (
    ChooseAbilityTarget,
    DecisionResponse,
    PickedTargets,
    answerable,
    within_reach,
)
from yasuki_core.engine.rules.legality import choosable_targets, group_targets
from yasuki_core.engine.rules.state import GameState, claim_once_per_turn, used_this_turn
from yasuki_core.engine.rules.turn.structure import RoundKind
from yasuki_core.engine.rules.vocabulary.work import Targeting
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
        _claim_first_unused_use(game, card, ability)
    defer_ability(game, card, ability, plays_card=False)


def _claim_first_unused_use(game: GameState, card: L5RCard, ability: Ability) -> None:
    """Claim the first of ``ability``'s uses this turn not yet claimed, if any is left. None is
    left only where the arc does not ration abilities, so nothing has to be claimed then."""
    tags = use_tags(game, card, ability)
    unused = next((tag for tag in tags if not used_this_turn(game, card, tag)), None)
    if unused is not None:
        claim_once_per_turn(game, card, unused)


@dataclass(frozen=True, slots=True)
class SelectAbilityTarget:
    """Raise an activated ability's next target choice once its cost has been paid. Deferred so a
    cost whose own cascade pauses for a decision resolves fully before the target is chosen.

    An ability printing several "target" phrases comes back here once for each: ``picked`` carries
    the phrases already settled, the phrase after them reads it for its candidates, and the
    ability resolves against all of them once the last one is answered.

    Attributes
    ----------
    card_id : str
        The card whose ability is resolving.
    candidates : tuple of str or None
        The ids the ability's first phrase may target, fixed before paying so the choice is never
        left empty, or None to read them now, for an ability that targets after its cost and for
        every phrase after the first. Such an ability with nothing to target does nothing more.
    ability_key : str, optional
        Names the ability among the several the card prints, so the one announced is the one
        that resolves. Default None, the card's only ability.
    picked : tuple of tuple of str, optional
        The phrases already settled, in print order. Default none, the first phrase.
    """

    card_id: str
    candidates: tuple[str, ...] | None
    ability_key: str | None = None
    picked: PickedTargets = ()

    def resume(self, game: GameState) -> None:
        source = game.table.cards_by_id[self.card_id]
        ability = ability_for(game, source, self.ability_key)
        if ability is None:
            return
        group = ability.phrases[len(self.picked)]
        limits = group.conditions(game, source, self.picked)
        candidates = self.candidates
        if candidates is None:
            candidates = tuple(choosable_targets(game, source, ability, self.picked))
        else:
            # The candidates were fixed before the cost was paid and the limits are read against
            # the board the cost left, so a cost that moved a ceiling can shut one of them out.
            candidates = within_reach(candidates, limits)
        minimum, maximum = group.wanted(game, source, self.picked, candidates)
        # Only the maximum bends to the board: a phrase cannot reach more cards than are there. The
        # minimum is what the card asks for, and a phrase with no legal answer to give targets
        # nothing rather than asking a question the seat cannot answer.
        maximum = min(maximum, len(candidates))
        if maximum == 0 or not answerable(candidates, minimum, limits):
            if not self.picked:
                # An ability that targets after its cost and found nothing does nothing more.
                return
            # A later phrase taking no card after the earlier picks targets nothing, and what the
            # card makes of that is its business. Good Faith keeps a pick from leaving one short.
            _advance(game, self.card_id, self.ability_key, (*self.picked, ()))
            return
        game.pending = ChooseAbilityTarget(
            seat=source.owner,
            candidates=candidates,
            source_card_id=self.card_id,
            ability_key=self.ability_key,
            source_name=source.name,
            targeting_message=group.targeting_message,
            minimum=minimum,
            maximum=maximum,
            limits=limits,
            settled=self.picked,
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
        _hit_every_target(game, self.card_id, (self.target_ids,), self.ability_key)


def defer_ability(game: GameState, card: L5RCard, ability: Ability, *, plays_card: bool) -> None:
    """Stack ``ability``'s effects behind its cost, and pay the cost.

    The cost resolves first and targeting follows it (CR, Action Sequence steps B and C), and an
    ``hits_every_target`` ability hits every one it found rather than pausing to be pointed at one.
    ``plays_card`` says whether taking the ability plays ``card``, as a Strategy from hand is
    played, whose Gold Cost has then already taken its share of the action's discount.
    """
    if ability.targets_after_cost:
        game.stack.append(SelectAbilityTarget(card.id, None, ability.key))
    else:
        targets = tuple(choosable_targets(game, card, ability))
        game.stack.append(
            ApplyAbilityEffects(card.id, targets, ability.key)
            if ability.hits_every_target
            else SelectAbilityTarget(card.id, targets, ability.key)
        )
    triggers.pay_costs(game, ability.discounted_cost(game, card, plays_card=plays_card))


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

    def is_negatable(self, game: GameState) -> bool:
        """False: targeting is no effect (CR, Action Sequence step C), so the action still targets
        what it targeted, and only the ability's effects behind it are negated as they commit."""
        return False

    def follow_on(self, game: GameState) -> tuple[Effect, ...]:
        return self.effects if self.effects is not None else self._build(game)

    def built(self, game: GameState) -> "ResolveAbility":
        """This targeting with the ability's effects built against its target on the board as it
        stands."""
        return replace(self, effects=self._build(game))

    def _build(self, game: GameState) -> tuple[Effect, ...]:
        source = game.table.cards_by_id[self.card_id]
        ability = ability_for(game, source, self.ability_key)
        target = game.table.cards_by_id[self.target_id]
        return tuple(ability.effects_against(game, source, ((target,),)))


def apply_ability_target(
    game: GameState, request: ChooseAbilityTarget, response: DecisionResponse
) -> None:
    """Take the targets the seat chose for this "target" phrase, and either ask the next phrase or
    resolve the ability against all of them."""
    _advance(
        game,
        request.source_card_id,
        request.ability_key,
        (*request.settled, response.choices),
    )


def _advance(
    game: GameState,
    card_id: str,
    ability_key: str | None,
    picked: PickedTargets,
) -> None:
    """Ask the ability's next "target" phrase, or resolve it once every phrase has one.

    The next phrase goes on the work stack rather than asking from here, so the answer that
    settled this one finishes resolving first (CR 20F, Timing).
    """
    source = game.table.cards_by_id[card_id]
    ability = ability_for(game, source, ability_key)
    if ability is not None and len(picked) < len(ability.phrases):
        game.stack.append(SelectAbilityTarget(card_id, None, ability_key, picked))
        return
    if ability is not None and len(picked) == 1 and len(picked[0]) == 1:
        # One card targeted by one phrase, however that phrase was declared: held at the Interrupt
        # step as the action's targeting, so an Interrupt may read it and substitute for it (CR,
        # Substitution and Targets).
        held = ResolveAbility(card_id, picked[0][0], ability_key)
        targeting = Targeting(card_id, ability_key, picked)
        _resolve(game, source, ability, [held.built(game)], targeting)
        return
    _hit_every_target(game, card_id, picked, ability_key)


def _hit_every_target(
    game: GameState,
    card_id: str,
    picked: PickedTargets,
    ability_key: str | None,
) -> None:
    """Record every phrase's targets as the action's and resolve the ability's effects against all
    of them."""
    source = game.table.cards_by_id[card_id]
    ability = ability_for(game, source, ability_key)
    _record_targets(game, tuple(card_id for group in picked for card_id in group))
    by_id = game.table.cards_by_id
    groups = tuple(tuple(by_id[target_id] for target_id in group) for group in picked)
    effects = ability.effects_against(game, source, groups) if ability is not None else []
    # An ability that hits every card it names takes no target, so it has no targeting to check.
    targeting = None
    if ability is not None and not ability.hits_every_target:
        targeting = Targeting(card_id, ability_key, picked)
    _resolve(game, source, ability, effects, targeting)


def _resolve(
    game: GameState,
    source: L5RCard,
    ability: Ability | None,
    effects: list[Effect],
    targeting: Targeting | None = None,
) -> None:
    """Hand ``effects`` over as the action's own, or as a trait's when ``ability`` is one. The
    action is from ``source`` unless the ability is the rulebook's. ``targeting`` is what the action
    targeted, if anything."""
    if ability is not None and ability.trait:
        triggers.resolve_effects(game, effects)
        return
    acting = source.id if ability is not None and ability.acts_from_its_card else None
    provenance = action_provenance(game, acting)
    triggers.resolve_action_effects(game, effects, provenance=provenance, targeting=targeting)


def lapsed_targets(
    game: GameState, targeting: Targeting, effects: tuple[Effect, ...]
) -> frozenset[str]:
    """The cards ``targeting`` names that are no longer legal targets for their phrase as the
    action's resolution begins (CR, Action Sequence step E). A targeting an Interrupt substituted
    is read as it now stands among ``effects``, the action's held effects."""
    source = game.table.cards_by_id.get(targeting.card_id)
    ability = None if source is None else ability_for(game, source, targeting.ability_key)
    if source is None or ability is None:
        return frozenset()
    picked = targeting.picked
    held = next((effect for effect in effects if isinstance(effect, ResolveAbility)), None)
    if held is not None:
        picked = ((triggers.as_modified(game, held).target_id,),)
    lapsed: set[str] = set()
    for index, group in enumerate(picked):
        offered = set(group_targets(game, source, ability, ability.phrases[index], picked[:index]))
        lapsed.update(target for target in group if target not in offered)
    return frozenset(lapsed)


def _record_targets(game: GameState, target_ids: tuple[str, ...]) -> None:
    """Add ``target_ids`` to the resolving action's record, unless the ability is a Response: the
    record then belongs to the action being responded to, which every responder reads."""
    if game.round.kind is not RoundKind.RESPONSE:
        game.action_targets += target_ids
