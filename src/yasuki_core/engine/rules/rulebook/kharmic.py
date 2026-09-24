from yasuki_core.engine.players import PlayerId
from yasuki_core.engine.rules.abilities.model import Ability, CardLocation
from yasuki_core.engine.rules.abilities.registry import register_ability
from yasuki_core.engine.rules.board.queries import (
    has_keyword,
    province_cards,
    province_key_of,
    rulebook_proxy,
)
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
from yasuki_core.engine.rules.vocabulary.actions import ActionTiming, ActivateAbility
from yasuki_core.engine.table import ZoneKey, ZoneRole
from yasuki_core.game_pieces.cards import L5RCard
from yasuki_core.game_pieces.constants import KHARMIC_PROXY_ID, Side
from yasuki_core.game_pieces.prints import CardPrint

# What the Kharmic rulebook abilities cost to use.
KHARMIC_COST = 2

KHARMIC_DRAW = "draw"
KHARMIC_REFILL = "refill"

# The print each seat's Kharmic proxy presents; ``rulebook/proxies.py`` deals it. A proxy is in no
# deck, so its side means nothing; STRONGHOLD is the catalog's bucket for such cards.
KHARMIC_PROXY = CardPrint(
    name="Kharmic", side=Side.STRONGHOLD, printed_id=KHARMIC_PROXY_ID, card_type="Other"
)


def kharmic_proxy(game: GameState, seat: PlayerId) -> L5RCard | None:
    """The card ``seat`` activates the Kharmic abilities from, or None before one is dealt."""
    return rulebook_proxy(game, seat, KHARMIC_PROXY_ID)


def is_kharmic_action(game: GameState) -> bool:
    """Whether the action now resolving is one of the rulebook Kharmic abilities."""
    action = game.action
    if not isinstance(action, ActivateAbility):
        return False
    return game.table.cards_by_id[action.card_id].printed_id == KHARMIC_PROXY_ID


def is_kharmic_card(game: GameState, card: L5RCard) -> bool:
    """Whether ``card`` carries the Kharmic keyword, so a Kharmic ability can spend it."""
    return has_keyword(game, card, keywords.KHARMIC)


def kharmic_in_hand(game: GameState, seat: PlayerId) -> list[L5RCard]:
    """The Kharmic cards ``seat`` holds, which the Fate Kharmic ability discards to draw."""
    hand = game.table.zones[ZoneKey(seat, ZoneRole.HAND)]
    return [card for card in hand.cards if is_kharmic_card(game, card)]


def kharmic_in_provinces(game: GameState, seat: PlayerId) -> list[L5RCard]:
    """The Kharmic cards face-up in ``seat``'s Provinces, which the Dynasty Kharmic ability discards
    to refill face-up. A face-down Province card is unknown to its owner, so it cannot be named."""
    return [
        card for card in province_cards(game, seat) if card.face_up and is_kharmic_card(game, card)
    ]


def _kharmic_cost(game: GameState, source: L5RCard) -> list[Effect]:
    return [PayGold(source.owner, KHARMIC_COST, keywords.KHARMIC)]


def _kharmic_draw_targets(game: GameState, source: L5RCard) -> list[str]:
    return [card.id for card in kharmic_in_hand(game, source.owner)]


def _kharmic_draw_effects(game: GameState, source: L5RCard, target: L5RCard) -> list[Effect]:
    return [Discard(target.id, source.owner), Then((DrawCard(source.owner),))]


def _kharmic_refill_targets(game: GameState, source: L5RCard) -> list[str]:
    return [card.id for card in kharmic_in_provinces(game, source.owner)]


def _kharmic_refill_effects(game: GameState, source: L5RCard, target: L5RCard) -> list[Effect]:
    vacated = province_key_of(game, source.owner, target.id)
    return [Discard(target.id, source.owner), Then((RefillProvince(vacated, face_up=True),))]


# The datasheet's two Kharmic abilities, Repeatable Open at 2 Gold, on the proxy rather than on the
# player: activated, paid, targeted and interrupted as any card's ability is.
register_ability(
    KHARMIC_PROXY_ID,
    Ability(
        timings=(ActionTiming.OPEN,),
        label=f"Repeatable Open, {KHARMIC_COST} Gold: Discard a Kharmic card to draw a card",
        cost=_kharmic_cost,
        targets=_kharmic_draw_targets,
        effects=_kharmic_draw_effects,
        key=KHARMIC_DRAW,
        repeatable=True,
        located_at=(CardLocation.RULEBOOK,),
        targeting_message="a Kharmic card in your hand",
    ),
)
register_ability(
    KHARMIC_PROXY_ID,
    Ability(
        timings=(ActionTiming.OPEN,),
        label=f"Repeatable Open, {KHARMIC_COST} Gold: Discard a Kharmic card from your Province and "
        "refill it face-up",
        cost=_kharmic_cost,
        targets=_kharmic_refill_targets,
        effects=_kharmic_refill_effects,
        key=KHARMIC_REFILL,
        repeatable=True,
        located_at=(CardLocation.RULEBOOK,),
        targeting_message="a face-up Kharmic card in your Province",
    ),
)
