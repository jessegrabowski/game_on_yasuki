from yasuki_core.engine import ops
from yasuki_core.engine.players import PlayerId
from yasuki_core.engine.rules.state import GameState
from yasuki_core.engine.rules.units.membership import attached_to
from yasuki_core.engine.table import Location
from yasuki_core.game_pieces.cards import L5RCard


def place_unit(game: GameState, card: L5RCard, location: Location) -> bool:
    """Put ``card``'s whole unit at ``location`` and, at a battlefield, record its Personality as
    ever present there. Return whether the unit moved.

    The unit is the one ``card``'s Personality leads, so naming an attached card moves the
    Personality and everything attached to him (CR, Unit). Assignment and a card's move both come
    through here, which is what keeps the record complete. Sending a unit home leaves the record
    as it is.
    """
    personality = attached_to(game, card) or card
    moved = ops.move_unit(game.table, personality, location)
    attack = game.attack
    if location.battlefield is not None and attack is not None:
        present = attack.battlefields[location.battlefield].ever_present
        attack.amend(
            location.battlefield, ever_present=present | {(personality.owner, personality.id)}
        )
    return moved


def record_terrain_played(game: GameState, card: L5RCard, battlefield: int) -> None:
    """Record that ``card``'s owner played it, a Terrain, from hand at ``battlefield``."""
    attack = game.attack
    assert attack is not None
    played = attack.battlefields[battlefield].terrains_played
    attack.amend(battlefield, terrains_played=played | {(card.owner, card.id)})


def record_terrain_destroyed(
    game: GameState, seat: PlayerId, card: L5RCard, battlefield: int
) -> None:
    """Record that ``seat`` destroyed ``card``, a Terrain at ``battlefield``."""
    attack = game.attack
    assert attack is not None
    destroyed = attack.battlefields[battlefield].terrains_destroyed
    attack.amend(battlefield, terrains_destroyed=destroyed | {(seat, card.id)})
