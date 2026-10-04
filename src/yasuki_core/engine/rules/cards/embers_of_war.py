from yasuki_core.engine.players import PlayerId
from yasuki_core.engine.rules.abilities.costs import no_cost
from yasuki_core.engine.rules.abilities.model import Ability
from yasuki_core.engine.rules.abilities.registry import register_ability
from yasuki_core.engine.rules.board.queries import owned_carrying
from yasuki_core.engine.rules.effects import AskOption, Effect, GrantKeyword
from yasuki_core.engine.rules.state import GameState
from yasuki_core.engine.rules.triggers import choice_resolver
from yasuki_core.engine.rules.vocabulary import keywords
from yasuki_core.engine.rules.vocabulary.actions import ActionTiming
from yasuki_core.engine.rules.vocabulary.modifiers import Duration
from yasuki_core.game_pieces.cards import L5RCard


# --- Temple to the Elements ---

# In the order the card names them.
TEMPLE_TO_THE_ELEMENTS_ELEMENTS = (keywords.AIR, keywords.EARTH, keywords.FIRE, keywords.WATER)


def _temple_to_the_elements_targets(game: GameState, source: L5RCard) -> list[str]:
    """Your Monks and Shugenja, Followers among them, bowed or not."""
    return [
        card.id for card in owned_carrying(game, source.owner, keywords.MONK, keywords.SHUGENJA)
    ]


def _temple_to_the_elements_effects(
    game: GameState, source: L5RCard, target: L5RCard
) -> list[Effect]:
    return [
        AskOption(
            source.owner,
            TEMPLE_TO_THE_ELEMENTS_ELEMENTS,
            f"Give {target.name} which element?",
            "temple_to_the_elements",
            source.id,
            resolver_context=(target.id,),
        )
    ]


@choice_resolver("temple_to_the_elements")
def _resolve_temple_to_the_elements(
    game: GameState,
    source_id: str,
    chosen: tuple[str, ...],
    seat: PlayerId,
    resolver_context: tuple[str, ...] = (),
) -> list[Effect]:
    """The text gives no duration, so the keyword lasts until the end of the turn (CR, Ongoing)."""
    return [GrantKeyword(source_id, resolver_context[0], chosen[0], Duration.UNTIL_END_OF_TURN)]


register_ability(
    "temple_to_the_elements",
    Ability(
        timings=(ActionTiming.OPEN,),
        cost=no_cost,
        targets=_temple_to_the_elements_targets,
        targeting_message="your Monk or Shugenja",
        effects=_temple_to_the_elements_effects,
    ),
)
