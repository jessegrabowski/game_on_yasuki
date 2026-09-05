from yasuki_core.engine.rules.economy import lobby_bonus_grant, province_strength_grant
from yasuki_core.engine.rules.state import GameState
from yasuki_core.engine.table import ZoneKey
from yasuki_core.game_pieces.cards import L5RCard


# --- Defensive Memorial ---


@province_strength_grant("defensive_memorial")
def _defensive_memorial_province_strength(game: GameState, card: L5RCard, province: ZoneKey) -> int:
    """ "This Province has +2 strength." Its other two lines need no handler: a Holding enters play
    bowed by the rulebook, and ":bow:: Produce 2 Gold" is the Gold Production it prints."""
    return 2


# --- Shigekawa's Court ---


@lobby_bonus_grant("shigekawas_court")
def _shigekawas_court_lobby_bonus(game: GameState, card: L5RCard) -> int:
    """ "You have a +5 Lobby Bonus." Whatever amount a Lobby action checks about its controller, not
    Family Honor alone. Its ":bow:: Produce 1 Gold" is the Gold Production it prints."""
    return 5
