from yasuki_core.engine.players import PlayerId
from yasuki_core.engine.rules.board.seats import cards_in_play, cards_named
from yasuki_core.engine.rules.abilities.costs import bow_cost, no_cost
from yasuki_core.engine.rules.abilities.idioms import plus_one_gp_this_turn, register_event_entry
from yasuki_core.engine.rules.abilities.model import Ability, CardLocation
from yasuki_core.engine.rules.abilities.registry import register_ability
from yasuki_core.engine.rules.board.queries import (
    ATTACK_TARGET,
    attack_targets,
    has_keyword,
    owned_holdings,
    owned_personalities,
    personalities_in_play,
)
from yasuki_core.engine.rules.stats.keyword_grants import effective_keywords, keyword_grant
from yasuki_core.engine.rules.stats.card_values import effective_chi, effective_personal_honor
from yasuki_core.engine.rules.stats.province_strength import province_strength_grant
from yasuki_core.engine.rules.gold.discounts import Purchase, action_discount
from yasuki_core.engine.rules.gold.production import effective_gold_production, gold_handler
from yasuki_core.engine.rules.gold.producers import reachable_gold
from yasuki_core.engine.rules.action_record import action_round
from yasuki_core.engine.rules.legality import permitted_timings_in, recruit_cost
from yasuki_core.engine.rules.rulebook.equip import is_spell
from yasuki_core.engine.table import ZoneKey
from yasuki_core.engine.rules.effects import (
    AdjustCounter,
    Ask,
    Bow,
    Choose,
    CreateToken,
    Destroy,
    Effect,
    GainHonor,
    GrantKeyword,
    GrantModifier,
    IgnoreHonorRequirements,
    MeleeAttack,
    PayGold,
    RecruitCard,
    register_honor_loss_shield,
    Straighten,
    Then,
)
from yasuki_core.engine.rules.vocabulary.game_events import CardDiscarded, Destroyed, EnteredPlay
from yasuki_core.engine.rules.vocabulary.actions import (
    ActionTiming,
    ActivateAbility,
)
from yasuki_core.engine.rules.vocabulary.modifiers import Duration, Stat
from yasuki_core.engine.rules.rulebook.kharmic import is_kharmic_action
from yasuki_core.engine.rules.state import GameState
from yasuki_core.engine.rules.triggers import TriggerContext, choice_resolver, on
from yasuki_core.engine.rules.board.queries import province_holdings
from yasuki_core.engine.rules.vocabulary import keywords
from yasuki_core.game_pieces.cards import L5RCard
from yasuki_core.game_pieces.constants import AttachmentType
from yasuki_core.game_pieces.prints import AttachmentPrint
from yasuki_core.game_pieces.counters import SINCERITY, WEALTH


# --- Blood of Fu Leng ---

# "give a target Personality -1C", as the card prints it.
BLOOD_OF_FU_LENG_PENALTY = -1


@on(CardDiscarded, "blood_of_fu_leng")
def _blood_of_fu_leng_card_discarded(ctx: TriggerContext) -> list[Effect]:
    """Put the Chi penalty to a target Personality once a Kharmic action has discarded the card.

    A Kharmic action is the only discard it reacts to, so reaching the pile any other way (pitched
    to hand size or discarded by another card) does nothing.
    """
    if ctx.event.card_id != ctx.card.id:
        return []
    if not is_kharmic_action(ctx.game):
        return []
    targets = tuple(card.id for card in personalities_in_play(ctx.game))
    if not targets:
        return []
    return [Choose(ctx.card.owner, targets, 1, 1, "blood_of_fu_leng", ctx.card.id)]


@choice_resolver("blood_of_fu_leng", prompt="Choose a Personality to give -1C")
def _resolve_blood_of_fu_leng(
    game: GameState, source_id: str, chosen: tuple[str, ...], seat: PlayerId
) -> list[Effect]:
    return [
        GrantModifier(
            source_id, chosen[0], Stat.CHI, BLOOD_OF_FU_LENG_PENALTY, Duration.UNTIL_END_OF_TURN
        )
    ]


# --- Confront Your Truth ---

register_event_entry("confront_your_truth")


# --- Draw Strength from Your Oaths ---


def _draw_strength_from_your_oaths_targets(game: GameState, source: L5RCard) -> list[str]:
    """Your unbowed Personalities. The Honesty rider, Melee equal to their Force instead, has no
    model for Bushido Virtues to read and is not written."""
    return [card.id for card in owned_personalities(game, source.owner) if not card.bowed]


