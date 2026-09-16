from yasuki_core.engine.rules.abilities.costs import no_cost
from yasuki_core.engine.rules.abilities.model import Ability, CardLocation
from yasuki_core.engine.rules.abilities.registry import register_ability
from yasuki_core.engine.rules.effects import Effect, GrantConditionalModifier, SpendSeatOncePerTurn
from yasuki_core.engine.rules.state import GameState, seat_once_key
from yasuki_core.engine.rules.vocabulary.actions import ActionTiming
from yasuki_core.engine.rules.vocabulary.modifiers import Condition, Duration, Stat
from yasuki_core.game_pieces.cards import L5RCard


# --- Flashy Technique ---

FLASHY_TECHNIQUE = "flashy_technique"
FLASHY_TECHNIQUE_PENALTY = -1


def _flashy_technique_targets(game: GameState, source: L5RCard) -> list[str]:
    """Itself, unless its controller has played another Flashy Technique this turn. The Focus
    Effect only applies inside a duel and none is fought yet."""
    played = game.has_used(seat_once_key(source.owner, FLASHY_TECHNIQUE, game.turn))
    return [] if played else [source.id]


def _flashy_technique_effects(game: GameState, source: L5RCard, target: L5RCard) -> list[Effect]:
    return [
        SpendSeatOncePerTurn(source.owner, FLASHY_TECHNIQUE),
        GrantConditionalModifier(
            source.id,
            Condition.ATTACKING,
            Stat.FORCE,
            FLASHY_TECHNIQUE_PENALTY,
            Duration.UNTIL_END_OF_TURN,
        ),
    ]


register_ability(
    "flashy_technique",
    Ability(
        timings=(ActionTiming.OPEN,),
        label="Open: Personalities have -1F while attacking this turn",
        cost=no_cost,
        targets=_flashy_technique_targets,
        effects=_flashy_technique_effects,
        located_at=(CardLocation.HAND,),
        hits_every_target=True,
    ),
)
