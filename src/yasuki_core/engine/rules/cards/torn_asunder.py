from yasuki_core.engine.rules.effects import CreateToken, Effect
from yasuki_core.engine.rules.events import Destroyed
from yasuki_core.engine.rules.legality import seat_alignment_name
from yasuki_core.engine.rules.triggers import TriggerContext, on


# --- Goju Kaxt ---

KAXT = "kaxt"


@on(Destroyed, "goju_kaxt")
def _goju_kaxt_destroyed(ctx: TriggerContext) -> list[Effect]:
    """After this Follower is destroyed, a 4F/3C/0PH Ninja of his controller's Clan Alignment takes
    his place — the Follower announces his own death from the discard pile."""
    if ctx.event.card_id != ctx.card.id:
        return []
    seat = ctx.card.owner
    return [CreateToken(KAXT, seat, ctx.card.id, clan=seat_alignment_name(ctx.game, seat))]
