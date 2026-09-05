from yasuki_core import ruleset
from yasuki_core.engine.players import PlayerId
from yasuki_core.engine.rules.abilities import (
    Ability,
    InvestAbility,
    attack_targets,
    bow_cost,
    itself,
    no_cost,
    register_ability,
    register_edict,
    register_invest,
)
from yasuki_core.engine.rules.actions import ActionTiming
from yasuki_core.engine.rules.economy import (
    PlayerState,
    effective_keywords,
    invest_discount,
    recruit_discount,
)
from yasuki_core.engine.rules.effects import (
    Choose,
    CreateToken,
    DrawCard,
    Effect,
    GainHonor,
    MeleeAttack,
    PlaceInProvince,
    ShuffleDeck,
)
from yasuki_core.engine.rules.equip import creation_targets
from yasuki_core.engine.rules.events import EnteredPlay
from yasuki_core.engine.rules.state import GameState
from yasuki_core.engine.rules.legality import province_zones
from yasuki_core.engine.rules.triggers import TriggerContext, choice_resolver, on
from yasuki_core.game_pieces import keywords
from yasuki_core.engine.table import DeckKey
from yasuki_core.game_pieces.cards import L5RCard
from yasuki_core.game_pieces.constants import Side
from yasuki_core.game_pieces.prints import PersonalityPrint


# --- Doji Maya (Experienced) ---

MAYA_MELEE = 3
MAYA_INVEST = 2
# "a Courtier or Tanuki Clan Personality" — both are keywords a card carries.
MAYA_SOUGHT = (keywords.COURTIER, keywords.TANUKI_CLAN)


def _doji_maya_experienced_effects(
    game: GameState, source: L5RCard, target: L5RCard
) -> list[Effect]:
    return [MeleeAttack(MAYA_MELEE, target.id, source.owner)]


register_ability(
    "doji_maya_experienced",
    Ability(
        timings=(ActionTiming.BATTLE,),
        label=f"Battle: Melee {MAYA_MELEE} Attack",
        cost=no_cost,
        targets=attack_targets,
        effects=_doji_maya_experienced_effects,
    ),
)


def _doji_maya_experienced_search_pool(game: GameState, seat: PlayerId) -> tuple[str, ...]:
    """The Personalities in ``seat``'s Dynasty deck her Invest may fetch."""
    return tuple(
        card.id
        for card in game.table.decks[DeckKey(seat, Side.DYNASTY)].cards
        if isinstance(card.printed, PersonalityPrint)
        and not effective_keywords(game, card).isdisjoint(MAYA_SOUGHT)
    )


def _doji_maya_experienced_invest(game: GameState, source: L5RCard, amount: int) -> list[Effect]:
    """Search the Dynasty deck for a Personality to refill the Province Maya just left."""
    # "If Maya entered play from a Province" needs no test: an Invest resolves only from a Recruit
    # or an Equip, and a Personality reaches play by Recruit, which is always out of a Province.
    pool = _doji_maya_experienced_search_pool(game, source.owner)
    if not pool:
        return []
    return [Choose(source.owner, pool, 1, 1, "doji_maya_experienced", source.id)]


@choice_resolver(
    "doji_maya_experienced",
    prompt="Search your Dynasty deck for a Courtier or Tanuki Clan Personality",
)
def _resolve_doji_maya_experienced(
    game: GameState, source_id: str, chosen: tuple[str, ...], seat: PlayerId
) -> list[Effect]:
    """Put the card Maya found into the Province she vacated, face-up, and shuffle the deck."""
    # Her Province is the one still short: a vacated Province's refill is deferred behind the
    # reactions to the card leaving, and an Invest resolves before that runs. Filling it here is
    # what leaves the pending refill a no-op.
    short = [key for key, zone in province_zones(game, seat) if zone.has_capacity()]
    placement = [PlaceInProvince(chosen[0], short[0])] if short else []
    return [*placement, ShuffleDeck(DeckKey(seat, Side.DYNASTY))]


register_invest(
    "doji_maya_experienced",
    InvestAbility(amounts=(MAYA_INVEST,), effect=_doji_maya_experienced_invest),
)


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
        timings=(ActionTiming.OPEN,),
        label="Open: Bow to create a 1F Undead Follower and attach it to your target Personality",
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


IKARICHI_MELEE = 4


def _moto_ikarichi_bloodseeker_effects(
    game: GameState, source: L5RCard, target: L5RCard
) -> list[Effect]:
    return [MeleeAttack(IKARICHI_MELEE, target.id, source.owner)]


register_ability(
    "moto_ikarichi_bloodseeker",
    Ability(
        timings=(ActionTiming.BATTLE,),
        label=f"Battle: Melee {IKARICHI_MELEE} Attack",
        cost=no_cost,
        targets=attack_targets,
        effects=_moto_ikarichi_bloodseeker_effects,
    ),
)


# --- Moto Traders ---


@recruit_discount("moto_traders")
def _moto_traders_recruit_discount(
    card: L5RCard, me: PlayerState, opponents: tuple[PlayerState, ...]
) -> int:
    """Enters play for 1 less Gold if you control another Merchant Caravan."""
    return 1 if me.controls(keywords.MERCHANT_CARAVAN, other_than=card) else 0


def _moto_traders_effects(game: GameState, source: L5RCard, target: L5RCard) -> list[Effect]:
    """Draw a card."""
    return [DrawCard(source.owner)]


register_ability(
    "moto_traders",
    Ability(
        timings=(ActionTiming.OPEN,),
        label="Open: Bow to draw a card",
        cost=bow_cost,
        targets=itself,
        effects=_moto_traders_effects,
        all_targets=True,
    ),
)


# --- Walk with Tengoku ---


FUSHICHO = "fushicho_personality_3_2_3"


def _walk_with_tengoku_effects(game: GameState, source: L5RCard, target: L5RCard) -> list[Effect]:
    """A Fushicho for the turn: it burns out before the turn ends however the turn goes."""
    return [CreateToken(FUSHICHO, source.owner, source.id, banish_at_turn_end=True)]


register_ability(
    "walk_with_tengoku",
    Ability(
        timings=(ActionTiming.OPEN,),
        label="Open: Bow to create a 3F/2C/3PH Fushicho, banished at the end of the turn",
        cost=bow_cost,
        targets=itself,
        effects=_walk_with_tengoku_effects,
        all_targets=True,
    ),
)


# --- Zealotry ---

# "Open: If you are an Akasha Clan player, put this Edict into play." Its Dynasty-phase trigger has
# no handler yet.
register_edict("zealotry", clan=ruleset.AKASHA)
