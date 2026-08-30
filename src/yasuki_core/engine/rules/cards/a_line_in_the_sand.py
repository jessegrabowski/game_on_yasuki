from yasuki_core.engine.players import PlayerId
from yasuki_core.engine.rules.abilities import (
    Ability,
    InvestAbility,
    bow_cost,
    register_ability,
    register_invest,
)
from yasuki_core.engine.rules.actions import ActionTiming
from yasuki_core.engine.rules.economy import effective_keywords
from yasuki_core.engine.rules.effects import (
    Choose,
    CounterOnAttachedProvince,
    Effect,
    MoveToHand,
    RecruitCard,
    Show,
    ShuffleDeck,
    Then,
)
from yasuki_core.engine.rules.state import GameState
from yasuki_core.engine.rules.triggers import choice_resolver
from yasuki_core.engine.table import DeckKey, ZoneKey, ZoneRole
from yasuki_core.game_pieces import keywords
from yasuki_core.game_pieces.cards import L5RCard
from yasuki_core.game_pieces.constants import Side
from yasuki_core.game_pieces.counters import WALL


# --- Agasha Beiru ---


def _agasha_beiru_targets(game: GameState, source: L5RCard) -> list[str]:
    """Fortifications in the seat's Dynasty discard pile."""
    discard = game.table.zones[ZoneKey(source.owner, ZoneRole.DYNASTY_DISCARD)].cards
    return [card.id for card in discard if keywords.FORTIFICATION in effective_keywords(game, card)]


def _agasha_beiru_effects(game: GameState, source: L5RCard, target: L5RCard) -> list[Effect]:
    """Recruit the Fortification out of the discard pile, then wall the Province it landed on.

    Entering play from anywhere but a Province, it asks its controller which Province to attach to
    (CR, Fortification) — so the token names the card rather than a Province, and finds the answer
    once the choice has been made.
    """
    return [
        RecruitCard(target.id),
        Then((CounterOnAttachedProvince(target.id, WALL, 1),)),
    ]


register_ability(
    "agasha_beiru",
    Ability(
        timings=(ActionTiming.OPEN,),
        label="Earth Open: Recruit a target Fortification in your discard pile and give its Province a +1 strength Wall token",
        cost=bow_cost,
        targets=_agasha_beiru_targets,
        effects=_agasha_beiru_effects,
    ),
)


# --- Stockpiled Weapon ---


@choice_resolver("stockpiled_weapon", prompt="Search your Fate deck for a Stockpiled Weapon")
def _resolve_stockpiled_weapon(
    game: GameState, source_id: str, chosen: tuple[str, ...], seat: PlayerId
) -> list[Effect]:
    return [
        Show(chosen[0]),
        MoveToHand(chosen[0], seat),
        ShuffleDeck(DeckKey(seat, Side.FATE)),
    ]


def _stockpiled_weapon_invest(game: GameState, source: L5RCard, amount: int) -> list[Effect]:
    """Fetch another copy out of the Fate deck, or nothing when the deck holds none — the Invest is
    then a pure surcharge, which the card does not forbid paying."""
    seat = source.owner
    deck = game.table.decks[DeckKey(seat, Side.FATE)].cards
    copies = tuple(card.id for card in deck if card.printed_id == "stockpiled_weapon")
    if not copies:
        return []
    return [Choose(seat, copies, 1, 1, "stockpiled_weapon", source.id)]


register_invest("stockpiled_weapon", InvestAbility((1,), _stockpiled_weapon_invest))
