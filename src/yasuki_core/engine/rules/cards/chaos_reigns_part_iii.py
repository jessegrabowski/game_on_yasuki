from yasuki_core import ruleset
from yasuki_core.engine.players import PlayerId, Trait
from yasuki_core.engine.rules.abilities.costs import bow_cost, no_cost
from yasuki_core.engine.rules.abilities.idioms import (
    ask_who_loses_honor,
    plays_clan,
    YuWidening,
    register_entry,
    register_granted_yu,
    register_terrain,
    register_yu,
    register_yu_widening,
)
from yasuki_core.engine.rules.abilities.model import (
    Ability,
    CardLocation,
    InvestAbility,
    TargetGroup,
    itself,
)
from yasuki_core.engine.rules.abilities.registry import (
    abilities_for,
    register_ability,
    register_invest,
)
from yasuki_core.engine.rules.board.queries import (
    in_army_with,
    ATTACK_TARGET,
    army_at,
    attack_targets,
    followers_in_play,
    owned_holdings,
    owned_personalities,
    personalities_in_play,
)
from yasuki_core.game_pieces.counters import WEALTH
from yasuki_core.engine.rules.vocabulary.actions import ActionTiming, ActivateAbility
from yasuki_core.engine.rules.action_record import action_round
from yasuki_core.engine.rules.gold.cost import effective_gold_cost
from yasuki_core.engine.rules.legality import permitted_timings_in
from yasuki_core.engine.rules.vocabulary.decisions import PickedTargets
from yasuki_core.engine.rules.stats.card_values import effective_chi
from yasuki_core.engine.rules.stats.keyword_grants import effective_keywords
from yasuki_core.engine.rules.gold.discounts import invest_discount, recruit_discount
from yasuki_core.engine.rules.gold.production import gold_handler
from yasuki_core.engine.rules.board.clans import controlled_alignments
from yasuki_core.engine.rules.board.seats import (
    cards_in_hand,
    seat_controls_printed,
    seat_named,
    seat_wind,
)
from yasuki_core.engine.rules.effects import (
    AdditionalAction,
    AdjustCounter,
    Arrange,
    Ask,
    AskOption,
    Banish,
    Bow,
    Choose,
    CreateToken,
    DelayedEffect,
    Destroy,
    Discard,
    DiscardFromHand,
    Dishonor,
    DrawCard,
    Effect,
    EndLook,
    Evaluate,
    Fear,
    LookAtTop,
    GainHonor,
    GrantKeyword,
    GrantModifier,
    GrantProvinceStrength,
    MeleeAttack,
    MoveToHand,
    PlaceInProvince,
    Rehonor,
    Show,
    ShuffleDeck,
    Simultaneously,
    PayGold,
    TakeFavor,
)
from yasuki_core.engine.rules.rulebook.looks import PUT_ON_BOTTOM
from yasuki_core.engine.rules.rulebook.equip import creation_targets
from yasuki_core.engine.rules.vocabulary.game_events import (
    BattleEnded,
    Destroyed,
    Dishonored,
    DuelDeclared,
    EnteredPlay,
)
from yasuki_core.engine.rules.vocabulary.modifiers import Duration, Stat
from yasuki_core.engine.rules.state import GameState
from yasuki_core.engine.rules.board.queries import (
    has_keyword,
    phase_history,
    province_zones,
    remaining_look,
    top_of_deck,
)
from yasuki_core.engine.rules.triggers import TriggerContext, caused_by, choice_resolver, on
from yasuki_core.engine.rules.duel.focus_effects import focus_effect
from yasuki_core.engine.rules.duel.procedure import decided_duel
from yasuki_core.engine.rules.turn.structure import DUEL_CONSEQUENCES
from yasuki_core.engine.rules.units.composition import is_follower
from yasuki_core.engine.rules.vocabulary import keywords
from yasuki_core.engine.table import DeckKey, Location, ZoneKey, ZoneRole, location_of
from yasuki_core.game_pieces.cards import L5RCard
from yasuki_core.game_pieces.constants import Side
from yasuki_core.game_pieces.prints import EventPrint, PersonalityPrint


# --- A Good Day to Die (2) ---

GOOD_DAY_WINNER = "a_good_day_to_die_2_winner"


@focus_effect("a_good_day_to_die_2")
def _a_good_day_to_die_2_focus_effect(game: GameState, card: L5RCard) -> list[Effect]:
    """ "As a Focus Effect, if the duel is during battle and the loser is destroyed, destroy the
    winner." Read once the duel's consequences have applied, which is where a loser is destroyed."""
    attack = game.attack
    if attack is None or attack.current is None:
        return []
    return [DelayedEffect(Evaluate(GOOD_DAY_WINNER, card.id, card.owner), DUEL_CONSEQUENCES)]


