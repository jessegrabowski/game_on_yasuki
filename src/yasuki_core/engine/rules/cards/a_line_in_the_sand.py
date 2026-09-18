from yasuki_core.engine.players import PlayerId
from yasuki_core.engine.rules.abilities.costs import bow_cost, no_cost
from yasuki_core.engine.rules.abilities.model import Ability, CardLocation, InvestAbility
from yasuki_core.engine.rules.abilities.registry import (
    RecruitTiming,
    register_ability,
    register_invest,
    register_recruit_timing,
)
from yasuki_core.engine.rules.board.queries import (
    attack_targets,
    has_keyword,
    owned_personalities,
    remaining_look,
    top_of_deck,
)
from yasuki_core.engine.rules.rulebook.looks import PUT_BACK_ON_TOP
from yasuki_core.engine.rules.stats.card_values import effective_chi
from yasuki_core.engine.rules.vocabulary.actions import ActionTiming
from yasuki_core.engine.rules.units.membership import shares_unit
from yasuki_core.engine.rules.stats.keyword_grants import effective_keywords
from yasuki_core.engine.rules.attack_effects import attack_strength_against
from yasuki_core.engine.rules.effects import (
    Arrange,
    AttackEffect,
    Bow,
    Choose,
    CounterOnAttachedProvince,
    DrawCard,
    Effect,
    EndLook,
    LookAtTop,
    MoveToDeck,
    MoveToHand,
    PayGold,
    RangedAttack,
    RecruitCard,
    Rehonor,
    Show,
    ShuffleDeck,
    TakeFavor,
    Then,
)
from yasuki_core.engine.rules.state import GameState
from yasuki_core.engine.rules.triggers import TriggerContext, choice_resolver, on
from yasuki_core.engine.rules.vocabulary.game_events import EnteredPlay
from yasuki_core.engine.table import DeckKey, ZoneKey, ZoneRole
from yasuki_core.engine.rules.vocabulary import keywords
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

    Entering play from anywhere but a Province, it asks its controller which Province to attach
    to (CR, Fortification), so the token names the card rather than a
    Province and reads the answer once the choice has been made.
    """
    return [
        RecruitCard(target.id),
        Then((CounterOnAttachedProvince(target.id, WALL, 1),)),
    ]


register_ability(
    "agasha_beiru",
    Ability(
        timings=(ActionTiming.OPEN,),
        keywords=frozenset({keywords.EARTH}),
        label="Earth Open: Recruit a target Fortification in your discard pile and give its Province a +1 strength Wall token",
        cost=bow_cost,
        targets=_agasha_beiru_targets,
        effects=_agasha_beiru_effects,
    ),
)


# --- Beset from All Sides ---

BESET_GOLD = 2


def _beset_from_all_sides_cost(game: GameState, source: L5RCard) -> list[Effect]:
    return [PayGold(source.owner, BESET_GOLD, source.name)]


def _beset_from_all_sides_targets(game: GameState, source: L5RCard) -> list[str]:
    """Your unbowed Courtiers."""
    return [
        card.id
        for card in owned_personalities(game, source.owner)
        if not card.bowed and has_keyword(game, card, keywords.COURTIER)
    ]


def _beset_from_all_sides_effects(
    game: GameState, source: L5RCard, target: L5RCard
) -> list[Effect]:
    """Bow the Courtier and look at as many cards as his Chi. A Courtier of no Chi, or an empty
    deck, leaves only the draw."""
    seat = source.owner
    fate = DeckKey(seat, Side.FATE)
    seen = top_of_deck(game, fate, effective_chi(game, target))
    if not seen:
        return [Bow(target.id), DrawCard(seat)]
    return [
        Bow(target.id),
        LookAtTop(seat, fate, len(seen)),
        Choose(seat, seen, 0, 1, "beset_from_all_sides", source.id),
        DrawCard(seat),
    ]


@choice_resolver("beset_from_all_sides", prompt="You may put one at the bottom of your deck")
def _resolve_beset_from_all_sides(
    game: GameState, source_id: str, chosen: tuple[str, ...], seat: PlayerId
) -> list[Effect]:
    """The chosen card goes to the bottom of the deck and the rest go back on top in the order the
    seat gives, then the draw waiting behind the choice takes whatever ended on top."""
    fate = DeckKey(seat, Side.FATE)
    to_bottom = [MoveToDeck(card_id, fate, from_bottom=0) for card_id in chosen]
    rest = tuple(card_id for card_id in remaining_look(game) if card_id not in chosen)
    if not rest:
        return [*to_bottom, EndLook()]
    return [*to_bottom, Arrange(seat, rest, PUT_BACK_ON_TOP, source_id)]


register_ability(
    "beset_from_all_sides",
    Ability(
        timings=(ActionTiming.OPEN,),
        keywords=frozenset({keywords.POLITICAL}),
        label="Political Open, 2 Gold: Bow your target unbowed Courtier. Look at a number of cards "
        "on the top of your Fate deck equal to his Chi. You may put one at the bottom of your "
        "deck. Put the rest back in any order. Draw a card.",
        cost=_beset_from_all_sides_cost,
        targets=_beset_from_all_sides_targets,
        effects=_beset_from_all_sides_effects,
        located_at=(CardLocation.HAND,),
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
# "Fear, Melee, and Ranged targeting this Follower have -2 strength" covers every kind there is, so
# the penalty asks nothing about which one arrived.
KHAN_ATTACK_PENALTY = -2


@attack_strength_against("legion_of_the_khan")
def _legion_of_the_khan_attack_strength(
    game: GameState, card: L5RCard, target: L5RCard, attack: AttackEffect
) -> int:
    """ "Targeting this Follower" means every kind of attack, but only the ones aimed at her."""
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
    """Fetch another copy out of the Fate deck, or nothing when the deck holds none. The Invest is
    then a pure surcharge, which the card does not forbid paying."""
    seat = source.owner
    deck = game.table.decks[DeckKey(seat, Side.FATE)].cards
    copies = tuple(card.id for card in deck if card.printed_id == "stockpiled_weapon")
    if not copies:
        return []
    return [Choose(seat, copies, 1, 1, "stockpiled_weapon", source.id)]


register_invest("stockpiled_weapon", InvestAbility((1,), _stockpiled_weapon_invest))


# --- The Ivory Courtroom ---


@on(EnteredPlay, "the_ivory_courtroom")
def _the_ivory_courtroom_entered_play(ctx: TriggerContext) -> list[Effect]:
    """After this Holding enters play, take the Imperial Favor and rehonor one of your
    Personalities (if able)."""
    if ctx.event.card_id != ctx.card.id:
        return []
    dishonorable = tuple(
        card.id for card in owned_personalities(ctx.game, ctx.card.owner) if card.dishonorable
    )
    effects: list[Effect] = [TakeFavor(ctx.card.owner)]
    if dishonorable:
        effects.append(
            Choose(ctx.card.owner, dishonorable, 1, 1, "the_ivory_courtroom", ctx.card.id)
        )
    return effects


@choice_resolver("the_ivory_courtroom", prompt="Rehonor one of your Personalities")
def _resolve_the_ivory_courtroom(
    game: GameState, source_id: str, chosen: tuple[str, ...], seat: PlayerId
) -> list[Effect]:
    return [Rehonor(chosen[0])]


# "You may Recruit this Holding as a Political Open action." Its bow for 2 Gold is printed gold
# production and needs no handler.
register_recruit_timing(
    "the_ivory_courtroom",
    RecruitTiming(ActionTiming.OPEN, keywords=frozenset({keywords.POLITICAL})),
)
