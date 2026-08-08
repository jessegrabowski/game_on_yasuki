from yasuki_core.engine.rules.abilities import InvestAbility, one_wealth, register_invest
from yasuki_core.engine.rules.effects import AdjustCounter, Choose, Effect
from yasuki_core.engine.rules.events import EnteredPlay
from yasuki_core.engine.rules.state import GameState
from yasuki_core.engine.rules.triggers import (
    TriggerContext,
    choice_resolver,
    on,
    sincerity_seed_targets,
)
from yasuki_core.game_pieces.counters import SINCERITY


# --- Training Court ---


@on(EnteredPlay, "training_court")
def _training_court(ctx: TriggerContext) -> list[Effect]:
    """Political Tireless Response: after Training Court enters play, seed a Sincerity token onto one
    of its controller's token-less Sincerity cards still in a Province."""
    if ctx.event.card_id != ctx.card.id:
        return []
    targets = tuple(sincerity_seed_targets(ctx.game, ctx.card.owner))
    if not targets:
        return []
    return [Choose(ctx.card.owner, targets, 1, 1, "sincerity_seed", ctx.card.id)]


@choice_resolver("sincerity_seed", prompt="Seed a Sincerity token onto one of your Sincerity cards")
def _sincerity_seed(game: GameState, source_id: str, chosen: tuple[str, ...]) -> list[Effect]:
    return [AdjustCounter(card_id, SINCERITY, 1) for card_id in chosen]


register_invest("training_court", InvestAbility(minimum=1, maximum=1, effect=one_wealth))
