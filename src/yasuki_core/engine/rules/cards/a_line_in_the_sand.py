from yasuki_core.engine.players import PlayerId
from yasuki_core.engine.rules.abilities import (
    Ability,
    InvestAbility,
    attack_targets,
    bow_cost,
    no_cost,
    register_ability,
    register_invest,
)
from yasuki_core.engine.rules.actions import ActionTiming
from yasuki_core.engine.rules.attachments import shares_unit
from yasuki_core.engine.rules.economy import effective_keywords
from yasuki_core.engine.rules.effects import (
    AttackEffect,
    Choose,
    CounterOnAttachedProvince,
    Effect,
    MoveToHand,
    RangedAttack,
    RecruitCard,
    Show,
    ShuffleDeck,
    Then,
    attack_strength_against,
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


# --- Ichigo's Guard ---

# "Fear, Melee, and Ranged targeting cards in this unit have -1 strength." The unit, not the card:
# the Guard covers the Personality it hangs on and every Follower beside it.
ICHIGOS_GUARD_PENALTY = -1


@attack_strength_against("ichigos_guard")
def _ichigos_guard_attack_strength(
    game: GameState, card: L5RCard, target: L5RCard, attack: AttackEffect
) -> int:
    """The unit is the reach: the Personality the Guard hangs on and every Follower beside it."""
    return ICHIGOS_GUARD_PENALTY if shares_unit(game, card, target) else 0


# --- Legion of the Khan ---

KHAN_RANGED = 3
# "Fear, Melee, and Ranged targeting this Follower have -2 strength" — every kind there is, so the
# penalty asks nothing about which one arrived.
KHAN_ATTACK_PENALTY = -2


@attack_strength_against("legion_of_the_khan")
def _legion_of_the_khan_attack_strength(
    game: GameState, card: L5RCard, target: L5RCard, attack: AttackEffect
) -> int:
    """ "Targeting this Follower" — every kind of attack, but only the ones aimed at her."""
    return KHAN_ATTACK_PENALTY if target is card else 0


def _legion_of_the_khan_effects(game: GameState, source: L5RCard, target: L5RCard) -> list[Effect]:
    return [RangedAttack(KHAN_RANGED, target.id, source.owner)]


register_ability(
    "legion_of_the_khan",
    Ability(
        timings=(ActionTiming.BATTLE,),
        label=f"Battle: Ranged {KHAN_RANGED} Attack",
        cost=no_cost,
        targets=attack_targets,
        effects=_legion_of_the_khan_effects,
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
