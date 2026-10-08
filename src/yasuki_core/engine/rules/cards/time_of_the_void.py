from yasuki_core.engine.players import PlayerId
from yasuki_core.engine.rules.abilities.idioms import register_event_entry
from yasuki_core.engine.rules.effects import Ask, DrawCard, Effect
from yasuki_core.engine.rules.board.queries import equipped_from_hand_since_last_turn
from yasuki_core.engine.rules.state import GameState
from yasuki_core.engine.rules.triggers import TriggerContext, choice_resolver, on
from yasuki_core.engine.rules.units.composition import is_follower
from yasuki_core.engine.rules.vocabulary.game_events import TurnBoundary
from yasuki_core.engine.rules.vocabulary.segments import Boundary


# --- Enlistment ---

register_event_entry("enlistment")


@on(TurnBoundary, "enlistment", boundary=Boundary.END)
def _enlistment_turn_boundary(ctx: TriggerContext) -> list[Effect]:
    """ "Each player may draw an additional card before his turn ends if he Equipped any Followers
    from his hand since his last turn ended." """
    seat = ctx.event.seat
    if not any(map(is_follower, equipped_from_hand_since_last_turn(ctx.game, seat))):
        return []
    question = "Draw an additional card for Enlistment?"
    return [Ask(seat, question, "enlistment", subjects=(ctx.card.id,), source_id=ctx.card.id)]


@choice_resolver("enlistment")
def _resolve_enlistment(
    game: GameState, source_id: str, chosen: tuple[str, ...], seat: PlayerId
) -> list[Effect]:
    return [DrawCard(seat)] if chosen else []
