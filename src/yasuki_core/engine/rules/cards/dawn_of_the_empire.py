from yasuki_core.engine.players import PlayerId
from yasuki_core.engine.rules.abilities.costs import bow_cost
from yasuki_core.engine.rules.abilities.model import Ability, itself
from yasuki_core.engine.rules.abilities.registry import register_ability
from yasuki_core.engine.rules.board.queries import top_of_deck
from yasuki_core.engine.rules.effects import (
    AskOption,
    Choose,
    Effect,
    EndLook,
    LookAtTop,
    MoveToHand,
    Show,
)
from yasuki_core.engine.rules.state import GameState
from yasuki_core.engine.rules.triggers import choice_resolver
from yasuki_core.engine.rules.vocabulary.actions import ActionTiming
from yasuki_core.engine.table import DeckKey
from yasuki_core.game_pieces.cards import L5RCard
from yasuki_core.game_pieces.constants import AttachmentType, Side
from yasuki_core.game_pieces.prints import AttachmentPrint


# --- Temples of Gisei Toshi ---

TEMPLES_LOOK = 4
# In the order the card names them.
TEMPLES_TYPES = (
    AttachmentType.FOLLOWER.value,
    AttachmentType.ITEM.value,
    AttachmentType.SPELL.value,
)


def _temples_of_gisei_toshi_effects(
    game: GameState, source: L5RCard, target: L5RCard
) -> list[Effect]:
    """Name the type first, so the look that follows knows which cards it offers."""
    return [
        AskOption(
            source.owner,
            TEMPLES_TYPES,
            'Name "Follower", "Item", or "Spell".',
            "temples_of_gisei_toshi_name",
            source.id,
        )
    ]


def _temples_of_gisei_toshi_of_type(
    game: GameState, card_ids: tuple[str, ...], named: str
) -> tuple[str, ...]:
    of_type = []
    for card_id in card_ids:
        printed = game.table.cards_by_id[card_id].printed
        if isinstance(printed, AttachmentPrint) and printed.attachment_type.value == named:
            of_type.append(card_id)
    return tuple(of_type)


@choice_resolver("temples_of_gisei_toshi_name")
def _resolve_temples_of_gisei_toshi_name(
    game: GameState, source_id: str, chosen: tuple[str, ...], seat: PlayerId
) -> list[Effect]:
    """Look at the top four and offer the ones of the named type. When none is, the look is still
    shown, with nothing to pick and only the way out, because the seat has read the cards."""
    fate = DeckKey(seat, Side.FATE)
    seen = top_of_deck(game, fate, TEMPLES_LOOK)
    if not seen:
        return []
    offered = _temples_of_gisei_toshi_of_type(game, seen, chosen[0])
    key = "temples_of_gisei_toshi_take" if offered else "temples_of_gisei_toshi_none"
    return [LookAtTop(seat, fate, len(seen)), Choose(seat, offered, 0, 1, key, source_id)]


@choice_resolver(
    "temples_of_gisei_toshi_take",
    prompt="You may show one of those cards that is of the type you named, then put it in your hand",
)
def _resolve_temples_of_gisei_toshi_take(
    game: GameState, source_id: str, chosen: tuple[str, ...], seat: PlayerId
) -> list[Effect]:
    """The rest stay where they are."""
    if not chosen:
        return [EndLook()]
    return [Show(chosen[0]), MoveToHand(chosen[0], seat), EndLook()]


@choice_resolver(
    "temples_of_gisei_toshi_none", prompt="None of those cards is of the type you named"
)
def _resolve_temples_of_gisei_toshi_none(
    game: GameState, source_id: str, chosen: tuple[str, ...], seat: PlayerId
) -> list[Effect]:
    return [EndLook()]


register_ability(
    "temples_of_gisei_toshi",
    Ability(
        timings=(ActionTiming.LIMITED,),
        label='Limited, bow: Name "Follower", "Item", or "Spell". Look at the top four cards of '
        "your Fate deck. You may show one of those cards that is of the type you named, then put "
        "it in your hand.",
        cost=bow_cost,
        targets=itself,
        effects=_temples_of_gisei_toshi_effects,
    ),
)
