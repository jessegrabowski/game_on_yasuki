from yasuki_core.engine.players import PlayerId
from yasuki_core.engine.rules.abilities.costs import no_cost
from yasuki_core.engine.rules.abilities.model import Ability, CardLocation
from yasuki_core.engine.rules.abilities.idioms import register_terrain
from yasuki_core.engine.rules.abilities.registry import register_ability
from yasuki_core.engine.rules.board.queries import units_at
from yasuki_core.engine.rules.effects import Effect, ExemptFromResolutionBow
from yasuki_core.engine.rules.gold.production import gold_handler
from yasuki_core.engine.rules.state import GameState
from yasuki_core.engine.rules.stats.stat_grants import stat_grant
from yasuki_core.engine.rules.vocabulary import keywords
from yasuki_core.engine.rules.vocabulary.actions import ActionTiming
from yasuki_core.engine.rules.vocabulary.modifiers import Stat
from yasuki_core.engine.rules.vocabulary.segments import BattleSegment
from yasuki_core.engine.table import location_of
from yasuki_core.game_pieces.cards import L5RCard
from yasuki_core.game_pieces.prints import PersonalityPrint


# --- Contentious Terrain ---

CONTENTIOUS_TERRAIN_FORCE = 1


@stat_grant("contentious_terrain")
def _contentious_terrain_stat_grant(
    game: GameState, source: L5RCard, card: L5RCard, stat: Stat
) -> int:
    """ "Your Personalities at this battlefield have +1F." """
    if stat is not Stat.FORCE or card.owner is not source.owner:
        return 0
    if not isinstance(card.printed, PersonalityPrint):
        return 0
    battlefield = location_of(game.table, source).battlefield
    if battlefield is None or location_of(game.table, card).battlefield != battlefield:
        return 0
    return CONTENTIOUS_TERRAIN_FORCE


register_terrain("contentious_terrain")


# --- Jade Works ---


@gold_handler("jade_works")
def _jade_works_gold(
    card: L5RCard, game: GameState, seat: PlayerId, targets: tuple[L5RCard, ...]
) -> int:
    """+2 GP when paying for a Jade card."""
    bonus = 2 if any(keywords.JADE in target.keywords for target in targets) else 0
    return card.gold_production + bonus


# --- Rallying Cry ---


def _rallying_cry_targets(game: GameState, source: L5RCard) -> list[str]:
    """Itself, in the Response Step after a battle's Resolution Segment, while its player has a
    unit at the current battlefield for the resolution to bow."""
    attack = game.attack
    if attack is None or attack.current is None:
        return []
    resolving = attack.battle_segment is BattleSegment.RESOLUTION
    return [source.id] if resolving and units_at(game, attack.current, source.owner) else []


def _rallying_cry_effects(game: GameState, source: L5RCard, target: L5RCard) -> list[Effect]:
    """ "This battle's resolution does not bow your units at the current battlefield." """
    attack = game.attack
    assert attack is not None and attack.current is not None
    return [ExemptFromResolutionBow(source.owner, attack.current)]


register_ability(
    "rallying_cry",
    Ability(
        timings=(ActionTiming.RESPONSE,),
        located_at=(CardLocation.HAND,),
        cost=no_cost,
        targets=_rallying_cry_targets,
        effects=_rallying_cry_effects,
        hits_every_target=True,
    ),
)
