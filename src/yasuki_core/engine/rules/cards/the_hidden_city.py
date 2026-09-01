from yasuki_core.engine.players import PlayerId
from yasuki_core.engine.rules.abilities import (
    Ability,
    CardLocation,
    itself,
    no_cost,
    register_ability,
)
from yasuki_core.engine.rules.actions import ActionTiming, BattleDesignator
from yasuki_core.engine.rules.effects import (
    Choose,
    Effect,
    GrantProvinceStrength,
    MoveToHand,
    Show,
    ShuffleDeck,
)
from yasuki_core.engine.rules.equip import attach_restriction
from yasuki_core.engine.rules.events import EnteredPlay
from yasuki_core.engine.rules.economy import effective_keywords
from yasuki_core.engine.rules.modifiers import Duration
from yasuki_core.engine.rules.state import GameState
from yasuki_core.engine.rules.triggers import choice_resolver, on
from yasuki_core.engine.table import DeckKey, ZoneKey, ZoneRole
from yasuki_core.game_pieces import keywords
from yasuki_core.game_pieces.cards import L5RCard
from yasuki_core.game_pieces.constants import Side


# --- Brothers in Arms ---


@attach_restriction("brothers_in_arms")
def _brothers_in_arms_attach_restriction(
    game: GameState, personality: L5RCard, card: L5RCard
) -> bool:
    return keywords.SAMURAI in effective_keywords(game, personality)


def _brothers_in_arms_copies(game: GameState, seat: PlayerId) -> tuple[str, ...]:
    """Other copies to fetch, discard pile before Fate deck.

    The card searches "your Fate discard pile, then deck", so the deck is read only when the discard
    holds none — a player never chooses to leave a discarded copy and shuffle for one instead.
    """
    discard = game.table.zones[ZoneKey(seat, ZoneRole.FATE_DISCARD)].cards
    found = [card.id for card in discard if card.printed_id == "brothers_in_arms"]
    if found:
        return tuple(found)
    deck = game.table.decks[DeckKey(seat, Side.FATE)].cards
    return tuple(card.id for card in deck if card.printed_id == "brothers_in_arms")


@choice_resolver("brothers_in_arms", prompt="Take another Brothers in Arms")
def _resolve_brothers_in_arms(
    game: GameState, source_id: str, chosen: tuple[str, ...], seat: PlayerId
) -> list[Effect]:
    """Show the copy and take it. A copy pulled out of the deck costs a shuffle; one lifted off the
    discard pile does not, since the discard pile is public and its order carries no information."""
    taken = chosen[0]
    from_deck = any(card.id == taken for card in game.table.decks[DeckKey(seat, Side.FATE)].cards)
    effects: list[Effect] = [Show(taken), MoveToHand(taken, seat)]
    if from_deck:
        effects.append(ShuffleDeck(DeckKey(seat, Side.FATE)))
    return effects


@on(EnteredPlay, "brothers_in_arms")
def _brothers_in_arms_entered_play(ctx) -> list[Effect]:
    """Fetch another copy, but only on the arrival the card names: this card's own, "from your
    hand".

    The event fires for every copy in play, so a trigger that reads "after *this* card enters play"
    has to check it is the one that arrived. An effect that attaches it from anywhere else raises
    nothing either, so the chain cannot feed itself off the discard pile it fills.
    """
    if ctx.event.card_id != ctx.card.id or not ctx.event.from_hand:
        return []
    seat = ctx.card.owner
    copies = _brothers_in_arms_copies(ctx.game, seat)
    if not copies:
        return []
    return [Choose(seat, copies, 1, 1, "brothers_in_arms", ctx.card.id)]


# --- Outer Walls ---

# "Give its province +3 strength", as the card prints it.
OUTER_WALLS_STRENGTH = 3


def _outer_walls_effects(game: GameState, source: L5RCard, target: L5RCard) -> list[Effect]:
    """Strengthen the Province the battle is being fought at — "its province" is the current
    battlefield's, which the card names rather than the seat choosing."""
    province = game.attack.current_province
    return [
        GrantProvinceStrength(source.id, province, OUTER_WALLS_STRENGTH, Duration.UNTIL_END_OF_TURN)
    ]


register_ability(
    "outer_walls",
    Ability(
        timings=(ActionTiming.BATTLE,),
        label="Battle: Even if you control no units at the current battlefield: Give its province "
        "+3 strength",
        cost=no_cost,
        targets=itself,
        effects=_outer_walls_effects,
        all_targets=True,
        located_at=(CardLocation.HAND,),
        battle=frozenset({BattleDesignator.ABSENT}),
    ),
)
