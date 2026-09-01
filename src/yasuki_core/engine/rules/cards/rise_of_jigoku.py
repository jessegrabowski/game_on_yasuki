from yasuki_core.engine.players import PlayerId
from yasuki_core.engine.rules.abilities import (
    Ability,
    bow_cost,
    bow_and_destroy,
    owned_holdings,
    owned_personalities,
    personalities_in_play,
    plus_one_gp_this_turn,
    spend_wealth,
    register_ability,
)
from yasuki_core.engine.rules.economy import (
    PlayerState,
    effective_chi,
    effective_gold_production,
    effective_keywords,
    gold_handler,
    keyword_grant,
    province_strength_grant,
)
from yasuki_core.engine.rules.legality import reachable_gold, recruit_cost
from yasuki_core.engine.table import ZoneKey
from yasuki_core.engine.rules.effects import (
    AdjustCounter,
    Ask,
    Bow,
    Choose,
    CreateToken,
    Destroy,
    Effect,
    GrantKeyword,
    GrantModifier,
    IgnoreHonorRequirements,
    PayGold,
    RecruitCard,
    Straighten,
    Then,
)
from yasuki_core.engine.rules.events import CardDiscarded, Destroyed, EnteredPlay
from yasuki_core.engine.rules.actions import ActionTiming, KharmicDraw, KharmicRefill
from yasuki_core.engine.rules.modifiers import Duration, Stat
from yasuki_core.engine.rules.state import GameState
from yasuki_core.engine.rules.triggers import TriggerContext, choice_resolver, on, province_holdings
from yasuki_core.game_pieces import keywords
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

    A Kharmic action is the only discard it reacts to, so reaching the pile any other way — pitched
    to hand size, or discarded by another card — does nothing.
    """
    if ctx.event.card_id != ctx.card.id:
        return []
    if not isinstance(ctx.game.action, KharmicDraw | KharmicRefill):
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


# --- Harvested Land ---


def _harvested_land_targets(game: GameState, card: L5RCard) -> list[str]:
    return [farm.id for farm in owned_holdings(game, card.owner, keywords.FARM) if farm is not card]


register_ability(
    "harvested_land",
    Ability(
        timings=(ActionTiming.OPEN,),
        label="Bow, destroy: give your other Farms +1 Gold Production",
        cost=bow_and_destroy,
        targets=_harvested_land_targets,
        effects=plus_one_gp_this_turn,
        all_targets=True,
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
    return next(
        card
        for card in game.table.battlefield.cards
        if card.printed_id == "mishime_sensei" and card.owner is seat
    )


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
        label=f"Open: Bow and pay {ONI_COST} gold to bow your Personality for an Oni of his Chi",
        cost=_mishime_sensei_cost,
        targets=_mishime_sensei_targets,
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
    # source_id is the recruited target; chosen holds Modest Farm's id when its controller sacrifices
    # it to straighten the target.
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
        label="Bow, pay a Holding's cost: recruit it from your Province out of sequence",
        cost=bow_cost,
        targets=_modest_farm_targets,
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
        label="Spend a Wealth token: straighten a Farm",
        cost=spend_wealth,
        targets=_rural_market_targets,
        effects=_rural_market_effects,
    ),
)


# --- Sapphire Mine ---


EXPENSIVE_ITEM = 6


@gold_handler("sapphire_mine")
def _sapphire_mine_gold(
    card: L5RCard, me: PlayerState, opponents: tuple[PlayerState, ...], targets: tuple[L5RCard, ...]
) -> int:
    """+1GP when paying for a single Item and nothing else, and +1GP more when it costs 6 or more.

    "A single Item only" is the whole payment rather than the Mine's share of it: paying for two
    cards at once, or for anything that is not an Item, leaves the Mine at its printed rate.
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
def _sapphire_mine_keywords(
    card: L5RCard, me: PlayerState, opponents: tuple[PlayerState, ...]
) -> tuple[str, ...]:
    """Renew while it holds any Sincerity token.

    Recruiting reads Renew as the card enters play and spends its Sincerity afterwards, so a Mine
    that accrued even one token refills the Province it vacated face-up.
    """
    return (keywords.RENEW,) if card.counters.get(SINCERITY.key, 0) else ()


@on(EnteredPlay, "sapphire_mine")
def _sapphire_mine_entered_play(ctx: TriggerContext) -> list[Effect]:
    """Sincerity: after this Holding enters play, if it accrued two or more Sincerity tokens, give it
    a +1GP Wealth token."""
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
        label="Open: Bow to give your Personality Cavalry, and may destroy this for a Follower",
        cost=bow_cost,
        targets=_shinjo_fields_targets,
        effects=_shinjo_fields_effects,
    ),
)