def _draw_strength_from_your_oaths_effects(
    game: GameState, source: L5RCard, target: L5RCard
) -> list[Effect]:
    """Bow the target, then aim the Melee Attack at a card in the enemy army, if there is one. The
    Choose carries the bowed Personality, whose Chi the resolver reads."""
    bowed: list[Effect] = [Bow(target.id)]
    aimable = tuple(attack_targets(game, source))
    if not aimable:
        return bowed
    return [*bowed, Choose(source.owner, aimable, 1, 1, "draw_strength_from_your_oaths", target.id)]


@choice_resolver("draw_strength_from_your_oaths", prompt="Target the Melee Attack")
def _resolve_draw_strength_from_your_oaths(
    game: GameState, source_id: str, chosen: tuple[str, ...], seat: PlayerId
) -> list[Effect]:
    """Strength is the bowed Personality's Chi, plus one per Courtier and Shugenja you control when
    they are a Yojimbo."""
    bowed = game.table.cards_by_id[source_id]
    strength = effective_chi(game, bowed)
    if keywords.YOJIMBO in effective_keywords(game, bowed):
        strength += sum(
            has_keyword(game, card, keywords.COURTIER) or has_keyword(game, card, keywords.SHUGENJA)
            for card in owned_personalities(game, seat)
        )
    return [MeleeAttack(strength, chosen[0], seat)]


register_ability(
    "draw_strength_from_your_oaths",
    Ability(
        timings=(ActionTiming.BATTLE,),
        cost=no_cost,
        targets=_draw_strength_from_your_oaths_targets,
        targeting_message="your unbowed Personality",
        effects=_draw_strength_from_your_oaths_effects,
        located_at=(CardLocation.HAND,),
    ),
)


# --- Harvested Land ---


def _harvested_land_cost(game: GameState, source: L5RCard) -> list[Effect]:
    return [Bow(source.id), Destroy(source.id, source.owner)]


def _harvested_land_targets(game: GameState, card: L5RCard) -> list[str]:
    return [farm.id for farm in owned_holdings(game, card.owner, keywords.FARM) if farm is not card]


register_ability(
    "harvested_land",
    Ability(
        timings=(ActionTiming.OPEN,),
        cost=_harvested_land_cost,
        targets=_harvested_land_targets,
        effects=plus_one_gp_this_turn,
        hits_every_target=True,
    ),
)


# --- Heart of Honor ---

HEART_OF_HONOR_HONORABLE = 3
HEART_OF_HONOR_FORCE_BONUS = 2
HEART_OF_HONOR_HONOR_GAIN = 1


def _heart_of_honor_targets(game: GameState, source: L5RCard) -> list[str]:
    return [card.id for card in owned_personalities(game, source.owner)]


def _heart_of_honor_effects(game: GameState, source: L5RCard, target: L5RCard) -> list[Effect]:
    """Straighten the target, and pay the honorable half only under the Battle designator.

    "If this was taken as a Battle action" is read off the Action Round the card was played in
    rather than off the action: the card prints Battle/Open, and a battle's Combat Segment is the
    only round that permits the Battle half (CR, Battle Sequence).
    """
    effects: list[Effect] = [Straighten(target.id)]
    if ActionTiming.BATTLE not in permitted_timings_in(game, action_round(game), source.owner):
        return effects
    if effective_personal_honor(game, target) < HEART_OF_HONOR_HONORABLE:
        return effects
    effects.append(
        GrantModifier(
            source.id,
            target.id,
            Stat.FORCE,
            HEART_OF_HONOR_FORCE_BONUS,
            Duration.UNTIL_END_OF_TURN,
        )
    )
    effects.append(GainHonor(source.owner, HEART_OF_HONOR_HONOR_GAIN))
    return effects


register_ability(
    "heart_of_honor",
    Ability(
        timings=(ActionTiming.BATTLE, ActionTiming.OPEN),
        keywords=frozenset({keywords.BUSHIDO_VIRTUE}),
        cost=no_cost,
        targets=_heart_of_honor_targets,
        targeting_message="your Personality",
        effects=_heart_of_honor_effects,
        located_at=(CardLocation.HAND,),
    ),
)


# --- I Do Not Forget ---


def _i_do_not_forget_targets(game: GameState, source: L5RCard) -> list[str]:
    return [card.id for card in personalities_in_play(game) if card.dishonorable]


def _i_do_not_forget_effects(game: GameState, source: L5RCard, target: L5RCard) -> list[Effect]:
    """Their controller loses Honor equal to their printed Personal Honor or 1, whichever is
    higher. The face-up hand discard and "you may not ally with them" are not modeled: nothing
    reveals a hand card to another player's action, and alliances do not exist."""
    return [GainHonor(target.owner, -max(target.personal_honor, 1), source_id=source.id)]


