from yasuki_core.engine.rules.abilities.model import Ability, CardLocation, itself
from yasuki_core.engine.rules.abilities.registry import register_keyword_ability
from yasuki_core.engine.rules.action_record import resolving_ability
from yasuki_core.engine.rules.board.queries import province_key_of
from yasuki_core.engine.rules.effects import (
    Discard,
    DrawCard,
    Effect,
    PayGold,
    RefillProvince,
    Then,
)
from yasuki_core.engine.rules.state import GameState
from yasuki_core.engine.rules.vocabulary import keywords
from yasuki_core.engine.rules.vocabulary.actions import ActionTiming
from yasuki_core.game_pieces.cards import L5RCard

# What the Kharmic rulebook abilities cost to use.
KHARMIC_COST = 2

KHARMIC_DRAW = "draw"
KHARMIC_REFILL = "refill"


def is_kharmic_action(game: GameState) -> bool:
    """Whether the action now resolving is one of the rulebook Kharmic abilities."""
    ability = resolving_ability(game)
    return ability is not None and ability.from_keyword == keywords.KHARMIC


def _kharmic_cost(game: GameState, source: L5RCard) -> list[Effect]:
    return [PayGold(source.owner, KHARMIC_COST, keywords.KHARMIC)]


def _kharmic_draw_effects(game: GameState, source: L5RCard, target: L5RCard) -> list[Effect]:
    return [Discard(source.id, source.owner), Then((DrawCard(source.owner),))]


def _kharmic_refill_effects(game: GameState, source: L5RCard, target: L5RCard) -> list[Effect]:
    vacated = province_key_of(game, source.owner, source.id)
    return [Discard(source.id, source.owner), Then((RefillProvince(vacated, face_up=True),))]


# The datasheet's two Kharmic abilities, Repeatable Open at 2 Gold, conferred by the keyword on the
# card they spend: activated from the hand or the Province the card sits in, paid and interrupted
# as any card's ability is, and spending the card it is used on. A face-down Province card is not
# offered, because its owner has not seen it.
register_keyword_ability(
    Ability(
        timings=(ActionTiming.OPEN,),
        label=f"Repeatable Open, {KHARMIC_COST} Gold: Discard a Kharmic card to draw a card",
        cost=_kharmic_cost,
        targets=itself,
        effects=_kharmic_draw_effects,
        hits_every_target=True,
        key=KHARMIC_DRAW,
        repeatable=True,
        located_at=(CardLocation.HAND,),
        from_keyword=keywords.KHARMIC,
    )
)
register_keyword_ability(
    Ability(
        timings=(ActionTiming.OPEN,),
        label=f"Repeatable Open, {KHARMIC_COST} Gold: Discard a Kharmic card from your Province and "
        "refill it face-up",
        cost=_kharmic_cost,
        targets=itself,
        effects=_kharmic_refill_effects,
        hits_every_target=True,
        key=KHARMIC_REFILL,
        repeatable=True,
        located_at=(CardLocation.PROVINCE,),
        from_keyword=keywords.KHARMIC,
    )
)
