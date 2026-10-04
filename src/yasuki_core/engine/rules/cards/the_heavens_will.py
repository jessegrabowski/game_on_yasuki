from yasuki_core.engine.rules.abilities.costs import no_cost
from yasuki_core.engine.rules.abilities.model import Ability, CardLocation
from yasuki_core.engine.rules.abilities.registry import register_ability
from yasuki_core.engine.rules.board.queries import opposed_units_in_battle
from yasuki_core.engine.rules.duel.focus_effects import focus_effect
from yasuki_core.engine.rules.effects import Bow, DrawCard, Effect, GainHonor, Move
from yasuki_core.engine.rules.state import GameState
from yasuki_core.engine.rules.vocabulary.actions import ActionTiming
from yasuki_core.engine.table import Location
from yasuki_core.game_pieces.cards import L5RCard


# --- Discretionary Valor ---

VALOR_HONOR = 1


@focus_effect("discretionary_valor")
def _discretionary_valor_focus_effect(game: GameState, card: L5RCard) -> list[Effect]:
    """ "As a Focus Effect, bow the other Personality."

    Read off the duel on the game rather than the one being fought, because a Focus Effect outlives
    a duel another Focus Effect ended.
    """
    duel = game.duel
    if duel is None or card.owner not in (duel.challenger, duel.challenged):
        return []
    return [Bow(duel.duelist_of(duel.opponent_of(card.owner)))]


def _discretionary_valor_targets(game: GameState, source: L5RCard) -> list[str]:
    """Your Personalities opposed at the battle. The Focus Effect, bowing the other Personality,
    only applies inside a duel and none is fought yet."""
    return list(opposed_units_in_battle(game, source.owner))


def _discretionary_valor_effects(game: GameState, source: L5RCard, target: L5RCard) -> list[Effect]:
    return [
        Move(target.id, Location.home(target.owner)),
        GainHonor(source.owner, VALOR_HONOR),
        DrawCard(source.owner),
    ]


register_ability(
    "discretionary_valor",
    Ability(
        timings=(ActionTiming.BATTLE,),
        cost=no_cost,
        targets=_discretionary_valor_targets,
        targeting_message="your opposed Personality",
        effects=_discretionary_valor_effects,
        located_at=(CardLocation.HAND,),
    ),
)
