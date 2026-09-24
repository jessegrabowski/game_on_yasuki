from yasuki_core.engine.rules.abilities.costs import no_cost
from yasuki_core.engine.rules.abilities.model import Ability, CardLocation
from yasuki_core.engine.rules.abilities.registry import register_ability
from yasuki_core.engine.rules.board.queries import has_keyword, owned_personalities, top_of_deck
from yasuki_core.engine.rules.effects import Bow, Choose, Effect, LookAtTop
from yasuki_core.engine.rules.rulebook.looks import TAKE_ONE_AND_SHUFFLE
from yasuki_core.engine.rules.state import GameState
from yasuki_core.engine.rules.vocabulary import keywords
from yasuki_core.engine.rules.vocabulary.actions import ActionTiming
from yasuki_core.engine.table import DeckKey
from yasuki_core.game_pieces.cards import L5RCard
from yasuki_core.game_pieces.constants import Side


# --- Banish All Shadows ---

BANISH_ALL_SHADOWS_LOOK = 4


def _banish_all_shadows_targets(game: GameState, source: L5RCard) -> list[str]:
    """Your unbowed Monks and Shugenja."""
    return [
        card.id
        for card in owned_personalities(game, source.owner)
        if not card.bowed
        and (has_keyword(game, card, keywords.MONK) or has_keyword(game, card, keywords.SHUGENJA))
    ]


def _banish_all_shadows_effects(game: GameState, source: L5RCard, target: L5RCard) -> list[Effect]:
    """Bow the target and look at the top four. An empty deck leaves only the bow."""
    seat = source.owner
    fate = DeckKey(seat, Side.FATE)
    seen = top_of_deck(game, fate, BANISH_ALL_SHADOWS_LOOK)
    if not seen:
        return [Bow(target.id)]
    return [
        Bow(target.id),
        LookAtTop(seat, fate, len(seen)),
        Choose(seat, seen, 1, 1, TAKE_ONE_AND_SHUFFLE, source.id),
    ]


register_ability(
    "banish_all_shadows",
    Ability(
        timings=(ActionTiming.LIMITED,),
        keywords=frozenset({keywords.KIHO}),
        cost=no_cost,
        targets=_banish_all_shadows_targets,
        targeting_message="your unbowed Monk or Shugenja",
        effects=_banish_all_shadows_effects,
        located_at=(CardLocation.HAND,),
    ),
)