register_ability(
    "i_do_not_forget",
    Ability(
        timings=(ActionTiming.OPEN,),
        keywords=frozenset({keywords.POLITICAL}),
        cost=no_cost,
        targets=_i_do_not_forget_targets,
        targeting_message="a dishonorable Personality",
        effects=_i_do_not_forget_effects,
        located_at=(CardLocation.HAND,),
    ),
)


# --- Impressment ---

register_event_entry("impressment", timing=ActionTiming.DYNASTY)


# --- Jade Legion ---

JADE_LEGION_MELEE = 3


def _jade_legion_effects(game: GameState, source: L5RCard, target: L5RCard) -> list[Effect]:
    """The attack alone. Whether it destroyed anything is not known until it resolves, so the
    straighten rides on the destruction rather than being queued behind the attack."""
    return [MeleeAttack(JADE_LEGION_MELEE, target.id, source.owner)]


@on(Destroyed, "jade_legion")
def _jade_legion_destroyed(ctx: TriggerContext) -> list[Effect]:
    """Straighten the Legion when its own attack destroys a Shadowlands card.

    ``Destroyed`` names the seat that caused it rather than the card, so the action being resolved
    is what says the destruction was this Follower's doing.
    """
    action = ctx.game.action
    if not isinstance(action, ActivateAbility) or action.card_id != ctx.card.id:
        return []
    destroyed = ctx.game.table.cards_by_id.get(ctx.event.card_id)
    if destroyed is None or keywords.SHADOWLANDS not in effective_keywords(ctx.game, destroyed):
        return []
    return [Straighten(ctx.card.id)]


register_ability(
    "jade_legion",
    Ability(
        timings=(ActionTiming.BATTLE,),
        cost=bow_cost,
        targets=attack_targets,
        targeting_message=ATTACK_TARGET,
        effects=_jade_legion_effects,
    ),
)


# --- Makeshift Fortifications ---


@province_strength_grant("makeshift_fortifications")
def _makeshift_fortifications_province_strength(
    game: GameState, card: L5RCard, province: ZoneKey
) -> int:
    """ "This Province has +3PS." A continuous grant read off the board, so it lasts exactly as long
    as the Fortification stays attached and needs no bookkeeping when it leaves."""
    return 3


# --- Mishime Sensei ---


MISHIMES_ONI = "oni_personality_variable_chi"
ONI_COST = 5
# "You pay :g2: less ... for each player who controls any :shadowlands: cards."
MISHIME_SENSEI_DISCOUNT = 2

register_honor_loss_shield("mishime_sensei")


@action_discount("mishime_sensei")
def _mishime_sensei_action_discount(game: GameState, sensei: L5RCard, purchase: Purchase) -> int:
    """2 Gold off a Maho action or a Spell for each player who controls a Shadowlands card.

    Mishime prints the Shadowlands keyword, so his controller always counts, and his own Open
    ability is a Maho action through the Maho icon beside his title.
    """
    for_spell = purchase.card is not None and is_spell(purchase.card)
    if not purchase.has_keyword(keywords.MAHO) and not for_spell:
        return 0
    shadowlands_seats = sum(
        any(has_keyword(game, card, keywords.SHADOWLANDS) for card in cards_in_play(game, seat))
        for seat in game.table.seats
    )
    return MISHIME_SENSEI_DISCOUNT * shadowlands_seats


@on(EnteredPlay, "mishime_sensei")
def _mishime_sensei_entered_play(ctx: TriggerContext) -> list[Effect]:
    """Mishime Sensei: grant its controller the ignore-Honor-Requirements waiver as it enters
    play."""
    if ctx.event.card_id != ctx.card.id:
        return []
    return [IgnoreHonorRequirements(ctx.card.owner)]


def _mishime_sensei_of(game: GameState, seat: PlayerId) -> L5RCard:
    """The Sensei whose ability is resolving. The question it asked carries the Personality rather
    than the Sensei, and a seat has the one Sensei, in play since it bowed to pay."""
    return cards_named(game, seat, "mishime_sensei")[0]


