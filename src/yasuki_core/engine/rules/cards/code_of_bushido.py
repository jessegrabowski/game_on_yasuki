from yasuki_core.engine.players import PlayerId
from yasuki_core.engine.rules.effects import Choose, CreateToken, Effect
from yasuki_core.engine.rules.equip import creation_targets
from yasuki_core.engine.rules.events import EnteredPlay
from yasuki_core.engine.rules.state import GameState
from yasuki_core.engine.rules.triggers import TriggerContext, choice_resolver, on


# --- Ichiro Yojimbo ---

MEDIUM_FOLLOWER = "medium_follower"


@on(EnteredPlay, "ichiro_yojimbo")
def _ichiro_yojimbo_entered_play(ctx: TriggerContext) -> list[Effect]:
    """After this Follower enters play, create another and attach it to a Personality.

    Which Personality is a real choice: the second Follower need not join the one Ichiro himself
    hangs on.
    """
    if ctx.event.card_id != ctx.card.id:
        return []
    follower = ctx.game.table.creatable_tokens[MEDIUM_FOLLOWER]
    targets = tuple(target.id for target in creation_targets(ctx.game, ctx.card.owner, follower))
    if not targets:
        return []
    return [Choose(ctx.card.owner, targets, 1, 1, "ichiro_yojimbo", ctx.card.id)]


@choice_resolver(
    "ichiro_yojimbo", prompt="Attach the created Follower to one of your Personalities"
)
def _resolve_ichiro_yojimbo(
    game: GameState, source_id: str, chosen: tuple[str, ...], seat: PlayerId
) -> list[Effect]:
    return [CreateToken(MEDIUM_FOLLOWER, seat, source_id, attach_to=chosen[0])]
