from yasuki_core import ruleset
from yasuki_core.engine.rules.economy import PlayerState, gold_handler, is_clan, keyword_grant
from yasuki_core.game_pieces import keywords
from yasuki_core.game_pieces.cards import L5RCard


# --- Famous Bazaar ---


@keyword_grant("famous_bazaar")
def _famous_bazaar_keywords(
    card: L5RCard, me: PlayerState, opponents: tuple[PlayerState, ...]
) -> tuple[str, ...]:
    """Renew, which the card carries under either templating.

    Shattered Empire prints it on the keyword line; every earlier printing spells the same rule out
    in the text box. Granting it here keeps the Province refilling face-up whichever printing's
    record the board was built from.
    """
    return (keywords.RENEW,)


# --- Teardrop Island ---


@gold_handler("teardrop_island")
def _teardrop_island_gold(
    card: L5RCard, me: PlayerState, opponents: tuple[PlayerState, ...], targets: tuple[L5RCard, ...]
) -> int:
    """Produce 2 Gold, or 3 while you are a Mantis Clan player."""
    return 3 if is_clan(me, ruleset.MANTIS) else 2