@choice_resolver("mishime_sensei")
def _resolve_mishime_sensei(
    game: GameState, source_id: str, chosen: tuple[str, ...], seat: PlayerId
) -> list[Effect]:
    """Destroy the bowed Personality if the seat said yes, then make the Oni either way.

    The Oni's Force is read here rather than baked into the question, but still before the
    destruction resolves: the Chi it copies belongs to a Personality who is about to stop having
    one. Sparing the Personality only lends the Oni for the turn.
    """
    target = game.table.cards_by_id[source_id]
    sensei = _mishime_sensei_of(game, seat)
    destroyed = bool(chosen)
    effects: list[Effect] = [Destroy(source_id, seat)] if destroyed else []
    effects.append(
        CreateToken(
            MISHIMES_ONI,
            seat,
            sensei.id,
            stats=((Stat.FORCE, effective_chi(game, target)),),
            banish_at_turn_end=not destroyed,
        )
    )
    return effects


def _mishime_sensei_cost(game: GameState, source: L5RCard) -> list[Effect]:
    return [Bow(source.id), PayGold(source.owner, ONI_COST, source.name)]


def _mishime_sensei_targets(game: GameState, source: L5RCard) -> list[str]:
    return [card.id for card in owned_personalities(game, source.owner) if not card.bowed]


def _mishime_sensei_effects(game: GameState, source: L5RCard, target: L5RCard) -> list[Effect]:
    """Bow the target, then ask whether to finish him. Both answers make the Oni, so the question
    settles how long it stays rather than whether it arrives."""
    return [
        Bow(target.id),
        Ask(
            source.owner,
            f"Destroy {target.name} to keep the Oni past this turn?",
            "mishime_sensei",
            subjects=(target.id,),
            source_id=target.id,
        ),
    ]


register_ability(
    "mishime_sensei",
    Ability(
        timings=(ActionTiming.OPEN,),
        cost=_mishime_sensei_cost,
        targets=_mishime_sensei_targets,
        targeting_message="your unbowed Personality",
        effects=_mishime_sensei_effects,
    ),
)


# --- Modest Farm ---


@choice_resolver(
    "modest_farm_straighten", prompt="Destroy Modest Farm to straighten the card it recruited"
)
def _resolve_modest_farm_straighten(
    game: GameState, source_id: str, chosen: tuple[str, ...], seat: PlayerId
) -> list[Effect]:
    # source_id is the recruited target; chosen holds Modest Farm's id when its controller
    # sacrifices it to straighten the target.
    if not chosen:
        return []
    return [Destroy(chosen[0], seat), Straighten(source_id)]


def _modest_farm_targets(game: GameState, card: L5RCard) -> list[str]:
    """The face-up Province Holdings ``card``'s controller can afford to bring into play. The seat
    pays each target's recruit cost from its pool and unbowed producers, minus ``card``'s own yield:
    the ability bows or destroys ``card`` as its cost, so it can no longer produce toward the
    recruit."""
    seat = card.owner
    affordable: list[str] = []
    for target_id in province_holdings(game, seat):
        target = game.table.cards_by_id[target_id]
        forfeited = effective_gold_production(game, card, targets=(target,))
        if recruit_cost(game, target) <= reachable_gold(game, seat, target) - forfeited:
            affordable.append(target_id)
    return affordable


def _modest_farm_effects(game: GameState, source: L5RCard, target: L5RCard) -> list[Effect]:
    """Recruit the target out of sequence, then offer to destroy Modest Farm to straighten it. The
    offer is deferred so it follows the recruit and anything the recruited card's entry causes."""
    question = f"Destroy {source.name} to straighten {target.name}?"
    return [
        RecruitCard(target.id, renew=keywords.FARM in target.keywords),
        Then(
            (
                Ask(
                    source.owner,
                    question,
                    "modest_farm_straighten",
                    subjects=(source.id,),
                    source_id=target.id,
                ),
            )
        ),
    ]


register_ability(
    "modest_farm",
    Ability(
        timings=(ActionTiming.OPEN,),
        cost=bow_cost,
        targets=_modest_farm_targets,
        targeting_message="a Holding in your Province",
        effects=_modest_farm_effects,
    ),
)


# --- Rural Market ---


@on(EnteredPlay, "rural_market")
def _rural_market_entered_play(ctx: TriggerContext) -> list[Effect]:
    """After this Holding enters play, give it a +1GP Wealth token."""
    if ctx.event.card_id != ctx.card.id:
        return []
    return [AdjustCounter(ctx.card.id, WEALTH, 1)]


@on(Destroyed, "rural_market")
def _rural_market_destroyed(ctx: TriggerContext) -> list[Effect]:
    """After your Farm is destroyed, give this Holding a +1GP Wealth token."""
    if ctx.event.card_id == ctx.card.id:
        # Rural Market carries Farm itself, and a Holding in a discard pile can hold no token
        # (CR, Tokens), so its own destruction pays it nothing.
        return []
    destroyed = ctx.game.table.cards_by_id.get(ctx.event.card_id)
    if destroyed is None or destroyed.owner is not ctx.card.owner:
        return []
    if keywords.FARM not in effective_keywords(ctx.game, destroyed):
        return []
    return [AdjustCounter(ctx.card.id, WEALTH, 1)]


