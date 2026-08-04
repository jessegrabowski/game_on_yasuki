from yasuki_core.engine.rules.abilities import Ability, bow_cost, register_ability
from yasuki_core.engine.rules.economy import PlayerState, gold_handler, recruit_discount
from yasuki_core.engine.rules.effects import AdjustCounter, Effect
from yasuki_core.engine.rules.state import GameState, Phase
from yasuki_core.engine.rules.triggers import sincerity_seed_targets
from yasuki_core.game_pieces.cards import L5RCard
from yasuki_core.game_pieces.counters import SINCERITY


# --- Shrine of Courtesy ---


@recruit_discount("shrine_of_courtesy")
def _shrine_of_courtesy(card: L5RCard, me: PlayerState, opponents: tuple[PlayerState, ...]) -> int:
    """Courtesy grants -3 Gold Cost while you are the second player (you did not go first)."""
    return 3 if me.went_second else 0


# --- Shrine of Sincerity ---


@gold_handler("shrine_of_sincerity")
def _shrine_of_sincerity(
    card: L5RCard, me: PlayerState, opponents: tuple[PlayerState, ...], targets: tuple[L5RCard, ...]
) -> int:
    """+1 GP when paying for a Sincerity card that still carries Sincerity tokens."""
    bonus = (
        1
        if any(
            "Sincerity" in target.keywords and target.counters.get(SINCERITY.key, 0) > 0
            for target in targets
        )
        else 0
    )
    return card.gold_production + bonus


# --- Shrine of Sincerity ---


def _sincerity_seed_targets(game: GameState, card: L5RCard) -> list[str]:
    return sincerity_seed_targets(game, card.owner)


def _seed_sincerity(source: L5RCard, target: L5RCard) -> list[Effect]:
    return [AdjustCounter(target.id, SINCERITY, 1)]


register_ability(
    "shrine_of_sincerity",
    Ability(
        phase=Phase.DYNASTY,
        label="Bow: seed a Sincerity token onto a Province Sincerity card",
        cost=bow_cost,
        targets=_sincerity_seed_targets,
        effects=_seed_sincerity,
    ),
)
