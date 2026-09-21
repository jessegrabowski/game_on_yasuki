from yasuki_core.engine.players import PlayerId
from yasuki_core.engine.rules.abilities.costs import no_cost
from yasuki_core.engine.rules.abilities.model import Ability, CardLocation, itself
from yasuki_core.engine.rules.abilities.registry import register_ability
from yasuki_core.engine.rules.board.queries import (
    has_keyword,
    owned_personalities,
    remaining_look,
    top_of_deck,
)
from yasuki_core.engine.rules.effects import (
    Arrange,
    Choose,
    Effect,
    EndLook,
    GrantConditionalModifier,
    LookAtTop,
    MoveToHand,
    SpendSeatOncePerTurn,
)
from yasuki_core.engine.rules.rulebook.looks import PUT_ON_BOTTOM
from yasuki_core.engine.rules.state import GameState, seat_once_key
from yasuki_core.engine.rules.triggers import choice_resolver
from yasuki_core.engine.rules.vocabulary import keywords
from yasuki_core.engine.rules.vocabulary.actions import ActionTiming
from yasuki_core.engine.rules.vocabulary.modifiers import Condition, Duration, Stat
from yasuki_core.engine.table import DeckKey
from yasuki_core.game_pieces.cards import L5RCard
from yasuki_core.game_pieces.constants import Side


# --- Banish All Doubt ---

BANISH_ALL_DOUBT_LOOK = 4


def _banish_all_doubt_targets(game: GameState, source: L5RCard) -> list[str]:
    """Your unbowed Tacticians. The Tactician performs the action and is not bowed by it."""
    return [
        card.id
        for card in owned_personalities(game, source.owner)
        if not card.bowed and has_keyword(game, card, keywords.TACTICIAN)
    ]


def _banish_all_doubt_effects(game: GameState, source: L5RCard, target: L5RCard) -> list[Effect]:
    """Look at the top four and take one. An empty deck leaves nothing to do."""
    seat = source.owner
    fate = DeckKey(seat, Side.FATE)
    seen = top_of_deck(game, fate, BANISH_ALL_DOUBT_LOOK)
    if not seen:
        return []
    return [
        LookAtTop(seat, fate, len(seen)),
        Choose(seat, seen, 1, 1, "banish_all_doubt", source.id),
    ]


@choice_resolver("banish_all_doubt", prompt="Put one of them in your hand")
def _resolve_banish_all_doubt(
    game: GameState, source_id: str, chosen: tuple[str, ...], seat: PlayerId
) -> list[Effect]:
    """The other three go on the bottom in the order the seat gives."""
    rest = tuple(card_id for card_id in remaining_look(game) if card_id not in chosen)
    taken = [MoveToHand(card_id, seat) for card_id in chosen]
    if not rest:
        return [*taken, EndLook()]
    return [*taken, Arrange(seat, rest, PUT_ON_BOTTOM, source_id, to_bottom=True)]


register_ability(
    "banish_all_doubt",
    Ability(
        timings=(ActionTiming.LIMITED,),
        keywords=frozenset({keywords.TACTICAL}),
        label="Tactical Limited: Target your performing unbowed Tactician to look at the top four "
        "cards of your Fate deck. Put one of them in your hand and put the other three on the "
        "bottom of your deck in any order.",
        cost=no_cost,
        targets=_banish_all_doubt_targets,
        targeting_message="your performing unbowed Tactician",
        effects=_banish_all_doubt_effects,
        located_at=(CardLocation.HAND,),
    ),
)


# --- Flashy Technique ---

FLASHY_TECHNIQUE = "flashy_technique"
FLASHY_TECHNIQUE_PENALTY = -1


def _flashy_technique_effects(game: GameState, source: L5RCard, target: L5RCard) -> list[Effect]:
    """The penalty, unless its controller has played another Flashy Technique this turn, in which
    case the action is legal and does nothing. The Focus Effect only applies inside a duel and none
    is fought yet."""
    if game.has_used(seat_once_key(source.owner, FLASHY_TECHNIQUE, game.turn)):
        return []
    return [
        SpendSeatOncePerTurn(source.owner, FLASHY_TECHNIQUE),
        GrantConditionalModifier(
            source.id,
            Condition.ATTACKING,
            Stat.FORCE,
            FLASHY_TECHNIQUE_PENALTY,
            Duration.UNTIL_END_OF_TURN,
        ),
    ]


register_ability(
    "flashy_technique",
    Ability(
        timings=(ActionTiming.OPEN,),
        label="Open: Personalities have -1F while attacking this turn",
        cost=no_cost,
        targets=itself,
        effects=_flashy_technique_effects,
        located_at=(CardLocation.HAND,),
        hits_every_target=True,
    ),
)
