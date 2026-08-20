from yasuki_core.engine.rules.abilities import Ability, bow_cost, register_ability
from yasuki_core.engine.rules.economy import (
    PlayerState,
    gold_handler,
    keyword_grant,
    recruit_discount,
)
from yasuki_core.engine.rules.effects import AdjustCounter, CreateToken, Effect
from yasuki_core.engine.rules.events import EnteredPlay
from yasuki_core.engine.rules.actions import ActionTiming
from yasuki_core.engine.rules.state import GameState
from yasuki_core.engine.rules.triggers import TriggerContext, on, sincerity_seed_targets
from yasuki_core.game_pieces import keywords
from yasuki_core.game_pieces.cards import L5RCard
from yasuki_core.game_pieces.counters import SINCERITY


# --- Sasada, Pearl Champion (Experienced) ---

SASADAS_OROCHI = "orochi_follower_2f"


@on(EnteredPlay, "sasada_pearl_champion_experienced")
def _sasada_calls_her_orochi(ctx: TriggerContext) -> list[Effect]:
    """After Sasada enters play, create and attach a 2F Orochi Follower to her."""
    if ctx.event.card_id != ctx.card.id:
        return []
    return [CreateToken(SASADAS_OROCHI, ctx.card.owner, ctx.card.id, attach_to=ctx.card.id)]


# --- Shrine of Courtesy ---


@recruit_discount("shrine_of_courtesy")
def _shrine_of_courtesy(card: L5RCard, me: PlayerState, opponents: tuple[PlayerState, ...]) -> int:
    """Courtesy grants -3 Gold Cost while you are the second player (you did not go first)."""
    return 3 if me.went_second else 0


@keyword_grant("shrine_of_courtesy")
def _shrine_of_courtesy_keywords(
    card: L5RCard, me: PlayerState, opponents: tuple[PlayerState, ...]
) -> tuple[str, ...]:
    """The same Courtesy clause grants Legacy, so a second player can search this Holding out."""
    return (keywords.LEGACY,) if me.went_second else ()


# --- Shrine of Sincerity ---


@gold_handler("shrine_of_sincerity")
def _shrine_of_sincerity(
    card: L5RCard, me: PlayerState, opponents: tuple[PlayerState, ...], targets: tuple[L5RCard, ...]
) -> int:
    """+1 GP when paying for a Sincerity card that still carries Sincerity tokens."""
    bonus = (
        1
        if any(
            keywords.SINCERITY in target.keywords and target.counters.get(SINCERITY.key, 0) > 0
            for target in targets
        )
        else 0
    )
    return card.gold_production + bonus


def _sincerity_seed_targets(game: GameState, card: L5RCard) -> list[str]:
    return sincerity_seed_targets(game, card.owner)


def _seed_sincerity(game: GameState, source: L5RCard, target: L5RCard) -> list[Effect]:
    return [AdjustCounter(target.id, SINCERITY, 1)]


register_ability(
    "shrine_of_sincerity",
    Ability(
        timing=ActionTiming.DYNASTY,
        label="Bow: seed a Sincerity token onto a Province Sincerity card",
        cost=bow_cost,
        targets=_sincerity_seed_targets,
        effects=_seed_sincerity,
    ),
)
