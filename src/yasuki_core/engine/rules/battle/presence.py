from yasuki_core.engine import ops
from yasuki_core.engine.rules.battle.records import AttackPhase
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
    if location.battlefield is not None and game.attack is not None:
        _record_presence(game.attack, location.battlefield, personality)
    return moved


def _record_presence(attack: AttackPhase, battlefield: int, personality: L5RCard) -> None:
    # A NamedTuple, so this is a replacement rather than an assignment.
    attack.battlefields = tuple(
        info._replace(ever_present=info.ever_present | {(personality.owner, personality.id)})
        if index == battlefield
        else info
        for index, info in enumerate(attack.battlefields)
    )