def _rural_market_cost(game: GameState, source: L5RCard) -> list[Effect]:
    return [AdjustCounter(source.id, WEALTH, -1)]


def _rural_market_targets(game: GameState, card: L5RCard) -> list[str]:
    # "Not produced Gold this turn" is satisfied for any bowed Farm: production only happens in the
    # Dynasty phase, after this Open ability's Action-phase window.
    return [farm.id for farm in owned_holdings(game, card.owner, keywords.FARM) if farm.bowed]


def _rural_market_effects(game: GameState, source: L5RCard, target: L5RCard) -> list[Effect]:
    return [Straighten(target.id)]


register_ability(
    "rural_market",
    Ability(
        timings=(ActionTiming.OPEN,),
        cost=_rural_market_cost,
        targets=_rural_market_targets,
        targeting_message="your Farm",
        effects=_rural_market_effects,
        tireless=True,
    ),
)


# --- Sapphire Mine ---


EXPENSIVE_ITEM = 6


@gold_handler("sapphire_mine")
def _sapphire_mine_gold(
    card: L5RCard, game: GameState, seat: PlayerId, targets: tuple[L5RCard, ...]
) -> int:
    """+1GP when paying for a single Item and nothing else, and +1GP more when it costs 6 or more.

    "A single Item only" means the whole payment: paying for two cards at once, or for anything
    that is not an Item, leaves the Mine at its printed rate.
    """
    if len(targets) != 1:
        return card.gold_production
    item = targets[0]
    if (
        not isinstance(item.printed, AttachmentPrint)
        or item.attachment_type is not AttachmentType.ITEM
    ):
        return card.gold_production
    return card.gold_production + 1 + (1 if item.gold_cost >= EXPENSIVE_ITEM else 0)


@keyword_grant("sapphire_mine")
def _sapphire_mine_keywords(card: L5RCard, game: GameState, seat: PlayerId) -> tuple[str, ...]:
    """Renew while it holds any Sincerity token.

    Recruiting reads Renew as the card enters play and spends its Sincerity afterwards, so a Mine
    that accrued even one token refills the Province it vacated face-up.
    """
    return (keywords.RENEW,) if card.counters.get(SINCERITY.key, 0) else ()


@on(EnteredPlay, "sapphire_mine")
def _sapphire_mine_entered_play(ctx: TriggerContext) -> list[Effect]:
    """Sincerity: after this Holding enters play, if it accrued two or more Sincerity tokens, give
    it a +1GP Wealth token."""
    if ctx.event.card_id != ctx.card.id:
        return []
    if ctx.card.counters.get(SINCERITY.key, 0) < 2:
        return []
    return [AdjustCounter(ctx.card.id, WEALTH, 1)]


# --- Shinjo Fields ---


CAVALRY_FOLLOWER = "cavalry"


def _shinjo_fields_targets(game: GameState, source: L5RCard) -> list[str]:
    return [personality.id for personality in owned_personalities(game, source.owner)]


def _shinjo_fields_effects(game: GameState, source: L5RCard, target: L5RCard) -> list[Effect]:
    """Cavalry for the rest of the turn, then the offer to spend the Holding on a rider to match.

    The keyword is given whatever the seat says next: only the Follower is optional.
    """
    return [
        GrantKeyword(source.id, target.id, keywords.CAVALRY, Duration.UNTIL_END_OF_TURN),
        Ask(
            source.owner,
            f"Destroy {source.name} to Equip a Cavalry Follower to {target.name}?",
            "shinjo_fields",
            subjects=(target.id,),
            source_id=source.id,
        ),
    ]


@choice_resolver("shinjo_fields")
def _resolve_shinjo_fields(
    game: GameState, source_id: str, chosen: tuple[str, ...], seat: PlayerId
) -> list[Effect]:
    """The Holding is what the Follower costs, so it goes before the rider arrives."""
    if not chosen:
        return []
    return [
        Destroy(source_id, seat),
        CreateToken(CAVALRY_FOLLOWER, seat, source_id, attach_to=chosen[0]),
    ]


register_ability(
    "shinjo_fields",
    Ability(
        timings=(ActionTiming.OPEN,),
        cost=bow_cost,
        targets=_shinjo_fields_targets,
        targeting_message="your Personality",
        effects=_shinjo_fields_effects,
    ),
)
