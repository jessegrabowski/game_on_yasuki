from yasuki_core.engine.players import PlayerId
from yasuki_core.engine.rules.abilities import (
    Ability,
    CardLocation,
    bow_cost,
    no_cost,
    register_ability,
    register_event_entry,
)
from yasuki_core.engine.rules.actions import ActionTiming
from yasuki_core.engine.rules.economy import SELF_GRANT, register_self_grant
from yasuki_core.engine.rules.effects import (
    AdjustCounter,
    Choose,
    CreateToken,
    Destroy,
    Discard,
    Effect,
    GainHonor,
    GrantModifier,
    PlaceInProvince,
    Straighten,
)
from yasuki_core.engine.rules.equip import creation_targets
from yasuki_core.engine.rules.events import Destroyed, EnteredPlay, ProducedGold, ProducingGold
from yasuki_core.engine.rules.legality import province_key_holding
from yasuki_core.engine.rules.modifiers import Duration, Stat
from yasuki_core.engine.rules.payments import offer_self_grant
from yasuki_core.engine.rules.state import GameState, once_per_turn, used_this_turn
from yasuki_core.engine.rules.triggers import TriggerContext, choice_resolver, on
from yasuki_core.engine.table import DeckKey, ZoneKey, ZoneRole
from yasuki_core.game_pieces.cards import L5RCard
from yasuki_core.game_pieces.constants import Side
from yasuki_core.game_pieces.counters import MINUS_1F
from yasuki_core.game_pieces.prints import HoldingPrint, PersonalityPrint


# --- Dull Tanto ---


def _dull_tanto_targets(game: GameState, source: L5RCard) -> list[str]:
    """Every Personality on the board. The card says "a target Personality" and narrows it no
    further, so the controller's own are legal targets."""
    return [
        card.id
        for card in game.table.battlefield.cards
        if isinstance(card.printed, PersonalityPrint)
    ]


def _dull_tanto_effects(game: GameState, source: L5RCard, target: L5RCard) -> list[Effect]:
    """Two -1F tokens on the target, then destroy this Item. Two separate tokens rather than one
    worth -2F, so an effect that removes a single token removes only 1 Force."""
    return [
        AdjustCounter(target.id, MINUS_1F, 2),
        Destroy(source.id, source.owner),
    ]


register_ability(
    "dull_tanto",
    Ability(
        timings=(ActionTiming.OPEN,),
        label="Open: give a Personality two -1F tokens and destroy this Item",
        cost=no_cost,
        targets=_dull_tanto_targets,
        effects=_dull_tanto_effects,
    ),
)


# --- Outlying Farms ---


OUTLYING_FARMS_GRANT = 2

register_self_grant("outlying_farms", OUTLYING_FARMS_GRANT)


@on(ProducingGold, "outlying_farms")
def _outlying_farms_producing_gold(ctx: TriggerContext) -> list[Effect]:
    """ "Before this Holding bows to produce Gold, you may give it +2GP." Offered in the window, so
    the grant is inside the yield the bow reads."""
    return offer_self_grant(
        ctx,
        f"Give Outlying Farms +{OUTLYING_FARMS_GRANT}GP? It is destroyed after it bows.",
        "outlying_farms_grant",
    )


@choice_resolver("outlying_farms_grant")
def _resolve_outlying_farms_grant(
    game: GameState, source_id: str | None, chosen: tuple[str, ...], seat: PlayerId
) -> list[Effect]:
    if not chosen:
        return []
    card = game.table.cards_by_id[chosen[0]]
    once_per_turn(game, card, SELF_GRANT)
    return [
        GrantModifier(
            card.id,
            card.id,
            Stat.GOLD_PRODUCTION,
            OUTLYING_FARMS_GRANT,
            Duration.UNTIL_END_OF_TURN,
        )
    ]


@on(ProducedGold, "outlying_farms")
def _outlying_farms_produced_gold(ctx: TriggerContext) -> list[Effect]:
    """ "...if you did, destroy it after it bows." The price waits for the bow, so the Gold the grant
    bought reaches the pool before the card leaves play."""
    if ctx.event.card_id != ctx.card.id or not used_this_turn(ctx.game, ctx.card, SELF_GRANT):
        return []
    return [Destroy(ctx.card.id, ctx.card.owner)]


# --- Repairing the Ruins ---


def _repairing_the_ruins_targets(game: GameState, source: L5RCard) -> list[str]:
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


def _repairing_the_ruins_effects(game: GameState, source: L5RCard, target: L5RCard) -> list[Effect]:
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
        timings=(ActionTiming.OPEN,),
        label="Economic Open: Discard this Event to refill its Province with a non-Unique Holding you control no copies of",
        cost=no_cost,
        targets=_repairing_the_ruins_targets,
        effects=_repairing_the_ruins_effects,
        located_at=(CardLocation.PROVINCE,),
    ),
)


# --- Siege of the Great Wall ---

register_event_entry("siege_of_the_great_wall")


# --- The Forgotten ---


FORGOTTEN_DEAD = "forgotten_dead"
FORGOTTEN_HONOR_LOSS = 2


def _the_forgotten_entered_play_or_destroyed(ctx: TriggerContext) -> list[Effect]:
    """Lose 2 Honor and Equip another of the dead to a Personality.

    The Honor is lost whether or not there is anyone left to carry them, since the card asks for no
    target before charging it.
    """
    if ctx.event.card_id != ctx.card.id:
        return []
    seat = ctx.card.owner
    dead = ctx.game.table.creatable_tokens[FORGOTTEN_DEAD]
    effects: list[Effect] = [GainHonor(seat, -FORGOTTEN_HONOR_LOSS)]
    bearers = tuple(bearer.id for bearer in creation_targets(ctx.game, seat, dead))
    if bearers:
        effects.append(Choose(seat, bearers, 1, 1, "the_forgotten", ctx.card.id))
    return effects


# "After this Follower enters play or is destroyed" — one clause, so one handler on both events.
on(EnteredPlay, "the_forgotten")(_the_forgotten_entered_play_or_destroyed)
on(Destroyed, "the_forgotten")(_the_forgotten_entered_play_or_destroyed)


@choice_resolver("the_forgotten", prompt="Attach the Undead Follower to your target Personality")
def _resolve_the_forgotten(
    game: GameState, source_id: str, chosen: tuple[str, ...], seat: PlayerId
) -> list[Effect]:
    return [CreateToken(FORGOTTEN_DEAD, seat, source_id, attach_to=chosen[0])]


# --- Verdant Wilds ---


def _verdant_wilds_targets(game: GameState, source: L5RCard) -> list[str]:
    """The controller's own bowed cards in play: "your target card" is one this seat owns.

    Narrowed to the bowed because straightening presupposes one, and no further. A card another card
    forbids to straighten stays on the list — that prohibition is the other card's to enforce when
    the effect resolves, not this one's to read while choosing targets.
    """
    return [
        card.id
        for card in game.table.battlefield.cards
        if card.owner is source.owner and card.bowed
    ]


def _verdant_wilds_effects(game: GameState, source: L5RCard, target: L5RCard) -> list[Effect]:
    return [Straighten(target.id)]


register_ability(
    "verdant_wilds",
    Ability(
        timings=(ActionTiming.OPEN,),
        label="Bow: straighten your target card",
        cost=bow_cost,
        targets=_verdant_wilds_targets,
        effects=_verdant_wilds_effects,
    ),
)