@choice_resolver(GOOD_DAY_WINNER)
def _a_good_day_to_die_2_winner(
    game: GameState, source_id: str, chosen: tuple[str, ...], seat: PlayerId
) -> list[Effect]:
    duel = decided_duel(game)
    if duel is None:
        return []
    events = game.turn_events
    declared = max(index for index, event in enumerate(events) if isinstance(event, DuelDeclared))
    destroyed = {event.card_id for event in events[declared:] if isinstance(event, Destroyed)}
    if not any(duel.duelist_of(loser) in destroyed for loser in duel.outcome.losers):
        return []
    return [Destroy(duel.duelist_of(winner), seat) for winner in duel.outcome.winners]


def _a_good_day_to_die_2_covers(game: GameState, good_day: L5RCard, card: L5RCard) -> bool:
    """Your cards' Yu effects trigger even when destroyed by your actions."""
    return card.owner is good_day.owner


register_yu_widening(
    "a_good_day_to_die_2", YuWidening(covers=_a_good_day_to_die_2_covers, chosen=False)
)
register_terrain(
    "a_good_day_to_die_2",
    timings=(ActionTiming.ENGAGE,),
    ability_keywords=frozenset({keywords.TERRAIN}),
)


# --- Bayushi Gihei ---

GIHEI_FORCE = 2
GIHEI_HONOR = 1


def _bayushi_gihei_reacts(ctx: TriggerContext, where: Location | None) -> list[Effect]:
    """After your action destroys or dishonors a card at Gihei's location, give him +2F and a
    target player loses 1 Honor. "Your action" is read off the event's cause."""
    gihei = ctx.card
    if not caused_by(ctx, gihei.owner) or where != location_of(ctx.game.table, gihei):
        return []
    return [
        GrantModifier(gihei.id, gihei.id, Stat.FORCE, GIHEI_FORCE, Duration.UNTIL_END_OF_TURN),
        ask_who_loses_honor(ctx.game, gihei.owner, GIHEI_HONOR, gihei.id),
    ]


@on(Destroyed, "bayushi_gihei")
def _bayushi_gihei_destroyed(ctx: TriggerContext) -> list[Effect]:
    return _bayushi_gihei_reacts(ctx, ctx.event.location)


@on(Dishonored, "bayushi_gihei")
def _bayushi_gihei_dishonored(ctx: TriggerContext) -> list[Effect]:
    dishonored = ctx.game.table.cards_by_id[ctx.event.card_id]
    return _bayushi_gihei_reacts(ctx, location_of(ctx.game.table, dishonored))


# --- Bayushi Purimu ---

PURIMU_HONOR_LOSS = 3


def _bayushi_purimu_yu(ctx: TriggerContext) -> list[Effect]:
    """ "Yu: Dishonor a target Personality at any location." Any Personality in play, since the
    text lifts the Yu's battlefield limit."""
    targets = tuple(card.id for card in personalities_in_play(ctx.game))
    return [Choose(ctx.card.owner, targets, 1, 1, "bayushi_purimu", ctx.card.id)] if targets else []


register_yu("bayushi_purimu", _bayushi_purimu_yu)


@choice_resolver("bayushi_purimu", prompt="Bayushi Purimu's Yu: choose a Personality to dishonor")
def _resolve_bayushi_purimu(
    game: GameState, source_id: str, chosen: tuple[str, ...], seat: PlayerId
) -> list[Effect]:
    """Dishonor the target, then "Their controller loses 3 Honor"."""
    target = game.table.cards_by_id[chosen[0]]
    return [
        Dishonor(target.id, Trait(source_id)),
        GainHonor(target.owner, -PURIMU_HONOR_LOSS, source_id=source_id),
    ]


# --- Chuda Jomei ---


JOMEI_HONOR_LOSS = 3


@on(EnteredPlay, "chuda_jomei")
def _chuda_jomei_entered_play(ctx: TriggerContext) -> list[Effect]:
    """After Jomei enters play, lose 3 Honor."""
    if ctx.event.card_id != ctx.card.id:
        return []
    return [GainHonor(ctx.card.owner, -JOMEI_HONOR_LOSS, source_id=ctx.card.id)]


def _chuda_jomei_targets(game: GameState, source: L5RCard) -> list[str]:
    """Every Personality on the board without the Nonhuman keyword. Human is the absence of that
    keyword rather than one a card carries (CR, Human), and it is read off the board because
    Nonhuman can be granted."""
    return [
        card.id
        for card in personalities_in_play(game)
        if keywords.NONHUMAN not in effective_keywords(game, card)
    ]


def _chuda_jomei_effects(game: GameState, source: L5RCard, target: L5RCard) -> list[Effect]:
    """Give the target Shadowlands. The card prints no duration, so the grant lasts until the end
    of the turn (CR, Duration of Effects)."""
    return [GrantKeyword(source.id, target.id, keywords.SHADOWLANDS, Duration.UNTIL_END_OF_TURN)]


