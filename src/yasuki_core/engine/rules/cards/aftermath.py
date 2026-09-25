from yasuki_core.engine.rules.abilities.idioms import register_terrain
from yasuki_core.engine.rules.state import GameState
from yasuki_core.engine.rules.stats.keyword_grants import effective_keywords
from yasuki_core.engine.rules.stats.stat_grants import stat_grant
from yasuki_core.engine.rules.units.composition import followers_of
from yasuki_core.engine.rules.vocabulary import keywords
from yasuki_core.engine.rules.vocabulary.modifiers import Stat
from yasuki_core.game_pieces.cards import L5RCard
from yasuki_core.game_pieces.prints import PersonalityPrint


# --- Lonely Battlefield ---

LONELY_BATTLEFIELD_PENALTY = -2
LONELY_BATTLEFIELD_COMMANDER_BONUS = 1


@stat_grant("lonely_battlefield")
def _lonely_battlefield_stat_grant(
    game: GameState, source: L5RCard, card: L5RCard, stat: Stat
) -> int:
    """ "Personalities without Followers have -2F. Commanders have +1F." The text names no
    battlefield, so it reaches every such card in play."""
    if stat is not Stat.FORCE or not any(held is card for held in game.table.battlefield.cards):
        return 0
    amount = 0
    if isinstance(card.printed, PersonalityPrint) and not followers_of(game, card):
        amount += LONELY_BATTLEFIELD_PENALTY
    if keywords.COMMANDER in effective_keywords(game, card):
        amount += LONELY_BATTLEFIELD_COMMANDER_BONUS
    return amount


register_terrain("lonely_battlefield")
