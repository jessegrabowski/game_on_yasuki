from yasuki_core.engine.players import PlayerId
from yasuki_core.engine.rules.abilities import (
    Ability,
    CardLocation,
    bow_parent_and_destroy,
    no_cost,
    register_ability,
)
from yasuki_core.engine.rules.actions import ActionTiming
from yasuki_core.engine.rules.attachments import attached_to
from yasuki_core.engine.rules.economy import PlayerState, effective_chi, is_clan, recruit_discount
from yasuki_core.engine.rules.effects import (
    Choose,
    Destroy,
    Discard,
    Effect,
    GainHonor,
    MoveToHand,
    Show,
    ShuffleDeck,
    Then,
)
from yasuki_core.engine.rules.state import GameState
from yasuki_core.engine.rules.triggers import choice_resolver
from yasuki_core.engine.table import DeckKey
from yasuki_core.game_pieces.cards import L5RCard
from yasuki_core.game_pieces.constants import AttachmentType, Side
from yasuki_core.game_pieces.prints import AttachmentPrint, PersonalityPrint


# --- Fantastic Gardens ---


@recruit_discount("fantastic_gardens")
def _fantastic_gardens(card: L5RCard, me: PlayerState, opponents: tuple[PlayerState, ...]) -> int:
    """Enters play for 2 less Gold if you are a Crane Clan player."""
    return 2 if is_clan(me, "Crane") else 0


# --- Imperial Gift ---


def _fate_deck_items(game: GameState, seat: PlayerId) -> tuple[str, ...]:
    """The Items in ``seat``'s Fate deck — what the search may turn up."""
    return tuple(
        card.id
        for card in game.table.decks[DeckKey(seat, Side.FATE)].cards
        if isinstance(card.printed, AttachmentPrint)
        and card.printed.attachment_type is AttachmentType.ITEM
    )


@choice_resolver("imperial_gift_item", prompt="Search your Fate deck for an Item")
def _imperial_gift_item(
    game: GameState, source_id: str, chosen: tuple[str, ...], seat: PlayerId
) -> list[Effect]:
    """Show the Item to the table, put it in hand, then shuffle the deck the search read. The
    disclosure outlives the move: once the opponent has seen which Item was taken, hiding the card
    again does not unsay it."""
    return [
        Show(chosen[0]),
        MoveToHand(chosen[0], seat),
        ShuffleDeck(DeckKey(seat, Side.FATE)),
    ]


def _imperial_gift_targets(game: GameState, card: L5RCard) -> list[str]:
    """The Event itself. The honor is unconditional, so the ability is offered whether or not the
    Fate deck holds an Item; the search is a choice raised after it, not the ability's target."""
    return [card.id]


def _imperial_gift_effects(game: GameState, source: L5RCard, target: L5RCard) -> list[Effect]:
    """Gain 2 Honor, spend the Event, then search. The card offers no choice about taking what it
    finds, so the search is skipped only when the deck holds no Item at all."""
    seat = source.owner
    spent: list[Effect] = [GainHonor(seat, 2), Discard(source.id, seat)]
    items = _fate_deck_items(game, seat)
    if not items:
        return spent
    return [*spent, Then((Choose(seat, items, 1, 1, "imperial_gift_item", source.id),))]


register_ability(
    "imperial_gift",
    Ability(
        timing=ActionTiming.OPEN,
        label="Gain 2 Honor and search your Fate deck for an Item",
        cost=no_cost,
        targets=_imperial_gift_targets,
        effects=_imperial_gift_effects,
        all_targets=True,
        located_at=(CardLocation.PROVINCE,),
    ),
)


# --- Touch of Death ---


def _get_touch_of_death_valid_targets(game: GameState, source: L5RCard) -> list[str]:
    """Bowed Personalities whose Chi does not exceed the Shugenja carrying this Spell.

    "Equal or lower" names no referent; the comparison is against the caster. The caster is never
    among these, since he has to be unbowed to pay the cost that bows him.
    """
    caster = attached_to(game, source)
    if caster is None:
        return []
    ceiling = effective_chi(game, caster)
    return [
        card.id
        for card in game.table.battlefield.cards
        if isinstance(card.printed, PersonalityPrint)
        and card.bowed
        and effective_chi(game, card) <= ceiling
    ]


def _resolve_touch_of_death_effect(
    game: GameState, source: L5RCard, target: L5RCard
) -> list[Effect]:
    return [Destroy(target.id, source.owner)]


register_ability(
    "touch_of_death",
    Ability(
        timing=ActionTiming.LIMITED,
        label="Limited: destroy a bowed Personality with Chi no higher than this Shugenja's",
        cost=bow_parent_and_destroy,
        targets=_get_touch_of_death_valid_targets,
        effects=_resolve_touch_of_death_effect,
    ),
)