register_ability(
    "chuda_jomei",
    Ability(
        timings=(ActionTiming.OPEN,),
        cost=no_cost,
        targets=_chuda_jomei_targets,
        targeting_message="a Human Personality",
        effects=_chuda_jomei_effects,
    ),
)


# --- Comprehensive Education ---

COMPREHENSIVE_EDUCATION_LOOK = 5


def _comprehensive_education_edicts_and_kata(
    game: GameState, card_ids: tuple[str, ...]
) -> tuple[str, ...]:
    return tuple(
        card_id
        for card_id in card_ids
        if has_keyword(game, game.table.cards_by_id[card_id], keywords.EDICT)
        or has_keyword(game, game.table.cards_by_id[card_id], keywords.KATA)
    )


def _comprehensive_education_effects(
    game: GameState, source: L5RCard, target: L5RCard
) -> list[Effect]:
    """Look at five, then the first of the two "may" questions, each skipped when it has no
    candidates. With no Edict or Kata among them the rest go straight to the bottom."""
    seat = source.owner
    fate = DeckKey(seat, Side.FATE)
    seen = top_of_deck(game, fate, COMPREHENSIVE_EDUCATION_LOOK)
    if not seen:
        return []
    return [
        LookAtTop(seat, fate, len(seen)),
        *_comprehensive_education_take(game, seen, seat, source.id),
    ]


def _comprehensive_education_take(
    game: GameState, seen: tuple[str, ...], seat: PlayerId, source_id: str
) -> list[Effect]:
    offered = _comprehensive_education_edicts_and_kata(game, seen)
    if not offered:
        return [_comprehensive_education_bottom(seat, seen, source_id)]
    return [Choose(seat, offered, 0, 1, "comprehensive_education_take", source_id)]


@choice_resolver(
    "comprehensive_education_take",
    prompt="You may show one that is an Edict or Kata and put it in your hand",
)
def _resolve_comprehensive_education_take(
    game: GameState, source_id: str, chosen: tuple[str, ...], seat: PlayerId
) -> list[Effect]:
    taken: list[Effect] = [Show(chosen[0]), MoveToHand(chosen[0], seat)] if chosen else []
    rest = tuple(card_id for card_id in remaining_look(game) if card_id not in chosen)
    discardable = _comprehensive_education_edicts_and_kata(game, rest)
    if discardable:
        next_step = Choose(
            seat, discardable, 0, len(discardable), "comprehensive_education_discard", source_id
        )
    else:
        next_step = _comprehensive_education_bottom(seat, rest, source_id)
    return [*taken, next_step]


@choice_resolver(
    "comprehensive_education_discard", prompt="You may discard any that are Edicts or Kata"
)
def _resolve_comprehensive_education_discard(
    game: GameState, source_id: str, chosen: tuple[str, ...], seat: PlayerId
) -> list[Effect]:
    discarded = Simultaneously(tuple(Discard(card_id, seat) for card_id in chosen))
    rest = tuple(card_id for card_id in remaining_look(game) if card_id not in chosen)
    return [discarded, _comprehensive_education_bottom(seat, rest, source_id)]


def _comprehensive_education_bottom(
    seat: PlayerId, rest: tuple[str, ...], source_id: str
) -> Effect:
    """ "Put the rest on the bottom of your deck in any order", or nothing left to put."""
    if not rest:
        return EndLook()
    return Arrange(seat, rest, PUT_ON_BOTTOM, source_id, to_bottom=True)


register_ability(
    "comprehensive_education",
    Ability(
        timings=(ActionTiming.OPEN,),
        cost=no_cost,
        targets=itself,
        hits_every_target=True,
        effects=_comprehensive_education_effects,
        located_at=(CardLocation.HAND,),
    ),
)


# --- Doji Maya (Experienced) ---

MAYA_MELEE = 3
MAYA_INVEST = 2
# "a Courtier or Tanuki Clan Personality": both are keywords a card carries.
MAYA_SOUGHT = (keywords.COURTIER, keywords.TANUKI_CLAN)


def _doji_maya_experienced_effects(
    game: GameState, source: L5RCard, target: L5RCard
) -> list[Effect]:
    return [MeleeAttack(MAYA_MELEE, target.id, source.owner)]


