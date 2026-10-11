from yasuki_core.engine.players import PlayerId
from yasuki_core.engine.rules.state import GameState
from yasuki_core.engine.rules.abilities.idioms import register_event_entry
from yasuki_core import ruleset
from yasuki_core.engine.rules.rulebook.recruit import refill_face_up
from yasuki_core.engine.rules.gold.production import gold_handler
from yasuki_core.engine.rules.board.clans import is_clan
from yasuki_core.game_pieces.cards import L5RCard


# --- A Prophet Revealed ---

register_event_entry("a_prophet_revealed")


# --- Famous Bazaar ---


@refill_face_up("famous_bazaar")
def _famous_bazaar_refill_face_up(game: GameState, bazaar: L5RCard, recruited: L5RCard) -> bool:
    """ "After you Recruit this Holding from a Province, refill the Province face-up." Shattered
    Empire prints the same rule as the Renew keyword."""
    return recruited is bazaar


# --- Teardrop Island ---


@gold_handler("teardrop_island")
def _teardrop_island_gold(
    card: L5RCard, game: GameState, seat: PlayerId, targets: tuple[L5RCard, ...]
) -> int:
    """Produce 2 Gold, or 3 while you are a Mantis Clan player."""
    return 3 if is_clan(game, seat, ruleset.MANTIS) else 2
