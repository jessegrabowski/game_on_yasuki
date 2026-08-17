from yasuki_core.engine.players import PlayerId
from yasuki_core.engine.rules.abilities import (
    Ability,
    bow_cost,
    bow_and_destroy,
    owned_holdings,
    plus_one_gp_this_turn,
    spend_wealth,
    register_ability,
)
from yasuki_core.engine.rules.economy import effective_gold_production, effective_keywords
from yasuki_core.engine.rules.legality import reachable_gold, recruit_cost
from yasuki_core.engine.rules.effects import (
    AdjustCounter,
    Ask,
    Destroy,
    Effect,
    IgnoreHonorRequirements,
    RecruitCard,
    Straighten,
    Then,
)
from yasuki_core.engine.rules.events import Destroyed, EnteredPlay
from yasuki_core.engine.rules.actions import ActionTiming
from yasuki_core.engine.rules.state import GameState
from yasuki_core.engine.rules.triggers import TriggerContext, choice_resolver, on, province_holdings
from yasuki_core.game_pieces.cards import L5RCard
from yasuki_core.game_pieces.counters import SINCERITY, WEALTH


# --- Harvested Land ---


def _other_farms(game: GameState, card: L5RCard) -> list[str]:
    return [farm.id for farm in owned_holdings(game, card.owner, "Farm") if farm is not card]


register_ability(
    "harvested_land",
    Ability(
        timing=ActionTiming.OPEN,
        label="Bow, destroy: give your other Farms +1 Gold Production",
        cost=bow_and_destroy,
        targets=_other_farms,
        effects=plus_one_gp_this_turn,
        all_targets=True,
    ),
)


# --- Mishime Sensei ---


@on(EnteredPlay, "mishime_sensei")
def _mishime_sensei_enters_play(ctx: TriggerContext) -> list[Effect]:
    """Mishime Sensei: grant its controller the ignore-Honor-Requirements waiver as it enters
    play."""
    if ctx.event.card_id != ctx.card.id:
        return []
    return [IgnoreHonorRequirements(ctx.card.owner)]


# --- Modest Farm ---


@choice_resolver(
    "modest_farm_straighten", prompt="Destroy Modest Farm to straighten the card it recruited"
)
def _modest_farm_straighten(
    game: GameState, source_id: str, chosen: tuple[str, ...], seat: PlayerId
) -> list[Effect]:
    # source_id is the recruited target; chosen holds Modest Farm's id when its controller sacrifices
    # it to straighten the target.
    if not chosen:
        return []
    return [Destroy(chosen[0], seat), Straighten(source_id)]


def _affordable_province_holdings(game: GameState, card: L5RCard) -> list[str]:
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
        RecruitCard(target.id, renew="Farm" in target.keywords),
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
        timing=ActionTiming.OPEN,
        label="Bow, pay a Holding's cost: recruit it from your Province out of sequence",
        cost=bow_cost,
        targets=_affordable_province_holdings,
        effects=_modest_farm_effects,
    ),
)


# --- Rural Market ---


@on(EnteredPlay, "rural_market")
def _rural_market_enters_play(ctx: TriggerContext) -> list[Effect]:
    """After this Holding enters play, give it a +1GP Wealth token."""
    if ctx.event.card_id != ctx.card.id:
        return []
    return [AdjustCounter(ctx.card.id, WEALTH, 1)]


@on(Destroyed, "rural_market")
def _rural_market_farm_destroyed(ctx: TriggerContext) -> list[Effect]:
    """After your Farm is destroyed, give this Holding a +1GP Wealth token."""
    destroyed = ctx.game.table.cards_by_id.get(ctx.event.card_id)
    if destroyed is None or destroyed.owner is not ctx.card.owner:
        return []
    if "Farm" not in effective_keywords(ctx.game, destroyed):
        return []
    return [AdjustCounter(ctx.card.id, WEALTH, 1)]


def _owned_bowed_farms(game: GameState, card: L5RCard) -> list[str]:
    # "Not produced Gold this turn" is satisfied for any bowed Farm: production only happens in the
    # Dynasty phase, after this Open ability's Action-phase window.
    return [farm.id for farm in owned_holdings(game, card.owner, "Farm") if farm.bowed]


def _rural_market_effects(game: GameState, source: L5RCard, target: L5RCard) -> list[Effect]:
    return [Straighten(target.id)]


register_ability(
    "rural_market",
    Ability(
        timing=ActionTiming.OPEN,
        label="Spend a wealth token: straighten a Farm",
        cost=spend_wealth,
        targets=_owned_bowed_farms,
        effects=_rural_market_effects,
    ),
)


# --- Sapphire Mine ---


@on(EnteredPlay, "sapphire_mine")
def _sapphire_mine(ctx: TriggerContext) -> list[Effect]:
    """Sincerity: after this Holding enters play, if it accrued two or more Sincerity tokens, give it
    a +1GP Wealth token."""
    if ctx.event.card_id != ctx.card.id:
        return []
    if ctx.card.counters.get(SINCERITY.key, 0) < 2:
        return []
    return [AdjustCounter(ctx.card.id, WEALTH, 1)]