register_ability(
    "doji_maya_experienced",
    Ability(
        timings=(ActionTiming.BATTLE,),
        keywords=frozenset({keywords.IAIJUTSU}),
        cost=no_cost,
        targets=attack_targets,
        targeting_message=ATTACK_TARGET,
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


# --- Doji Teru ---

TERU_HONOR = 2
TERU_FORCE = 2


def _doji_teru_targets(game: GameState, source: L5RCard) -> list[str]:
    return [
        card.id
        for card in personalities_in_play(game)
        if card.owner is not source.owner and card.dishonorable
    ]


def _doji_teru_effects(game: GameState, source: L5RCard, target: L5RCard) -> list[Effect]:
    """Their controller may rehonor them. If this rehonored them, gain 2 Honor; otherwise, give
    Teru +2F. The gain names no Personality: rehonoring is one of the action's own effects, so the
    CR does not substitute it for the gain (CR, Rehonoring 0.1)."""
    return [
        Ask(
            target.owner,
            f"Rehonor {target.name}?",
            "doji_teru",
            subjects=(target.id,),
            source_id=source.id,
        )
    ]


@choice_resolver("doji_teru")
def _resolve_doji_teru(
    game: GameState, source_id: str, chosen: tuple[str, ...], seat: PlayerId
) -> list[Effect]:
    teru = game.table.cards_by_id[source_id]
    if chosen:
        return [Rehonor(chosen[0]), GainHonor(teru.owner, TERU_HONOR)]
    return [GrantModifier(source_id, source_id, Stat.FORCE, TERU_FORCE, Duration.UNTIL_END_OF_TURN)]


register_ability(
    "doji_teru",
    Ability(
        timings=(ActionTiming.OPEN,),
        cost=no_cost,
        targets=_doji_teru_targets,
        targeting_message="another player's dishonorable Personality",
        effects=_doji_teru_effects,
    ),
)


# --- Hungry Moon ---

HUNGRY_MOON_HONOR = 3


def _hungry_moon_dishonor_targets(game: GameState, source: L5RCard) -> list[str]:
    return [card.id for card in personalities_in_play(game) if card.bowed]


def _hungry_moon_dishonor_effects(
    game: GameState, source: L5RCard, target: L5RCard
) -> list[Effect]:
    return [Dishonor(target.id, source.owner)]


def _hungry_moon_wealth_targets(game: GameState, source: L5RCard) -> list[str]:
    return [card.id for seat in game.table.seats for card in owned_holdings(game, seat)]


def _hungry_moon_wealth_effects(game: GameState, source: L5RCard, target: L5RCard) -> list[Effect]:
    """Destroy all Wealth tokens on a target Holding. If this destroyed any Wealth tokens, choose a
    player, who loses 3 Honor. A Holding with none is a legal target the ability does nothing to."""
    held = target.counters.get(WEALTH.key, 0)
    if not held:
        return []
    return [
        AdjustCounter(target.id, WEALTH, -held),
        ask_who_loses_honor(game, source.owner, HUNGRY_MOON_HONOR, source.id),
    ]


register_ability(
    "hungry_moon",
    Ability(
        timings=(ActionTiming.OPEN,),
        cost=no_cost,
        targets=_hungry_moon_dishonor_targets,
        targeting_message="a bowed Personality",
        effects=_hungry_moon_dishonor_effects,
        located_at=(CardLocation.HAND,),
        key="dishonor",
    ),
)

register_ability(
    "hungry_moon",
    Ability(
        printed_index=1,
        timings=(ActionTiming.OPEN,),
        cost=no_cost,
        targets=_hungry_moon_wealth_targets,
        targeting_message="a Holding",
        effects=_hungry_moon_wealth_effects,
        located_at=(CardLocation.HAND,),
        key="wealth",
    ),
)


# --- Ijathilu Zealots ---

NAGA_ZEALOT = "naga_zealot_personality_2_2_1"
IJATHILU_ZEALOT_COUNT = 2
IJATHILU_FEAR = 3


def _ijathilu_zealots_yu(ctx: TriggerContext) -> list[Effect]:
    """ "Yu: Create two 2F/2C/1PH Naga Nonhuman Zealot Personalities in your home." """
    zealots = (
        CreateToken(NAGA_ZEALOT, ctx.card.owner, ctx.card.id) for _ in range(IJATHILU_ZEALOT_COUNT)
    )
    return [Simultaneously(tuple(zealots))]


register_yu("ijathilu_zealots", _ijathilu_zealots_yu)


def _ijathilu_zealots_effects(game: GameState, source: L5RCard, target: L5RCard) -> list[Effect]:
    return [Fear(IJATHILU_FEAR, target.id, source.owner)]


register_ability(
    "ijathilu_zealots",
    Ability(
        timings=(ActionTiming.BATTLE,),
        cost=no_cost,
        targets=attack_targets,
        targeting_message=ATTACK_TARGET,
        effects=_ijathilu_zealots_effects,
    ),
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
    return [GainHonor(ctx.card.owner, -KENGUN_HONOR_LOSS, source_id=ctx.card.id)]


def _kengun_grounds_targets(game: GameState, source: L5RCard) -> list[str]:
    zombie = game.table.creatable_tokens[ZOMBIE_FOLLOWER]
    return [target.id for target in creation_targets(game, source.owner, zombie)]


def _kengun_grounds_effects(game: GameState, source: L5RCard, target: L5RCard) -> list[Effect]:
    """The dead serve anyone. A Personality untouched by the Shadowlands pays for the company."""
    effects: list[Effect] = [
        CreateToken(ZOMBIE_FOLLOWER, source.owner, source.id, attach_to=target.id)
    ]
    if keywords.SHADOWLANDS not in effective_keywords(game, target):
        effects.append(GainHonor(source.owner, -UNTAINTED_HONOR_LOSS, source_id=source.id))
    return effects


register_ability(
    "kengun_grounds",
    Ability(
        timings=(ActionTiming.LIMITED,),
        cost=bow_cost,
        targets=_kengun_grounds_targets,
        targeting_message="your Personality",
        effects=_kengun_grounds_effects,
    ),
)


# --- Matsu Hanshiro ---

HANSHIRO_PROVINCE_STRENGTH = 4
HANSHIRO_LOWER = "Give this Province -4PS"
HANSHIRO_RAISE = "Give this Province +4PS"
HANSHIRO_MELEE = 3
HANSHIRO_USES_AFTER_A_DEATHSEEKER_FELL = 2


def _matsu_hanshiro_yu(ctx: TriggerContext) -> list[Effect]:
    """ "Yu: Give this Province -4PS or +4PS." """
    return [
        AskOption(
            ctx.card.owner,
            (HANSHIRO_LOWER, HANSHIRO_RAISE),
            "Matsu Hanshiro's Yu: give this Province -4PS or +4PS?",
            "matsu_hanshiro",
            ctx.card.id,
        )
    ]


register_yu("matsu_hanshiro", _matsu_hanshiro_yu)


@choice_resolver("matsu_hanshiro")
def _resolve_matsu_hanshiro(
    game: GameState, source_id: str, chosen: tuple[str, ...], seat: PlayerId
) -> list[Effect]:
    """The Province at Hanshiro's battlefield, which he still stands at: his Yu resolves before he
    is destroyed. The change lasts the turn, the default for an effect that states no duration (CR,
    Ongoing)."""
    battlefield = location_of(game.table, game.table.cards_by_id[source_id]).battlefield
    province = game.attack.battlefields[battlefield].province
    amount = (
        -HANSHIRO_PROVINCE_STRENGTH if chosen[0] == HANSHIRO_LOWER else HANSHIRO_PROVINCE_STRENGTH
    )
    return [GrantProvinceStrength(source_id, province, amount, Duration.UNTIL_END_OF_TURN)]


def _matsu_hanshiro_effects(game: GameState, source: L5RCard, target: L5RCard) -> list[Effect]:
    return [MeleeAttack(HANSHIRO_MELEE, target.id, source.owner)]


def _matsu_hanshiro_uses_per_turn(game: GameState, source: L5RCard) -> int:
    """ "You may use this ability one additional time this turn if any of your Deathseekers have
    been destroyed during this battle." """
    if _matsu_hanshiro_deathseeker_fell_this_battle(game, source.owner):
        return HANSHIRO_USES_AFTER_A_DEATHSEEKER_FELL
    return 1


def _matsu_hanshiro_deathseeker_fell_this_battle(game: GameState, seat: PlayerId) -> bool:
    """Whether a Deathseeker ``seat`` controlled was destroyed since the last battle of this Attack
    Phase ended."""
    history = phase_history(game)
    ended = [index for index, event in enumerate(history) if isinstance(event, BattleEnded)]
    this_battle = history[ended[-1] + 1 :] if ended else history
    for event in this_battle:
        if not isinstance(event, Destroyed) or event.controller is not seat:
            continue
        destroyed = game.table.cards_by_id.get(event.card_id)
        if destroyed is not None and has_keyword(game, destroyed, keywords.DEATHSEEKER):
            return True
    return False


register_ability(
    "matsu_hanshiro",
    Ability(
        timings=(ActionTiming.BATTLE,),
        cost=no_cost,
        targets=attack_targets,
        targeting_message=ATTACK_TARGET,
        effects=_matsu_hanshiro_effects,
        uses_per_turn=_matsu_hanshiro_uses_per_turn,
    ),
)


# --- Moto Ikarichi, Bloodseeker ---


IKARICHIS_UNDEAD = "undead_cavalry_follower_2f"
KANPEKI_DYNASTY = "the_kanpeki_dynasty_hantei_xl"
IKARICHI_HONOR_LOSS = 2
IKARICHI_INVEST = 2


@invest_discount("moto_ikarichi_bloodseeker")
def _moto_ikarichi_bloodseeker_invest_discount(
    card: L5RCard, game: GameState, seat: PlayerId
) -> int:
    """His Invest costs nothing under the Kanpeki Dynasty, and its printed two Gold under any other
    Wind."""
    wind = seat_wind(game, seat)
    return IKARICHI_INVEST if wind is not None and wind.printed_id == KANPEKI_DYNASTY else 0


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
    return [GainHonor(ctx.card.owner, -IKARICHI_HONOR_LOSS, source_id=ctx.card.id)]


IKARICHI_MELEE = 4


def _moto_ikarichi_bloodseeker_effects(
    game: GameState, source: L5RCard, target: L5RCard
) -> list[Effect]:
    return [MeleeAttack(IKARICHI_MELEE, target.id, source.owner)]


register_ability(
    "moto_ikarichi_bloodseeker",
    Ability(
        timings=(ActionTiming.BATTLE,),
        cost=no_cost,
        targets=attack_targets,
        targeting_message=ATTACK_TARGET,
        effects=_moto_ikarichi_bloodseeker_effects,
    ),
)


# --- Moto Traders ---


@recruit_discount("moto_traders")
def _moto_traders_recruit_discount(card: L5RCard, game: GameState, seat: PlayerId) -> int:
    """Enters play for 1 less Gold if you control another Merchant Caravan."""
    return 1 if seat_controls_printed(game, seat, keywords.MERCHANT_CARAVAN, other_than=card) else 0


def _moto_traders_effects(game: GameState, source: L5RCard, target: L5RCard) -> list[Effect]:
    """Draw a card."""
    return [DrawCard(source.owner)]


register_ability(
    "moto_traders",
    Ability(
        timings=(ActionTiming.OPEN,),
        cost=bow_cost,
        targets=itself,
        effects=_moto_traders_effects,
        hits_every_target=True,
    ),
)


# --- Tanuki Band ---


@gold_handler("tanuki_band")
def _tanuki_band_gold(
    card: L5RCard, game: GameState, seat: PlayerId, targets: tuple[L5RCard, ...]
) -> int:
    """+1GP while you control two Clan Alignments, or +2GP while you control three or more."""
    controlled = len(controlled_alignments(game, seat))
    bonus = 2 if controlled >= 3 else 1 if controlled == 2 else 0
    return card.gold_production + bonus


def _tanuki_band_players(game: GameState, seat: PlayerId) -> tuple[PlayerId, ...]:
    """The players with more cards in their hand than ``seat``."""
    held = len(cards_in_hand(game, seat))
    return tuple(player for player in game.table.seats if len(cards_in_hand(game, player)) > held)


def _tanuki_band_targets(game: GameState, source: L5RCard) -> list[str]:
    """The Band itself, while some player could be its target: an action with no legal target
    cannot be announced."""
    return [source.id] if _tanuki_band_players(game, source.owner) else []


def _tanuki_band_effects(game: GameState, source: L5RCard, target: L5RCard) -> list[Effect]:
    """Name the target player, a player with more cards in their hand than you. Nothing happens
    when no player still qualifies, since the hands can change between announcement and
    resolution."""
    names = tuple(
        game.table.seats[player].name for player in _tanuki_band_players(game, source.owner)
    )
    if not names:
        return []
    return [AskOption(source.owner, names, "Who must discard a card?", "tanuki_band", source.id)]


@choice_resolver("tanuki_band")
def _resolve_tanuki_band(
    game: GameState, source_id: str, chosen: tuple[str, ...], seat: PlayerId
) -> list[Effect]:
    """The named player must discard a card, which they choose."""
    named = seat_named(game, chosen[0])
    return [DiscardFromHand(named, 1, seat, named)]


register_ability(
    "tanuki_band",
    Ability(
        timings=(ActionTiming.OPEN,),
        cost=bow_cost,
        targets=_tanuki_band_targets,
        effects=_tanuki_band_effects,
        hits_every_target=True,
    ),
)


# --- The Taisen Sorrow ---


TAISEN_SORROW_MAX_GOLD_COST = 4


def _the_taisen_sorrow_effects(game: GameState, source: L5RCard, target: L5RCard) -> list[Effect]:
    """Every cheap Personality and Follower that is not Shadowlands goes at once, the Event after
    them. A Personality takes his unit with him, so a Follower that left with its Personality is
    gone by the time its own destruction resolves."""
    swept = [
        card
        for card in (*personalities_in_play(game), *followers_in_play(game))
        if keywords.SHADOWLANDS not in effective_keywords(game, card)
        and effective_gold_cost(game, card) <= TAISEN_SORROW_MAX_GOLD_COST
    ]
    return [
        Simultaneously(tuple(Destroy(card.id, source.owner) for card in swept)),
        Banish(source.id),
    ]


register_ability(
    "the_taisen_sorrow",
    Ability(
        timings=(ActionTiming.OPEN,),
        cost=no_cost,
        targets=itself,
        effects=_the_taisen_sorrow_effects,
        hits_every_target=True,
        located_at=(CardLocation.PROVINCE,),
    ),
)


# --- Tsudao's Grave ---


def _tsudaos_grave_cost(game: GameState, source: L5RCard) -> list[Effect]:
    return [Destroy(source.id, source.owner)]


def _tsudaos_grave_events(game: GameState, seat: PlayerId) -> tuple[str, ...]:
    """The Events in ``seat``'s Dynasty deck and discard pile, which the search reaches alike."""
    searched = (
        *game.table.decks[DeckKey(seat, Side.DYNASTY)].cards,
        *game.table.zones[ZoneKey(seat, ZoneRole.DYNASTY_DISCARD)].cards,
    )
    return tuple(card.id for card in searched if isinstance(card.printed, EventPrint))


def _tsudaos_grave_effects(game: GameState, source: L5RCard, target: L5RCard) -> list[Effect]:
    """Search for an Event. Both it and the Province it fills are named after the search, so the
    action announces neither. Nothing to find is the whole action, since the Grave is spent by
    then either way."""
    found = _tsudaos_grave_events(game, source.owner)
    if not found:
        return []
    return [Choose(source.owner, found, 1, 1, "tsudaos_grave_event", source.id, declinable=True)]


@choice_resolver("tsudaos_grave_event", prompt="Choose an Event to refill a Province with")
def _resolve_tsudaos_grave_event(
    game: GameState, source_id: str, chosen: tuple[str, ...], seat: PlayerId
) -> list[Effect]:
    """Name the Province the Event refills, which the seat may decline to do. A Province is a slot
    rather than the card standing in it, so an empty one is as fillable as a full one."""
    if not chosen:
        return []
    slots = tuple(key.token for key, _ in province_zones(game, seat))
    return [
        Choose(
            seat=seat,
            candidates=slots,
            minimum=1,
            maximum=1,
            resolver="tsudaos_grave_province",
            source_id=source_id,
            resolver_context=chosen,
            declinable=True,
        )
    ]


@choice_resolver("tsudaos_grave_province", prompt="Choose the Province to refill")
def _resolve_tsudaos_grave_province(
    game: GameState,
    source_id: str,
    chosen: tuple[str, ...],
    seat: PlayerId,
    resolver_context: tuple[str, ...] = (),
) -> list[Effect]:
    """Clear the Province and put the Event there face-up. The card already standing there is
    discarded to make room, since a full Province takes nothing. A Province named here and gone
    by the time the seat answers takes nothing either."""
    if not chosen:
        return []
    (found,) = resolver_context
    province = ZoneKey.from_token(chosen[0])
    zone = game.table.zones.get(province)
    if zone is None:
        return []
    standing = tuple(Discard(card.id, seat) for card in zone.cards)
    return [*standing, PlaceInProvince(found, province)]


register_ability(
    "tsudaos_grave",
    Ability(
        timings=(ActionTiming.OPEN,),
        cost=_tsudaos_grave_cost,
        targets=itself,
        effects=_tsudaos_grave_effects,
        hits_every_target=True,
    ),
)


# --- Walk with Tengoku ---


FUSHICHO = "fushicho_personality_3_2_3"


def _walk_with_tengoku_effects(game: GameState, source: L5RCard, target: L5RCard) -> list[Effect]:
    """A Fushicho for the turn: it burns out before the turn ends however the turn goes. The
    Ranged 3 Attack a battle lets the Shugenja bow for is not modeled."""
    return [CreateToken(FUSHICHO, source.owner, source.id, banish_at_turn_end=True)]


register_ability(
    "walk_with_tengoku",
    Ability(
        timings=(ActionTiming.BATTLE, ActionTiming.OPEN),
        cost=bow_cost,
        targets=itself,
        effects=_walk_with_tengoku_effects,
        hits_every_target=True,
    ),
)


# --- With Regards ---

WITH_REGARDS_GOLD = 4
WITH_REGARDS_FEWEST_TARGETED = 2


def _with_regards_cost(game: GameState, source: L5RCard) -> list[Effect]:
    return [PayGold(source.owner, WITH_REGARDS_GOLD, source.name)]


def _with_regards_targets(game: GameState, source: L5RCard, picked: PickedTargets) -> list[str]:
    """ "your unbowed Merchant or Ninja Personalities"."""
    wanted = {keywords.MERCHANT, keywords.NINJA}
    return [
        card.id
        for card in owned_personalities(game, source.owner)
        if not card.bowed and wanted & effective_keywords(game, card)
    ]


def _with_regards_count(
    game: GameState, source: L5RCard, picked: PickedTargets, offered: tuple[str, ...]
) -> tuple[int, int]:
    """ "two or more": every one on offer, if the seat likes, since each adds its Chi to what the
    action can destroy."""
    return WITH_REGARDS_FEWEST_TARGETED, len(offered)


def _with_regards_victims(game: GameState, source: L5RCard, picked: PickedTargets) -> list[str]:
    """ "a target Personality with a lower Gold Cost than the combined Chi of your Personalities
    this targeted": the first phrase settles the figure, so this one is read against it rather
    than limited as a set."""
    by_id = game.table.cards_by_id
    combined = sum(effective_chi(game, by_id[card_id]) for card_id in picked[0])
    return [
        card.id
        for card in personalities_in_play(game)
        if effective_gold_cost(game, card) < combined
    ]


def _with_regards_effects(
    game: GameState, source: L5RCard, groups: tuple[tuple[L5RCard, ...], ...]
) -> list[Effect]:
    """Bow the Merchants for an Open, destroy the Personality, take the Favor."""
    targeted, victims = groups
    seat = source.owner
    # Not a ``To``: that links one effect to one, and this sentence bows a whole phrase's worth of
    # cards, so the bow and the destruction are applied in the order the card prints them.
    taken_as_open = ActionTiming.BATTLE not in permitted_timings_in(game, action_round(game), seat)
    effects: list[Effect] = []
    if taken_as_open:
        effects.append(Simultaneously(tuple(Bow(card.id) for card in targeted)))
    effects.extend(Destroy(victim.id, seat) for victim in victims)
    effects.append(TakeFavor(seat))
    return effects


register_ability(
    "with_regards",
    Ability(
        timings=(ActionTiming.BATTLE, ActionTiming.OPEN),
        cost=_with_regards_cost,
        target_groups=(
            TargetGroup(
                candidates=_with_regards_targets,
                count=_with_regards_count,
                targeting_message="your unbowed Merchant or Ninja Personalities",
            ),
            TargetGroup(
                candidates=_with_regards_victims,
                targeting_message=(
                    "a Personality with a lower Gold Cost than your Personalities' combined Chi"
                ),
            ),
        ),
        effects_for_groups=_with_regards_effects,
        located_at=(CardLocation.HAND,),
    ),
)


# --- Yasuki Soden, Captain of the <i>Horokabe</i> (Experienced) ---

SODEN_PENALTY = -3


def _yasuki_soden_captain_of_the_i_horokabe_i_experienced_reaches(
    game: GameState, soden: L5RCard, card: L5RCard
) -> bool:
    """Your Commanders and Courage Followers at Soden's battlefield."""
    commander = has_keyword(game, card, keywords.COMMANDER)
    courage = is_follower(card) and has_keyword(game, card, keywords.COURAGE)
    return (commander or courage) and in_army_with(game, soden, card)


def _yasuki_soden_captain_of_the_i_horokabe_i_experienced_yu(ctx: TriggerContext) -> list[Effect]:
    """ "Yu: Draw a card." """
    return [DrawCard(ctx.card.owner)]


register_granted_yu(
    "yasuki_soden_captain_of_the_i_horokabe_i_experienced",
    _yasuki_soden_captain_of_the_i_horokabe_i_experienced_reaches,
    _yasuki_soden_captain_of_the_i_horokabe_i_experienced_yu,
)


def _yasuki_soden_captain_of_the_i_horokabe_i_experienced_targets(
    game: GameState, source: L5RCard
) -> list[str]:
    """The enemy army's cards."""
    attack = game.attack
    if attack is None or attack.current is None:
        return []
    return [card.id for card in army_at(game, attack.current, attack.enemy_of(source.owner))]


def _yasuki_soden_captain_of_the_i_horokabe_i_experienced_effects(
    game: GameState, source: L5RCard, target: L5RCard
) -> list[Effect]:
    """Give the target -3F, then open an additional action to the Battle abilities of your
    Followers in this army, when there is one to take."""
    penalty = GrantModifier(
        source.id, target.id, Stat.FORCE, SODEN_PENALTY, Duration.UNTIL_END_OF_TURN
    )
    here = location_of(game.table, source).battlefield
    if here is None:
        return [penalty]
    follow_ups = frozenset(
        ActivateAbility(card.id, ability.key)
        for card in army_at(game, here, source.owner)
        if is_follower(card)
        for ability in abilities_for(game, card)
        if ActionTiming.BATTLE in ability.timings
    )
    if not follow_ups:
        return [penalty]
    return [penalty, AdditionalAction(source.owner, source.id, follow_ups)]


register_ability(
    "yasuki_soden_captain_of_the_i_horokabe_i_experienced",
    Ability(
        timings=(ActionTiming.BATTLE,),
        cost=no_cost,
        targets=_yasuki_soden_captain_of_the_i_horokabe_i_experienced_targets,
        targeting_message="an enemy card",
        effects=_yasuki_soden_captain_of_the_i_horokabe_i_experienced_effects,
    ),
)


# --- Zealotry ---

# "Open: If you are an Akasha Clan player, put this Edict into play." Its Dynasty-phase trigger has
# no handler yet.
register_entry("zealotry", clears=keywords.EDICT, condition=plays_clan(ruleset.AKASHA))
