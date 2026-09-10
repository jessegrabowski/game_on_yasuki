from yasuki_core.engine import ops
from yasuki_core.engine.rules.effects import RefillProvince
from yasuki_core.engine.rules.state import GameState
from yasuki_core.engine.rules.vocabulary.work import ApplyEffects
from yasuki_core.engine.table import ZoneKey, ZoneRole


def defer_refill(game: GameState, zone: ZoneKey, *, face_up: bool = False) -> None:
    """Queue the refill of a Province a card has just left, behind the reactions to it leaving.

    The rules put it there: the effects triggered by the card leaving or entering play resolve
    first, and only then is the Province refilled — and only if it is still short.
    """
    game.stack.append(ApplyEffects((RefillProvince(zone, face_up=face_up),)))


def refill_short_provinces(game: GameState) -> None:
    """Refill every Province standing short, face-down, as far as the Dynasty decks reach.

    A Province refills because it is empty, whatever emptied it. The refills the rules time
    explicitly — a Renew's face-up arrival, Kharmic's — resolve inside the cascade and land first,
    leaving nothing short here.
    """
    for key, zone in game.table.zones.items():
        if key.role is ZoneRole.PROVINCE and zone.has_capacity():
            ops.fill_province(game.table, key.owner, zone)
