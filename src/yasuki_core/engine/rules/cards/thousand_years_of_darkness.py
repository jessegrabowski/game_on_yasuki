from yasuki_core.engine.players import PlayerId, Trait
from yasuki_core.engine.rules.abilities.costs import bow_cost, no_cost
from yasuki_core.engine.rules.abilities.model import Ability
from yasuki_core.engine.rules.abilities.registry import register_ability
from yasuki_core.engine.rules.board.queries import ATTACK_TARGET, attack_targets, attack_targets_at
from yasuki_core.engine.rules.vocabulary.actions import ActionTiming
from yasuki_core.engine.rules.effects import Choose, Destroy, Effect, Fear, GainHonor, RangedAttack
from yasuki_core.engine.rules.vocabulary.game_events import Destroyed, EnteredPlay
from yasuki_core.engine.rules.state import GameState
from yasuki_core.engine.rules.triggers import TriggerContext, choice_resolver, on
from yasuki_core.game_pieces.cards import L5RCard


# --- Ashura ---

ASHURA_HONOR_LOSS = 5
ASHURA_FEAR = 4


@on(EnteredPlay, "ashura")
def _ashura_entered_play(ctx: TriggerContext) -> list[Effect]:
    if ctx.event.card_id != ctx.card.id:
        return []
    return [GainHonor(ctx.card.owner, -ASHURA_HONOR_LOSS, source_id=ctx.card.id)]


@on(Destroyed, "ashura")
def _ashura_destroyed(ctx: TriggerContext) -> list[Effect]:
    """After Ashura is destroyed while at a battlefield, target and destroy a Follower, or
    Personality without Followers, at that battlefield. Either army's, since the text names the
    battlefield and not a side. He is in his discard by now, so where he stood is the event's."""
    battlefield = None if ctx.event.location is None else ctx.event.location.battlefield
    if ctx.event.card_id != ctx.card.id or battlefield is None:
        return []
    targets = [
        target
        for seat in ctx.game.table.seats
        for target in attack_targets_at(ctx.game, battlefield, seat)
    ]
    if not targets:
        return []
    return [Choose(ctx.card.owner, tuple(targets), 1, 1, "ashura", ctx.card.id)]


@choice_resolver(
    "ashura", prompt="Destroy a Follower, or Personality without Followers, at that battlefield"
)
def _resolve_ashura(
    game: GameState, source_id: str, chosen: tuple[str, ...], seat: PlayerId
) -> list[Effect]:
    return [Destroy(chosen[0], Trait(source_id))]


def _ashura_effects(game: GameState, source: L5RCard, target: L5RCard) -> list[Effect]:
    return [Fear(ASHURA_FEAR, target.id, source.owner)]


register_ability(
    "ashura",
    Ability(
        timings=(ActionTiming.BATTLE,),
        cost=no_cost,
        targets=attack_targets,
        targeting_message=ATTACK_TARGET,
        effects=_ashura_effects,
    ),
)


# --- Tosekiki ---

TOSEKIKI_HONOR_LOSS = 3
TOSEKIKI_RANGED = 4


@on(EnteredPlay, "tosekiki")
def _tosekiki_entered_play(ctx: TriggerContext) -> list[Effect]:
    """After this Follower enters play, lose 3 Honor."""
    if ctx.event.card_id != ctx.card.id:
        return []
    return [GainHonor(ctx.card.owner, -TOSEKIKI_HONOR_LOSS, source_id=ctx.card.id)]


def _tosekiki_effects(game: GameState, source: L5RCard, target: L5RCard) -> list[Effect]:
    return [RangedAttack(TOSEKIKI_RANGED, target.id, source.owner)]


register_ability(
    "tosekiki",
    Ability(
        timings=(ActionTiming.BATTLE,),
        repeatable=True,
        cost=bow_cost,
        targets=attack_targets,
        targeting_message=ATTACK_TARGET,
        effects=_tosekiki_effects,
    ),
)
