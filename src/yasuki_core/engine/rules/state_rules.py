from collections.abc import Callable

from yasuki_core.engine.rules.economy import effective_chi
from yasuki_core.engine.rules.effects import Destroy, Effect
from yasuki_core.game_pieces.cards import L5RCard
from yasuki_core.engine.rules.state import GameState
from yasuki_core.game_pieces.prints import PersonalityPrint

# A state rule reads the board and returns the effects the rules demand of it. Unlike a trigger it
# answers to no event: the CR states these as conditions that hold at all times rather than as
# consequences of something happening, so a rule fires however the board came to break it. The
# Chi Death Rule is the one modeled here; a seat losing its last Province, a seat controlling five
# Rings of different elements, and a destroyed Province ending its battlefield are the same shape.
StateRule = Callable[[GameState], list[Effect]]

# The cards whose own text exempts them from the Chi Death Rule, by printed id. Each says so
# plainly — "Stone Breaker will not be destroyed for having 0 Chi" — which the CR permits as a
# continuous effect. Listed here rather than registered from the set modules because it is data
# about a card rather than behavior; it belongs on the print, alongside the Chi it qualifies.
#
# Two cards that mention 0 Chi are deliberately absent. Moto Chagatai and Moto Soro read "unless
# his Chi is 0 after all penalties that last until your turn ends wear off" — a deferred check
# this rule cannot express, so they take the rule as written rather than a wrong exemption. Shuten
# Doji asks for a window before the destruction, which is a replacement rather than an exemption.
CHI_DEATH_EXEMPT: frozenset[str] = frozenset(
    {
        "bayushi_baku",
        "corpse_monstrosity",
        "daigotsu_endo",
        "earthen_golem",
        "hida_kanjouteki_experienced",
        "stone_breaker",
        "the_cursed_dead",
    }
)


def chi_death(game: GameState) -> list[Effect]:
    """Destroy every Personality in play whose Chi is zero (CR, Chi Death Rule).

    Zero is the whole condition: the stat floors there, so a Personality penalised past zero reads
    zero and dies. A card whose own text exempts it is skipped, which the CR permits because that
    text is a continuous effect and only those work against Chi death.
    """
    return [
        Destroy(card.id)
        for card in game.table.battlefield.cards
        if isinstance(card.printed, PersonalityPrint)
        and effective_chi(game, card) == 0
        and not _exempt_from_chi_death(card)
    ]


def _exempt_from_chi_death(card: L5RCard) -> bool:
    """Whether ``card``'s own text spares it the Chi Death Rule."""
    return card.printed_id in CHI_DEATH_EXEMPT


# Every state rule, in the order they are checked. Closed by design: this is the rulebook's list of
# conditions the board must satisfy, not an extension point cards register into.
STATE_RULES: tuple[StateRule, ...] = (chi_death,)


def demanded(game: GameState) -> list[Effect]:
    """What the rules demand of the board as it stands, or an empty list when it is already legal."""
    return [effect for rule in STATE_RULES for effect in rule(game)]
