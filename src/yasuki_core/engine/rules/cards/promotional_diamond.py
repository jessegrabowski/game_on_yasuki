from yasuki_core.engine.players import PlayerId
from yasuki_core.engine.rules.abilities import (
    Ability,
    no_cost,
    owned_personalities,
    register_ability,
)
from yasuki_core.engine.rules.actions import ActionTiming
from yasuki_core.engine.rules.economy import effective_chi
from yasuki_core.engine.rules.effects import (
    AskDistribution,
    CreateToken,
    Destroy,
    Effect,
    GainHonor,
)
from yasuki_core.engine.rules.equip import creation_targets
from yasuki_core.engine.rules.state import GameState
from yasuki_core.engine.rules.triggers import choice_resolver
from yasuki_core.game_pieces.cards import L5RCard


# --- Suiteiru no Oni ---

SUITEIRUS_PODLING = "suiteirus_podling"


def _suiteiru_no_oni_targets(game: GameState, source: L5RCard) -> list[str]:
    """His own controller's unbowed Personalities, himself among them."""
    return [
        personality.id
        for personality in owned_personalities(game, source.owner)
        if not personality.bowed
    ]


def _suiteiru_no_oni_effects(game: GameState, source: L5RCard, target: L5RCard) -> list[Effect]:
    """Destroy the target, then divide a Podling per point of his Chi among the Personalities left.

    The bearers are read before the target is destroyed but exclude him, since he is on his way out
    and cannot carry what his own death creates. A target with no Chi, or a board where he was the
    last Personality, leaves nothing to divide and nothing to ask.
    """
    podlings = effective_chi(game, target)
    printed = game.table.creatable_tokens[SUITEIRUS_PODLING]
    bearers = tuple(
        personality.id
        for personality in creation_targets(game, source.owner, printed)
        if personality.id != target.id
    )
    destroy = Destroy(target.id, source.owner)
    if not podlings or not bearers:
        return [destroy]
    return [
        destroy,
        AskDistribution(source.owner, bearers, podlings, "suiteiru_no_oni", source.id),
    ]


@choice_resolver(
    "suiteiru_no_oni", prompt="Attach the Oni Followers to one or more of your Personalities"
)
def _resolve_suiteiru_no_oni(
    game: GameState, source_id: str, chosen: tuple[str, ...], seat: PlayerId
) -> list[Effect]:
    """Create one Podling per name in ``chosen``, so a Personality named twice carries two, and pay
    for the lot in Honor."""
    return [
        *(CreateToken(SUITEIRUS_PODLING, seat, source_id, attach_to=bearer) for bearer in chosen),
        GainHonor(seat, -len(chosen)),
    ]


register_ability(
    "suiteiru_no_oni",
    Ability(
        timings=(ActionTiming.OPEN,),
        label="Open: Destroy your unbowed Personality to create Oni Followers equal to his Chi",
        cost=no_cost,
        targets=_suiteiru_no_oni_targets,
        effects=_suiteiru_no_oni_effects,
    ),
)
