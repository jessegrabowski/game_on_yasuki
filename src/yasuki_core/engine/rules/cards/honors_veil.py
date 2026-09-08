from yasuki_core.engine.players import PlayerId
from yasuki_core.engine.rules.state import GameState
from yasuki_core.engine.rules.abilities.idioms import register_event_entry
from yasuki_core import ruleset
from yasuki_core.engine.rules.keyword_grants import keyword_grant
from yasuki_core.engine.rules.gold.production import gold_handler
from yasuki_core.engine.rules.board.clans import is_clan
from yasuki_core.game_pieces import keywords
from yasuki_core.game_pieces.cards import L5RCard


# --- A Prophet Revealed ---

register_event_entry("a_prophet_revealed")


# --- Famous Bazaar ---


@keyword_grant("famous_bazaar")
def _famous_bazaar_keywords(card: L5RCard, game: GameState, seat: PlayerId) -> tuple[str, ...]:
    """Renew, which the card carries under either templating: Shattered Empire prints it on the
    keyword line, and every earlier printing spells the same rule out in the text box."""
    return (keywords.RENEW,)


# --- Teardrop Island ---


@gold_handler("teardrop_island")
def _teardrop_island_gold(
    card: L5RCard, game: GameState, seat: PlayerId, targets: tuple[L5RCard, ...]
) -> int:
    """Produce 2 Gold, or 3 while you are a Mantis Clan player."""
    return 3 if is_clan(game, seat, ruleset.MANTIS) else 2
