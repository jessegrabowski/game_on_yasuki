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


def kharmic_ability(form: str) -> Ability:
    """The rulebook Kharmic ability of one form on the card it spends: Repeatable Open at the
    printed cost, the ``KHARMIC_DRAW`` form activated from the hand or the ``KHARMIC_REFILL`` form
    activated from a Province. Raise ValueError for any other ``form``.

    The datasheet names the forms by side, Fate and Dynasty. They are keyed here by where the card
    sits, which is the same thing on every board a card produces today.

    A card that changes how the ability is used builds on this with ``dataclasses.replace``, so
    the form's effects have one home.
    """
    if form == KHARMIC_DRAW:
        located_at = CardLocation.HAND
        effects = _kharmic_draw_effects
        text = "Discard a Kharmic card to draw a card"
    elif form == KHARMIC_REFILL:
        located_at = CardLocation.PROVINCE
        effects = _kharmic_refill_effects
        text = "Discard a Kharmic card from your Province and refill it face-up"
    else:
        raise ValueError(f"{form!r} is not a Kharmic form")

    return Ability(
        timings=(ActionTiming.OPEN,),
        label=f"Repeatable Open, :g{KHARMIC_COST}:: {text}",
        cost=_kharmic_cost,
        targets=itself,
        effects=effects,
        hits_every_target=True,
        key=form,
        repeatable=True,
        located_at=(located_at,),
        from_keyword=keywords.KHARMIC,
        from_rulebook=True,
    )


def _kharmic_cost(game: GameState, source: L5RCard) -> list[Effect]:
    return [PayGold(source.owner, KHARMIC_COST, keywords.KHARMIC)]


def _kharmic_draw_effects(game: GameState, source: L5RCard, target: L5RCard) -> list[Effect]:
    return [Discard(source.id, source.owner), Then((DrawCard(source.owner),))]


def _kharmic_refill_effects(game: GameState, source: L5RCard, target: L5RCard) -> list[Effect]:
    vacated = province_key_of(game, source.owner, source.id)
    return [Discard(source.id, source.owner), Then((RefillProvince(vacated, face_up=True),))]


# The datasheet's two Kharmic abilities, conferred by the keyword on the card they spend and paid
# and interrupted as any card's ability is. A face-down Province card is not offered, because its
# owner has not seen it.
register_keyword_ability(kharmic_ability(KHARMIC_DRAW))
register_keyword_ability(kharmic_ability(KHARMIC_REFILL))
