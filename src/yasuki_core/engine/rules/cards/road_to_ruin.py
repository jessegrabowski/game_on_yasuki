from yasuki_core.engine.rules.abilities import (
    Ability,
    CardLocation,
    ProductionBoost,
    no_cost,
    register_ability,
    register_production_boost,
)
from yasuki_core.engine.rules.actions import ActionTiming
from yasuki_core.engine.rules.effects import (
    Destroy,
    Discard,
    Effect,
    GrantModifier,
    PlaceInProvince,
)
from yasuki_core.engine.rules.legality import province_key_holding
from yasuki_core.engine.rules.modifiers import Duration, Stat
from yasuki_core.engine.rules.state import GameState
from yasuki_core.engine.table import DeckKey, ZoneKey, ZoneRole
from yasuki_core.game_pieces.cards import L5RCard
from yasuki_core.game_pieces.constants import Side
from yasuki_core.game_pieces.prints import HoldingPrint


# --- Outlying Farms ---


def _destroy_for_boosting(card: L5RCard) -> list[Effect]:
    """ "...if you did, destroy it after it bows." The destruction is this card's price for the
    boost; Jade Mine and Slave Pits pay different ones."""
    return [Destroy(card.id, card.owner)]


register_production_boost("outlying_farms", ProductionBoost(2, _destroy_for_boosting))


# --- Repairing the Ruins ---


def _rebuildable_holdings(game: GameState, source: L5RCard) -> list[str]:
    """Non-Unique Holdings in the seat's Dynasty deck or discard pile that they control no copy of."""
    seat = source.owner
    held = {
        card.printed_id
        for card in game.table.battlefield.cards
        if card.owner is seat and isinstance(card.printed, HoldingPrint)
    }
    searched = [
        *game.table.decks[DeckKey(seat, Side.DYNASTY)].cards,
        *game.table.zones[ZoneKey(seat, ZoneRole.DYNASTY_DISCARD)].cards,
    ]
    return [
        card.id
        for card in searched
        if isinstance(card.printed, HoldingPrint)
        and not card.printed.is_unique
        and card.printed_id not in held
    ]


def _rebuild_the_province(game: GameState, source: L5RCard, target: L5RCard) -> list[Effect]:
    """Discard the Event and put the found Holding in the Province it vacated, permanently +1 Gold
    Cost unless it came from the discard pile."""
    province = province_key_holding(game, source.owner, source.id)
    if province is None:
        return []
    # The discard is an effect rather than a cost: a cost resolves first, and the Province is read
    # off the Event, which by then is no longer in one.
    effects = [Discard(source.id, source.owner), PlaceInProvince(target.id, province)]
    discard = game.table.zones[ZoneKey(source.owner, ZoneRole.DYNASTY_DISCARD)]
    from_discard = any(card.id == target.id for card in discard.cards)
    if not from_discard:
        effects.append(GrantModifier(source.id, target.id, Stat.GOLD_COST, 1, Duration.PERMANENT))
    return effects


register_ability(
    "repairing_the_ruins",
    Ability(
        timing=ActionTiming.OPEN,
        label="Discard: rebuild this Province with a Holding you do not control",
        cost=no_cost,
        targets=_rebuildable_holdings,
        effects=_rebuild_the_province,
        located_at=(CardLocation.PROVINCE,),
    ),
)
