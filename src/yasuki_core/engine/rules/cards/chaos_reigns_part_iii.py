from yasuki_core.engine.rules.abilities import (
    Ability,
    InvestAbility,
    bow_cost,
    itself,
    register_ability,
    register_invest,
)
from yasuki_core.engine.rules.actions import ActionTiming
from yasuki_core.engine.rules.economy import (
    PlayerState,
    effective_keywords,
    invest_discount,
    recruit_discount,
)
from yasuki_core.engine.rules.effects import CreateToken, Effect, GainHonor
from yasuki_core.engine.rules.equip import creation_targets
from yasuki_core.engine.rules.events import EnteredPlay
from yasuki_core.engine.rules.state import GameState
from yasuki_core.engine.rules.triggers import TriggerContext, on
from yasuki_core.game_pieces import keywords
from yasuki_core.game_pieces.cards import L5RCard


# --- Kengun Grounds ---

ZOMBIE_FOLLOWER = "zombie_follower"
KENGUN_HONOR_LOSS = 2
UNTAINTED_HONOR_LOSS = 5


@on(EnteredPlay, "kengun_grounds")
def _kengun_grounds_entered_play(ctx: TriggerContext) -> list[Effect]:
    """After this Holding enters play, lose 2 Honor."""
    if ctx.event.card_id != ctx.card.id:
        return []
    return [GainHonor(ctx.card.owner, -KENGUN_HONOR_LOSS)]


def _kengun_grounds_targets(game: GameState, source: L5RCard) -> list[str]:
    """Nobody while it is not the controller's turn — the ability's own condition, read before it is
    offered rather than resolving into nothing."""
    if game.active is not source.owner:
        return []
    zombie = game.table.creatable_tokens[ZOMBIE_FOLLOWER]
    return [target.id for target in creation_targets(game, source.owner, zombie)]


def _kengun_grounds_effects(game: GameState, source: L5RCard, target: L5RCard) -> list[Effect]:
    """The dead serve anyone; a Personality untouched by the Shadowlands pays for the company."""
    effects: list[Effect] = [
        CreateToken(ZOMBIE_FOLLOWER, source.owner, source.id, attach_to=target.id)
    ]
    if keywords.SHADOWLANDS not in effective_keywords(game, target):
        effects.append(GainHonor(source.owner, -UNTAINTED_HONOR_LOSS))
    return effects


register_ability(
    "kengun_grounds",
    Ability(
        timing=ActionTiming.OPEN,
        label="Open: Bow to Equip a 1F Undead Follower to your Personality",
        cost=bow_cost,
        targets=_kengun_grounds_targets,
        effects=_kengun_grounds_effects,
    ),
)


# --- Moto Ikarichi, Bloodseeker ---

IKARICHIS_UNDEAD = "undead_cavalry_follower_2f"
KANPEKI_DYNASTY = "the_kanpeki_dynasty_hantei_xl"
IKARICHI_HONOR_LOSS = 2
IKARICHI_INVEST = 2


@invest_discount("moto_ikarichi_bloodseeker")
def _moto_ikarichi_bloodseeker_invest_discount(
    card: L5RCard, me: PlayerState, opponents: tuple[PlayerState, ...]
) -> int:
    """His Invest costs nothing under the Kanpeki Dynasty, and its printed two Gold under any other
    Wind."""
    return IKARICHI_INVEST if any(held.printed_id == KANPEKI_DYNASTY for held in me.in_play) else 0


def _moto_ikarichi_bloodseeker_invest(
    game: GameState, source: L5RCard, amount: int
) -> list[Effect]:
    """A 2F Undead outrider, made and mounted as he arrives."""
    return [CreateToken(IKARICHIS_UNDEAD, source.owner, source.id, attach_to=source.id)]


register_invest(
    "moto_ikarichi_bloodseeker",
    InvestAbility(amounts=(IKARICHI_INVEST,), effect=_moto_ikarichi_bloodseeker_invest),
)


@on(EnteredPlay, "moto_ikarichi_bloodseeker")
def _moto_ikarichi_bloodseeker_entered_play(ctx: TriggerContext) -> list[Effect]:
    """After Ikarichi enters play, lose 2 Honor."""
    if ctx.event.card_id != ctx.card.id:
        return []
    return [GainHonor(ctx.card.owner, -IKARICHI_HONOR_LOSS)]


# --- Moto Traders ---


@recruit_discount("moto_traders")
def _moto_traders_recruit_discount(
    card: L5RCard, me: PlayerState, opponents: tuple[PlayerState, ...]
) -> int:
    """Enters play for 1 less Gold if you control another Merchant Caravan."""
    return 1 if me.controls(keywords.MERCHANT_CARAVAN, other_than=card) else 0


# --- Walk with Tengoku ---

FUSHICHO = "fushicho_personality_3_2_3"


def _walk_with_tengoku_effects(game: GameState, source: L5RCard, target: L5RCard) -> list[Effect]:
    """A Fushicho for the turn: it burns out before the turn ends however the turn goes."""
    return [CreateToken(FUSHICHO, source.owner, source.id, banish_at_turn_end=True)]


register_ability(
    "walk_with_tengoku",
    Ability(
        timing=ActionTiming.OPEN,
        label="Open: Bow to call a 3F/2C/3PH Fushicho for the turn",
        cost=bow_cost,
        targets=itself,
        effects=_walk_with_tengoku_effects,
        all_targets=True,
    ),
)
