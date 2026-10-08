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
    through here, which is what keeps the record complete and what makes a sealed battlefield
    sealed: a unit never recorded present at one is refused, assigned or moved. Sending a unit
    home leaves the record as it is.
    """
    personality = attached_to(game, card) or card
    attack = game.attack
    if location.battlefield is None or attack is None:
        return ops.move_unit(game.table, personality, location)
    info = attack.battlefields[location.battlefield]
    arriving = (personality.owner, personality.id)
    if info.sealed and arriving not in info.ever_present:
        return False
    moved = ops.move_unit(game.table, personality, location)
    attack.amend(location.battlefield, ever_present=info.ever_present | {arriving})
    return moved


def record_printed_action(game: GameState, seat: PlayerId) -> None:
    """Record that ``seat`` took a printed action from one of its cards during the battle being
    fought. Nothing is recorded between battles."""
    attack = game.attack
    if attack is None or attack.current is None:
        return
    taken = attack.battlefields[attack.current].printed_actions
    attack.amend(attack.current, printed_actions=taken | {seat})


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
