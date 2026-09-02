from yasuki_core.engine.rules.abilities import (
    Ability,
    attack_targets,
    bow_cost,
    register_ability,
)
from yasuki_core.engine.rules.actions import ActionTiming
from yasuki_core.engine.rules.effects import (
    Ask,
    DelayedEffect,
    DrawCard,
    Effect,
    RangedAttack,
)
from yasuki_core.engine.rules.events import EnteredPlay
from yasuki_core.engine.players import PlayerId
from yasuki_core.engine.rules.state import END_OF_TURN, GameState
from yasuki_core.engine.rules.triggers import TriggerContext, choice_resolver, on
from yasuki_core.game_pieces.cards import L5RCard


# --- Ashigaru Spearmen ---

SPEARMEN_RANGED = 1


@on(EnteredPlay, "ashigaru_spearmen")
def _ashigaru_spearmen_entered_play(ctx: TriggerContext) -> list[Effect]:
    """After this Follower enters play from your hand, offer the extra card the turn's end draws.

    Equipping from hand is the only arrival the card names, so one attached by an effect from
    anywhere else offers nothing.
    """
    if ctx.event.card_id != ctx.card.id or not ctx.event.from_hand:
        return []
    return [
        Ask(
            ctx.card.owner,
            "Draw an additional card when this turn ends?",
            "ashigaru_spearmen",
            subjects=(ctx.card.id,),
            source_id=ctx.card.id,
        )
    ]


@choice_resolver("ashigaru_spearmen")
def _resolve_ashigaru_spearmen(
    game: GameState, source_id: str, chosen: tuple[str, ...], seat: PlayerId
) -> list[Effect]:
    """The draw waits for the end of the turn rather than happening now, so a Spearmen that leaves
    play in between still draws — the card ties the draw to the turn ending, not to itself."""
    if not chosen:
        return []
    return [DelayedEffect(DrawCard(seat), END_OF_TURN)]


def _ashigaru_spearmen_effects(game: GameState, source: L5RCard, target: L5RCard) -> list[Effect]:
    return [RangedAttack(SPEARMEN_RANGED, target.id, source.owner)]


register_ability(
    "ashigaru_spearmen",
    Ability(
        timings=(ActionTiming.BATTLE,),
        label=f"Battle, Bow: Ranged {SPEARMEN_RANGED} Attack",
        cost=bow_cost,
        targets=attack_targets,
        effects=_ashigaru_spearmen_effects,
    ),
)
