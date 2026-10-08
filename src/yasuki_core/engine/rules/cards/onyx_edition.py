from dataclasses import replace
from functools import cache

from yasuki_core import ruleset
from yasuki_core.engine.players import PlayerId
from yasuki_core.engine.rules.rulebook.lobby import register_may_not_lobby
from yasuki_core.engine.rules.abilities.costs import bow_cost, no_cost
from yasuki_core.engine.rules.abilities.idioms import (
    clan_player,
    one_wealth,
    register_entry,
    register_event_entry,
    register_ring,
    register_terrain,
    enemy_units_ever_present,
    register_trait_entry,
    resolved_favor_actions,
)
from yasuki_core.engine.rules.abilities.model import (
    Ability,
    CardLocation,
    Interrupt,
    Interruption,
    InvestAbility,
    TargetGroup,
    itself,
)
from yasuki_core.engine.rules.abilities.registry import (
    printed_ability_line,
    printed_line_without_cost,
    granted_ability,
    invest_amounts,
    register_ability,
    register_interrupt,
    register_invest,
)
from yasuki_core.engine.rules.vocabulary.actions import ActionTiming, BattleDesignator
from yasuki_core.engine.rules.vocabulary.decisions import PickedTargets
from yasuki_core.engine.rules.effects import (
    honor_loss_reduced_by,
    register_honor_loss_reduction,
    AdditionalAction,
    AdjustCounter,
    AlternateEffects,
    AskOption,
    Banish,
    Bow,
    Choose,
    CreateToken,
    DelayedEffect,
    Destroy,
    Discard,
    DiscardFromHand,
    DrawCard,
    Effect,
    Evaluate,
    Fear,
    GainHonor,
    GrantDuelStat,
    GrantKeyword,
    GrantModifier,
    GrantSeatAbility,
    MeleeAttack,
    Move,
    MoveToDeck,
    Negated,
    PayGold,
    PutIntoPlay,
    RevokeGrants,
    Show,
    ShuffleDeck,
    Simultaneously,
    SpendOncePerTurn,
    StartDuel,
    Straighten,
    TakeFavor,
    To,
    Unpayable,
)
from yasuki_core.engine.rules.rulebook.equip import (
    attach_restriction,
    creation_targets,
    equip_discount,
)
from yasuki_core.engine.rules.rulebook.kharmic import (
    KHARMIC_COST,
    KHARMIC_DRAW,
    KHARMIC_REFILL,
    is_kharmic_action,
    kharmic_ability,
)
from yasuki_core.engine.rules.vocabulary.game_events import (
    ActionResolved,
    BattleEnded,
    BattleResolved,
    CardDiscarded,
    Destroyed,
    DuelResolved,
    EnteredPlay,
    ProvinceDestroying,
)
from yasuki_core.engine.rules.state import GameState, used_this_turn
from yasuki_core.engine.rules.action_record import action_keywords, action_round
from yasuki_core.engine.rules.legality import permitted_timings_in
from yasuki_core.engine.rules.state_based_actions import ThresholdShift, register_threshold_shift
from yasuki_core.engine.rules.turn.structure import DUEL_CONSEQUENCES, END_OF_BATTLE
from yasuki_core.engine.rules.units.composition import followers_of, is_follower, unit_force
from yasuki_core.engine.rules.units.membership import attached_to, attachments_of, unit_of
from yasuki_core.engine.rules.triggers import TriggerContext, action_recruited, choice_resolver, on
from yasuki_core.engine.rules.board.clans import card_alignments
from yasuki_core.engine.rules.duel.procedure import duel_decided_by
from yasuki_core.engine.rules.board.counts_as import Asking, counts_as
from yasuki_core.engine.rules.board.queries import (
    ATTACK_TARGET,
    army_at,
    attack_targets,
    followers_in_play,
    has_keyword,
    opposed_units_in_battle,
    opposing_units_in_battle,
    outnumbered_at,
    owned_holdings,
    owned_personalities,
    personalities_in_play,
    rings_in_play,
    sincerity_seed_targets,
    top_of_deck,
    units_at,
)
from yasuki_core.engine.rules.board.seats import cards_in_hand, cards_in_play, has_compassion
from yasuki_core.engine.rules.rulebook.recruit_restrictions import register_recruit_restriction
from yasuki_core.engine.rules.stats.calculation import effective_stat
from yasuki_core.engine.rules.stats.card_values import (
    effective_chi,
    effective_force,
    effective_personal_honor,
)
from yasuki_core.engine.rules.stats.keyword_grants import keyword_grant
from yasuki_core.engine.rules.stats.stat_grants import stat_grant
from yasuki_core.engine.rules.vocabulary.modifiers import (
    Duration,
    EnlightenmentExclusion,
    SeatAbilityGrant,
    Stat,
)
from yasuki_core.engine.rules.vocabulary import keywords
from yasuki_core.engine.rules.vocabulary.segments import BattleSegment
from yasuki_core.engine.table import DeckKey, Location, location_of
from yasuki_core.game_pieces.cards import L5RCard
from yasuki_core.game_pieces.prints import (
    AttachmentPrint,
    PersonalityPrint,
    RingPrint,
    StrongholdPrint,
)
from yasuki_core.game_pieces.constants import Side
from yasuki_core.game_pieces.counters import PLUS_1F_PLUS_1C, SINCERITY, counter_from_key


# --- Daigotsu Hiromu ---


def _daigotsu_hiromu_followers(
    game: GameState, source: L5RCard, picked: PickedTargets
) -> list[str]:
    return [card.id for card in followers_in_play(game) if card.owner is source.owner]


def _daigotsu_hiromu_attacked(game: GameState, source: L5RCard, picked: PickedTargets) -> list[str]:
    return attack_targets(game, source, MeleeAttack)


def _daigotsu_hiromu_effects(
    game: GameState, source: L5RCard, groups: tuple[tuple[L5RCard, ...], ...]
) -> list[Effect]:
    """ "Bow or destroy your target Follower to make a Melee equal to its Force": the Melee is
    made only if the alternative chosen happened, and reads the Follower's Force as it last stood
    in play when that was its destruction."""
    (follower,), (attacked,) = groups
    seat = source.owner
    paid = AlternateEffects(
        seat,
        (Bow(follower.id), Destroy(follower.id, seat)),
        ("Bow it", "Destroy it"),
        f"Bow or destroy {follower.name}?",
        source.id,
    )
    return [To(paid, (MeleeAttack(0, attacked.id, seat, force_of=follower.id),))]


register_ability(
    "daigotsu_hiromu",
    Ability(
        timings=(ActionTiming.BATTLE,),
        cost=no_cost,
        target_groups=(
            TargetGroup(candidates=_daigotsu_hiromu_followers, targeting_message="your Follower"),
            TargetGroup(candidates=_daigotsu_hiromu_attacked, targeting_message=ATTACK_TARGET),
        ),
        effects_for_groups=_daigotsu_hiromu_effects,
    ),
)


# --- Daigotsu Rin ---


def _daigotsu_rin_targets(game: GameState, source: L5RCard) -> list[str]:
    """Himself, once the action just resolved Recruited him."""
    return [source.id] if action_recruited(game, source.id) else []


def _daigotsu_rin_effects(game: GameState, source: L5RCard, target: L5RCard) -> list[Effect]:
    """The seat may let the search fail even with an Undead Follower to find, and a deck holding
    none is still searched and shuffled (CR, Search)."""
    seat = source.owner
    undead = tuple(
        card.id
        for card in game.table.decks[DeckKey(seat, Side.FATE)].cards
        if is_follower(card) and has_keyword(game, card, keywords.UNDEAD)
    )
    if not undead:
        return [ShuffleDeck(DeckKey(seat, Side.FATE))]
    return [Choose(seat, undead, 0, 1, "daigotsu_rin", source.id)]


@choice_resolver("daigotsu_rin", prompt="You may put an Undead Follower into your discard pile")
def _resolve_daigotsu_rin(
    game: GameState, source_id: str, chosen: tuple[str, ...], seat: PlayerId
) -> list[Effect]:
    """The searched deck is shuffled whatever the search found (CR, Search)."""
    found = [Discard(card_id, seat) for card_id in chosen]
    return [*found, ShuffleDeck(DeckKey(seat, Side.FATE))]


register_ability(
    "daigotsu_rin",
    Ability(
        timings=(ActionTiming.RESPONSE,),
        cost=no_cost,
        targets=_daigotsu_rin_targets,
        effects=_daigotsu_rin_effects,
        hits_every_target=True,
    ),
)


# --- Daigotsu Shinobu ---

DAIGOTSU_SHINOBU_TOKEN = counter_from_key("plus1f")
DAIGOTSU_SHINOBU_MOST_FORCE_DESTROYED = 2

register_threshold_shift("daigotsu_shinobu", ThresholdShift(2, -2))


def _daigotsu_shinobu_targets(game: GameState, source: L5RCard) -> list[str]:
    return attack_targets(game, source, Fear)


def _daigotsu_shinobu_effects(game: GameState, source: L5RCard, target: L5RCard) -> list[Effect]:
    """ "If this bowed a card with 2 or lower Force": what follows depends on the Fear's bow
    actually happening, and reads the card's Force once it has."""
    seat = source.owner
    bowed = Evaluate("daigotsu_shinobu_bowed", source.id, seat, (target.id,))
    outcome = (To(Bow(target.id), (bowed,)),)
    return [Fear(0, target.id, seat, outcome=outcome, force_of=source.id)]


@choice_resolver("daigotsu_shinobu_bowed")
def _resolve_daigotsu_shinobu_bowed(
    game: GameState, source_id: str, chosen: tuple[str, ...], seat: PlayerId
) -> list[Effect]:
    """ "Destroy it and give Shinobu a +1F token." """
    (bowed_id,) = chosen
    if (
        effective_force(game, game.table.cards_by_id[bowed_id])
        > DAIGOTSU_SHINOBU_MOST_FORCE_DESTROYED
    ):
        return []
    return [Destroy(bowed_id, seat), AdjustCounter(source_id, DAIGOTSU_SHINOBU_TOKEN, 1)]


register_ability(
    "daigotsu_shinobu",
    Ability(
        timings=(ActionTiming.BATTLE,),
        cost=no_cost,
        targets=_daigotsu_shinobu_targets,
        targeting_message=ATTACK_TARGET,
        effects=_daigotsu_shinobu_effects,
    ),
)


# --- Daytiba ---

# "Daytiba cannot Lobby." His other line, that Favor actions cannot target him, has no handler yet.
register_may_not_lobby("daytiba")


# --- Death of the Mantis Clan ---

register_event_entry("death_of_the_mantis_clan")


# --- Doji Aoi, Soul of Doji Chitose ---


def _doji_aoi_soul_of_doji_chitose_targets(game: GameState, source: L5RCard) -> list[str]:
    """The controller's other Personalities, once the action just resolved was Political."""
    if keywords.POLITICAL not in action_keywords(game):
        return []
    return [card.id for card in owned_personalities(game, source.owner) if card.id != source.id]


def _doji_aoi_soul_of_doji_chitose_effects(
    game: GameState, source: L5RCard, target: L5RCard
) -> list[Effect]:
    return [Move(target.id, location_of(game.table, source)), Straighten(target.id)]


register_ability(
    "doji_aoi_soul_of_doji_chitose",
    Ability(
        timings=(ActionTiming.RESPONSE,),
        cost=no_cost,
        targets=_doji_aoi_soul_of_doji_chitose_targets,
        targeting_message="your Personality",
        effects=_doji_aoi_soul_of_doji_chitose_effects,
        battle_designators=frozenset({BattleDesignator.HOME}),
        targets_any_location=True,
        tireless=True,
    ),
)


# --- Fields of Slaughter ---

FIELDS_OF_SLAUGHTER_HONOR = 2


@on(Destroyed, "fields_of_slaughter")
def _fields_of_slaughter_destroyed(ctx: TriggerContext) -> list[Effect]:
    """ "Gain 2 Honor after each time a card at this battlefield that you do not control is
    destroyed." """
    event = ctx.event
    if not isinstance(event, Destroyed):
        return []
    here = location_of(ctx.game.table, ctx.card).battlefield
    if here is None or event.left_as.location.battlefield != here:
        return []
    if event.left_as.controller is ctx.card.owner:
        return []
    return [GainHonor(ctx.card.owner, FIELDS_OF_SLAUGHTER_HONOR, source_id=ctx.card.id)]


register_terrain(
    "fields_of_slaughter",
    timings=(ActionTiming.BATTLE, ActionTiming.ENGAGE),
    ability_keywords=frozenset({keywords.POLITICAL, keywords.TERRAIN}),
)


# --- Hida Haikeru ---


def _hida_haikeru_targets(game: GameState, source: L5RCard) -> list[str]:
    """The enemy Personalities Haikeru faces at the battle, which the card challenges."""
    return list(opposing_units_in_battle(game, source.owner))


def _hida_haikeru_effects(game: GameState, source: L5RCard, target: L5RCard) -> list[Effect]:
    """Challenge the target to a duel of Force.

    The CR names the duel stat per Personality rather than per duel, so a duel of Force is both
    duelists being told to compare it (CR, Duel Stat). The overrides are bound ahead of the duel so
    its declaration announces the stats it compares, and they lapse with the duel.
    """
    return [
        *(
            GrantDuelStat(source.id, duelist, Stat.FORCE, DUEL_CONSEQUENCES)
            for duelist in (source.id, target.id)
        ),
        StartDuel(source.id, target.id, source.id),
        DelayedEffect(Evaluate("hida_haikeru_loser", source.id, source.owner), DUEL_CONSEQUENCES),
    ]


@choice_resolver("hida_haikeru_loser")
def _resolve_hida_haikeru_loser(
    game: GameState, source_id: str, chosen: tuple[str, ...], seat: PlayerId
) -> list[Effect]:
    """Bow the challenged Personality if it lost. A tie is lost by both, so it is bowed then too,
    and nothing happens to Haikeru on any outcome."""
    duel = duel_decided_by(game, source_id)
    if duel is None or duel.challenged not in duel.outcome.losers:
        return []
    return [Bow(duel.challenged_duelist)]


register_ability(
    "hida_haikeru",
    Ability(
        timings=(ActionTiming.BATTLE,),
        cost=no_cost,
        targets=_hida_haikeru_targets,
        targeting_message="an enemy Personality",
        effects=_hida_haikeru_effects,
    ),
)


# --- Hida Shunsuke, Soul of Hida Tenshu ---


@attach_restriction("hida_shunsuke_soul_of_hida_tenshu")
def _hida_shunsuke_soul_of_hida_tenshu_attach_restriction(
    game: GameState, personality: L5RCard, card: L5RCard
) -> bool:
    """ "Will not attach Armor." """
    return not has_keyword(game, card, keywords.ARMOR)


@on(BattleEnded, "hida_shunsuke_soul_of_hida_tenshu")
def _hida_shunsuke_soul_of_hida_tenshu_battle_ended(ctx: TriggerContext) -> list[Effect]:
    """ "After a battle ends, if Shunsuke was at its battlefield during resolution and his army's
    Force was less than or equal to twice the other army's, destroy him." """
    if not isinstance(ctx.event, BattleEnded):
        return []
    resolved = ctx.event.resolved
    shunsuke = ctx.card
    if (shunsuke.owner, shunsuke.id) not in resolved.present_at_resolution:
        return []
    attacking = shunsuke.owner is resolved.attacker
    own = resolved.attacking_force if attacking else resolved.defending_force
    other = resolved.defending_force if attacking else resolved.attacking_force
    return [Destroy(shunsuke.id, shunsuke.owner)] if own <= 2 * other else []


# --- Hida War College (Experienced) ---

WAR_COLLEGE_FORCE = 2
WAR_COLLEGE_PRESSED_FORCE = 4

register_recruit_restriction("hida_war_college_experienced", clan_player(ruleset.CRAB))


def _hida_war_college_experienced_targets(game: GameState, source: L5RCard) -> list[str]:
    return [card.id for card in owned_personalities(game, source.owner)]


def _hida_war_college_experienced_pressed(game: GameState, personality: L5RCard) -> bool:
    """ "If they are defending or outnumbered", read at the battle being fought, where a Battle
    action's target stands."""
    attack = game.attack
    if attack is None or attack.current is None:
        return False
    seat = personality.owner
    return attack.defender is seat or outnumbered_at(game, attack.current, seat)


def _hida_war_college_experienced_effects(
    game: GameState, source: L5RCard, target: L5RCard
) -> list[Effect]:
    """The bonus runs to the end of the turn, as one with no printed duration does (CR, Duration
    of Effects)."""
    pressed = _hida_war_college_experienced_pressed(game, target)
    amount = WAR_COLLEGE_PRESSED_FORCE if pressed else WAR_COLLEGE_FORCE
    return [
        GrantModifier(source.id, target.id, Stat.FORCE, amount, Duration.UNTIL_END_OF_TURN),
        AdditionalAction(source.owner, source.id),
    ]


register_ability(
    "hida_war_college_experienced",
    Ability(
        timings=(ActionTiming.BATTLE,),
        cost=bow_cost,
        targets=_hida_war_college_experienced_targets,
        targeting_message="your Personality",
        effects=_hida_war_college_experienced_effects,
    ),
)


# --- Hida Yurike, Soul of Hida Rikyu ---


def _hida_yurike_soul_of_hida_rikyu_bow_targets(game: GameState, source: L5RCard) -> list[str]:
    """Enemy Personalities at the battle whose unit totals no more Force than Yurike's."""
    reach = unit_force(game, source)
    return [
        card_id
        for card_id in opposing_units_in_battle(game, source.owner)
        if unit_force(game, game.table.cards_by_id[card_id]) <= reach
    ]


def _hida_yurike_soul_of_hida_rikyu_bow_effects(
    game: GameState, source: L5RCard, target: L5RCard
) -> list[Effect]:
    """Bow every card in the target's unit (CR, Unit)."""
    return [Simultaneously(tuple(Bow(card.id) for card in unit_of(game, target)))]


register_ability(
    "hida_yurike_soul_of_hida_rikyu",
    Ability(
        timings=(ActionTiming.BATTLE,),
        cost=bow_cost,
        targets=_hida_yurike_soul_of_hida_rikyu_bow_targets,
        targeting_message="an enemy Personality whose unit has no more Force than Yurike's",
        effects=_hida_yurike_soul_of_hida_rikyu_bow_effects,
        key="bow",
    ),
)


def _hida_yurike_soul_of_hida_rikyu_straighten_targets(
    game: GameState, source: L5RCard
) -> list[str]:
    return [card.id for card in followers_of(game, source) if not card.bowed]


def _hida_yurike_soul_of_hida_rikyu_straighten_effects(
    game: GameState, source: L5RCard, target: L5RCard
) -> list[Effect]:
    """ "Bow Yurike's target Follower to straighten Yurike": Yurike straightens only if the Follower
    actually bows (CR, Independence of Effects)."""
    return [To(Bow(target.id), (Straighten(source.id),))]


register_ability(
    "hida_yurike_soul_of_hida_rikyu",
    Ability(
        printed_index=1,
        timings=(ActionTiming.BATTLE,),
        cost=no_cost,
        targets=_hida_yurike_soul_of_hida_rikyu_straighten_targets,
        targeting_message="Yurike's unbowed Follower",
        effects=_hida_yurike_soul_of_hida_rikyu_straighten_effects,
        tireless=True,
        key="straighten",
    ),
)


# --- Imperial Treasurer's Outpost ---


def _imperial_treasurers_outpost_effects(
    game: GameState, source: L5RCard, target: L5RCard
) -> list[Effect]:
    """If you have Compassion, draw a card. Read as the action resolves, so Compassion an
    Interrupt grants while it resolves counts."""
    return [DrawCard(source.owner)] if has_compassion(game, source.owner, source) else []


register_ability(
    "imperial_treasurers_outpost",
    Ability(
        timings=(ActionTiming.OPEN,),
        cost=no_cost,
        targets=itself,
        effects=_imperial_treasurers_outpost_effects,
        hits_every_target=True,
    ),
)


# --- Kaiu Denkaru ---

DENKARU_FORCE = 2
DENKARU_BONUS = "Give Denkaru +2F"
DENKARU_PENALTY = "Give a target enemy Follower or Personality -2F"


def _kaiu_denkaru_enemies(game: GameState, source: L5RCard) -> tuple[str, ...]:
    """The enemy Followers and Personalities at the battle being fought."""
    attack = game.attack
    if attack is None or attack.current is None:
        return ()
    return tuple(
        card.id
        for card in army_at(game, attack.current, attack.enemy_of(source.owner))
        if isinstance(card.printed, PersonalityPrint) or is_follower(card)
    )


def _kaiu_denkaru_targets(game: GameState, source: L5RCard) -> list[str]:
    """Denkaru himself, while he is opposed: unopposed, the ability does nothing."""
    return [source.id] if source.id in opposed_units_in_battle(game, source.owner) else []


def _kaiu_denkaru_effects(game: GameState, source: L5RCard, target: L5RCard) -> list[Effect]:
    """ "If Denkaru is opposed, either give him +2F or give a target enemy Follower or Personality
    -2F. If Denkaru is defending, you may do both." The penalty is offered only while an enemy can
    take it."""
    attack = game.attack
    if attack is None or source.id not in opposed_units_in_battle(game, source.owner):
        return []
    if _kaiu_denkaru_enemies(game, source):
        modes = (DENKARU_BONUS, DENKARU_PENALTY)
    else:
        modes = (DENKARU_BONUS,)
    defending = attack.defender is source.owner
    return [
        AskOption(
            source.owner,
            modes,
            "Kaiu Denkaru: give him +2F, or an enemy -2F?",
            "kaiu_denkaru",
            source.id,
            maximum=len(modes) if defending else 1,
        )
    ]


@choice_resolver("kaiu_denkaru")
def _resolve_kaiu_denkaru(
    game: GameState, source_id: str, chosen: tuple[str, ...], seat: PlayerId
) -> list[Effect]:
    """Both changes run to the end of the turn, as ones with no printed duration do (CR, Duration
    of Effects)."""
    effects: list[Effect] = []
    if DENKARU_BONUS in chosen:
        effects.append(
            GrantModifier(
                source_id, source_id, Stat.FORCE, DENKARU_FORCE, Duration.UNTIL_END_OF_TURN
            )
        )
    if DENKARU_PENALTY in chosen:
        enemies = _kaiu_denkaru_enemies(game, game.table.cards_by_id[source_id])
        effects.append(Choose(seat, enemies, 1, 1, "kaiu_denkaru_penalty", source_id))
    return effects


@choice_resolver("kaiu_denkaru_penalty", prompt="Give a target enemy Follower or Personality -2F")
def _resolve_kaiu_denkaru_penalty(
    game: GameState, source_id: str, chosen: tuple[str, ...], seat: PlayerId
) -> list[Effect]:
    return [
        GrantModifier(source_id, chosen[0], Stat.FORCE, -DENKARU_FORCE, Duration.UNTIL_END_OF_TURN)
    ]


register_ability(
    "kaiu_denkaru",
    Ability(
        timings=(ActionTiming.BATTLE,),
        cost=no_cost,
        targets=_kaiu_denkaru_targets,
        effects=_kaiu_denkaru_effects,
        hits_every_target=True,
    ),
)


# --- Kitsu Hayako ---

LION_ANCESTOR = "lion_ancestor"
ONE_ANCESTOR = 2
TWO_ANCESTORS = 6


def _kitsu_hayako_invest(game: GameState, source: L5RCard, amount: int) -> list[Effect]:
    """One 2F/2C/3PH Lion Ancestor for the lower of his two prices, and a second for the higher.

    Which price was paid, not how much: a discount moves both prices down together, so the second
    Ancestor goes with whichever price is higher at the time.

    Creates two separate Ancestor cards, not one counted twice.
    """
    ancestors = 2 if amount == max(invest_amounts(game, source)) else 1
    created = (CreateToken(LION_ANCESTOR, source.owner, source.id) for _ in range(ancestors))
    return [Simultaneously(tuple(created))]


register_invest(
    "kitsu_hayako",
    InvestAbility(amounts=(ONE_ANCESTOR, TWO_ANCESTORS), effect=_kitsu_hayako_invest),
)


# --- Mirumoto Higashi ---

MIRUMOTO_HIGASHI_TAG = "mirumoto_higashi_draw"


@on(EnteredPlay, "mirumoto_higashi")
def _mirumoto_higashi_entered_play(ctx: TriggerContext) -> list[Effect]:
    """Once per turn, after you put a Ring into play, draw a card. The trait asks, so a card
    counting as a Ring only for actions does not set it off."""
    entered = ctx.game.table.cards_by_id[ctx.event.card_id]
    if entered.owner is not ctx.card.owner:
        return []
    if not counts_as(ctx.game, entered, RingPrint, Asking.trait(ctx.card)):
        return []
    if used_this_turn(ctx.game, ctx.card, MIRUMOTO_HIGASHI_TAG):
        return []
    return [SpendOncePerTurn(ctx.card.id, MIRUMOTO_HIGASHI_TAG), DrawCard(ctx.card.owner)]


# --- Ring of Air ---

# "Play after you resolve two or more Favor actions in one turn."
register_trait_entry(
    "ring_of_air", ActionResolved, resolved_favor_actions(2), ruleset=ruleset.ONYX.name
)


def _ring_of_air_targets(game: GameState, source: L5RCard) -> list[str]:
    return [
        card.id
        for card in cards_in_play(game, source.owner)
        if card.bowed and isinstance(card.printed, PersonalityPrint | AttachmentPrint)
    ]


def _ring_of_air_effects(game: GameState, source: L5RCard, target: L5RCard) -> list[Effect]:
    return [Straighten(target.id)]


register_ring(
    "ring_of_air",
    ability=Ability(
        timings=(ActionTiming.BATTLE, ActionTiming.OPEN),
        cost=bow_cost,
        targets=_ring_of_air_targets,
        effects=_ring_of_air_effects,
        key="air",
        keywords=frozenset({keywords.AIR}),
        repeatable=True,
    ),
    pitch=printed_line_without_cost,
    ruleset=ruleset.ONYX.name,
)


# --- Ring of Earth ---

# The pitch is the Interrupt taken from hand, which the Interrupt step plays as a Strategy.


def _ring_of_earth_condition(ctx: TriggerContext) -> bool:
    """ "Play after a battle resolves at your Province, if it was not destroyed and any enemy units
    were ever at its battlefield." """
    event = ctx.event
    if not isinstance(event, BattleResolved) or event.province_destroyed:
        return False
    owner = ctx.card.owner
    return event.defender is owner and enemy_units_ever_present(event, owner)


register_trait_entry(
    "ring_of_earth", BattleResolved, _ring_of_earth_condition, ruleset=ruleset.ONYX.name
)


def _ring_of_earth_applies(game: GameState, source: L5RCard, effect: Move) -> bool:
    """A Battle action's moving of a Personality, read off the unit the Move names a card in."""
    if ActionTiming.BATTLE not in permitted_timings_in(game, action_round(game), source.owner):
        return False
    card = game.table.cards_by_id.get(effect.card_id)
    if card is None:
        return False
    return isinstance(card.printed, PersonalityPrint) or attached_to(game, card) is not None


def _ring_of_earth_interrupt(game: GameState, source: L5RCard, effect: Move) -> Interruption:
    return Interruption(Negated(effect))


register_interrupt(
    "ring_of_earth",
    Interrupt(
        answers=Move,
        interrupt=_ring_of_earth_interrupt,
        applies=_ring_of_earth_applies,
        located_at=(CardLocation.HAND, CardLocation.BATTLEFIELD),
        cost=bow_cost,
        answers_every=True,
        ruleset=ruleset.ONYX.name,
    ),
)


# --- Ring of Fire ---

# "Play after you win a duel during a battle, if your Personality did not enter the duel with
# higher Chi than the other." The entry has no handler: DuelDeclared records the duel stats the
# Personalities entered on, and a card can make that stat something other than Chi.


def _ring_of_fire_targets(game: GameState, source: L5RCard) -> list[str]:
    return [
        card.id
        for card in game.table.battlefield.cards
        if card.owner is not source.owner
        and not isinstance(card.printed, StrongholdPrint)
        and not attachments_of(game, card)
    ]


def _ring_of_fire_effects(game: GameState, source: L5RCard, target: L5RCard) -> list[Effect]:
    evaluation = Evaluate("ring_of_fire", source.id, source.owner, (target.id,))
    return [DelayedEffect(evaluation, END_OF_BATTLE)]


@choice_resolver("ring_of_fire")
def _resolve_ring_of_fire(
    game: GameState, source_id: str, chosen: tuple[str, ...], seat: PlayerId
) -> list[Effect]:
    """After the battle resolves, destroy the target if ``seat`` lost. A tie is not a loss."""
    outcome = game.attack.battlefields[game.attack.current].outcome
    lost = outcome.winner is not None and outcome.winner is not seat
    return [Destroy(chosen[0], seat)] if lost else []


register_ring(
    "ring_of_fire",
    ability=Ability(
        timings=(ActionTiming.BATTLE,),
        cost=bow_cost,
        targets=_ring_of_fire_targets,
        effects=_ring_of_fire_effects,
        key="fire",
        keywords=frozenset({keywords.FIRE}),
    ),
    pitch=printed_line_without_cost,
    ruleset=ruleset.ONYX.name,
)


# --- Ring of the Void ---

VOID_RINGS_ALLOWED = 2


def _ring_of_the_void_condition(game: GameState, source: L5RCard) -> bool:
    """ "Play if you have two or fewer Rings in play." """
    return len(rings_in_play(game, source.owner, Asking.action(source))) <= VOID_RINGS_ALLOWED


def _ring_of_the_void_entry_effects(game: GameState, source: L5RCard) -> list[Effect]:
    """ "Discard your hand." The Ring itself has entered play by the time these resolve, so it is
    left out of what was in hand."""
    held = tuple(card.id for card in cards_in_hand(game, source.owner) if card.id != source.id)
    return [DiscardFromHand(source.owner, len(held), source.owner, source.owner, candidates=held)]


register_entry(
    "ring_of_the_void",
    timing=ActionTiming.LIMITED,
    condition=_ring_of_the_void_condition,
    extra_effects=_ring_of_the_void_entry_effects,
    key="enter",
    ruleset=ruleset.ONYX.name,
)


def _ring_of_the_void_effects(game: GameState, source: L5RCard, target: L5RCard) -> list[Effect]:
    return [DrawCard(source.owner), Evaluate("ring_of_the_void", source.id, source.owner)]


@choice_resolver("ring_of_the_void")
def _resolve_ring_of_the_void(
    game: GameState, source_id: str, chosen: tuple[str, ...], seat: PlayerId
) -> list[Effect]:
    """After the draw, discard a card if the hand is now larger than every other player's."""
    hands = {
        each: tuple(card.id for card in cards_in_hand(game, each)) for each in game.table.seats
    }
    mine = hands.pop(seat)
    if len(mine) <= max((len(theirs) for theirs in hands.values()), default=0):
        return []
    return [DiscardFromHand(seat, 1, seat, seat)]


register_ring(
    "ring_of_the_void",
    ability=Ability(
        printed_index=1,
        timings=(ActionTiming.LIMITED,),
        cost=bow_cost,
        targets=itself,
        effects=_ring_of_the_void_effects,
        hits_every_target=True,
        key="void",
        keywords=frozenset({keywords.VOID}),
    ),
    pitch=printed_line_without_cost,
    ruleset=ruleset.ONYX.name,
)


# --- Ring of Water ---


def _ring_of_water_condition(ctx: TriggerContext) -> bool:
    """ "Play after a battle resolves in which you played a Terrain, destroyed a Terrain, and
    destroyed any cards or provinces during resolution." Resolution's destruction belongs to the
    seat whose enemy army it destroys, and a Province's to the Attacker (CR, Battle Resolution)."""
    event = ctx.event
    if not isinstance(event, BattleResolved):
        return False
    owner = ctx.card.owner
    played = any(seat is owner for seat, _ in event.terrains_played)
    destroyed_terrain = any(seat is owner for seat, _ in event.terrains_destroyed)
    destroyed_in_resolution = (event.province_destroyed and event.attacker is owner) or any(
        seat is not owner for seat in event.destroyed_controllers
    )
    return played and destroyed_terrain and destroyed_in_resolution


register_trait_entry(
    "ring_of_water",
    BattleResolved,
    _ring_of_water_condition,
    ruleset=ruleset.ONYX.name,
)


def _ring_of_water_targets(game: GameState, source: L5RCard) -> list[str]:
    """Your Personalities at the current battlefield, to move home, and, while an enemy unit is
    there to oppose him, your Personalities anywhere else, to move to it."""
    attack = game.attack
    if attack is None or attack.current is None:
        return []
    here, elsewhere = [], []
    for card in owned_personalities(game, source.owner):
        at_battle = location_of(game.table, card).battlefield == attack.current
        (here if at_battle else elsewhere).append(card.id)
    if not opposing_units_in_battle(game, source.owner):
        return here
    return here + elsewhere


def _ring_of_water_effects(game: GameState, source: L5RCard, target: L5RCard) -> list[Effect]:
    current = game.attack.current
    if location_of(game.table, target).battlefield == current:
        return [Move(target.id, Location.home(target.owner))]
    return [Move(target.id, Location.at_battlefield(current))]


register_ring(
    "ring_of_water",
    ability=Ability(
        timings=(ActionTiming.BATTLE,),
        cost=bow_cost,
        targets=_ring_of_water_targets,
        effects=_ring_of_water_effects,
        battle_designators=frozenset({BattleDesignator.ABSENT}),
        targets_any_location=True,
        key="water",
        keywords=frozenset({keywords.WATER}),
        repeatable=True,
    ),
    pitch=printed_line_without_cost,
    ruleset=ruleset.ONYX.name,
)


# --- Spearmen of the Akasha ---

NAGA_FOLLOWER = "naga"


@on(CardDiscarded, "spearmen_of_the_akasha")
def _spearmen_of_the_akasha_card_discarded(ctx: TriggerContext) -> list[Effect]:
    """After the Spearmen reach the discard from hand or deck, offer to banish them for a 1F Naga
    Follower on one of the seat's Naga Personalities.

    Nothing is offered with nobody to carry it. The Follower is the whole of what banishing buys, so
    a board with no Naga Personality leaves the card nothing it could do.
    """
    if ctx.event.card_id != ctx.card.id or not ctx.event.from_hand_or_deck:
        return []
    seat = ctx.card.owner
    naga = ctx.game.table.creatable_tokens[NAGA_FOLLOWER]
    bearers = tuple(
        bearer.id for bearer in creation_targets(ctx.game, seat, naga, keyword=keywords.NAGA)
    )
    if not bearers:
        return []
    return [Choose(seat, bearers, 0, 1, "spearmen_of_the_akasha", ctx.card.id)]


@choice_resolver("spearmen_of_the_akasha", prompt="Banish the Spearmen to Equip a Naga Follower")
def _resolve_spearmen_of_the_akasha(
    game: GameState, source_id: str, chosen: tuple[str, ...], seat: PlayerId
) -> list[Effect]:
    """Banishing is what buys the Follower, so declining
    leaves the Spearmen lying in the discard."""
    if not chosen:
        return []
    return [Banish(source_id), CreateToken(NAGA_FOLLOWER, seat, source_id, attach_to=chosen[0])]


# --- Tamori Tsushima ---

TAMORI_TSUSHIMA_GOLD = 3
DRAGON_YOJIMBO = "dragon_yojimbo_personality_2_2_2"
TAMORI_TSUSHIMA_CREATE = "Create and Recruit a Samurai Yojimbo"


def _tamori_tsushima_cost(game: GameState, source: L5RCard) -> list[Effect]:
    return [PayGold(source.owner, TAMORI_TSUSHIMA_GOLD, source.name)]


def _tamori_tsushima_targets(game: GameState, source: L5RCard) -> list[str]:
    """Himself, once the action just resolved Recruited him."""
    return [source.id] if action_recruited(game, source.id) else []


def _tamori_tsushima_effects(game: GameState, source: L5RCard, target: L5RCard) -> list[Effect]:
    """Create and Recruit (without further cost) a 2F/2C/3GC/2PH Samurai Yojimbo Dragon Clan
    Personality, or put a Ring from your hand into play. With no Ring in hand there is nothing to
    choose between."""
    rings = _tamori_tsushima_rings(game, source.id)
    if not rings:
        return [_tamori_tsushima_yojimbo(source.owner, source.id)]
    return [
        Choose(
            source.owner,
            rings,
            minimum=1,
            maximum=1,
            resolver="tamori_tsushima",
            source_id=source.id,
            options=(TAMORI_TSUSHIMA_CREATE,),
        )
    ]


def _tamori_tsushima_yojimbo(seat: PlayerId, source_id: str) -> CreateToken:
    return CreateToken(DRAGON_YOJIMBO, seat, source_id, recruit=True)


def _tamori_tsushima_rings(game: GameState, source_id: str) -> tuple[str, ...]:
    """The cards in his controller's hand that are Rings for his action."""
    source = game.table.cards_by_id[source_id]
    asking = Asking.action(source)
    return tuple(
        card.id
        for card in cards_in_hand(game, source.owner)
        if counts_as(game, card, RingPrint, asking)
    )


@choice_resolver(
    "tamori_tsushima",
    prompt="Pick a Ring to put into play",
    pick="Put this Ring into play, it does not count towards an Enlightenment Victory",
)
def _resolve_tamori_tsushima(
    game: GameState, source_id: str, chosen: tuple[str, ...], seat: PlayerId
) -> list[Effect]:
    """If the Ring enters play, while it remains in play it does not count towards an
    Enlightenment Victory. It enters under the exclusion, so the victory never sees it without."""
    (answer,) = chosen
    if answer == TAMORI_TSUSHIMA_CREATE:
        return [_tamori_tsushima_yojimbo(seat, source_id)]
    excluded = EnlightenmentExclusion(source_id, answer, Duration.PERMANENT)
    return [PutIntoPlay(answer, entering_under=(excluded,))]


register_ability(
    "tamori_tsushima",
    Ability(
        timings=(ActionTiming.RESPONSE,),
        cost=_tamori_tsushima_cost,
        targets=_tamori_tsushima_targets,
        effects=_tamori_tsushima_effects,
        hits_every_target=True,
    ),
)


# --- The Ancient Castle of the Lion ---

ANCIENT_CASTLE_HONOR = 1


def _the_ancient_castle_of_the_lion_targets(game: GameState, source: L5RCard) -> list[str]:
    """The enemy's defending Personalities: none while the Stronghold's controller defends."""
    attack = game.attack
    if attack is None or attack.attacker is not source.owner:
        return []
    return list(opposing_units_in_battle(game, source.owner))


def _the_ancient_castle_of_the_lion_effects(
    game: GameState, source: L5RCard, target: L5RCard
) -> list[Effect]:
    """ "Move home a target enemy defending Personality. You may target your Personality with
    higher Personal Honor to straighten this Stronghold and gain 1 Honor." The second target is
    optional, chosen as the ability resolves among the controller's Personalities at the battle."""
    honor = effective_personal_honor(game, target)
    higher = tuple(
        card.id
        for card in units_at(game, game.attack.current, source.owner)
        if effective_personal_honor(game, card) > honor
    )
    effects: list[Effect] = [Move(target.id, Location.home(target.owner))]
    if higher:
        effects.append(
            Choose(source.owner, higher, 0, 1, "the_ancient_castle_of_the_lion", source.id)
        )
    return effects


@choice_resolver(
    "the_ancient_castle_of_the_lion",
    prompt="You may target your Personality with higher Personal Honor to straighten this "
    "Stronghold and gain 1 Honor",
)
def _resolve_the_ancient_castle_of_the_lion(
    game: GameState, source_id: str, chosen: tuple[str, ...], seat: PlayerId
) -> list[Effect]:
    if not chosen:
        return []
    return [Straighten(source_id), GainHonor(seat, ANCIENT_CASTLE_HONOR, personalities=chosen)]


register_ability(
    "the_ancient_castle_of_the_lion",
    Ability(
        timings=(ActionTiming.BATTLE,),
        cost=bow_cost,
        targets=_the_ancient_castle_of_the_lion_targets,
        effects=_the_ancient_castle_of_the_lion_effects,
    ),
)


# --- The Ancient Castle of the Lion (back) ---


@stat_grant("the_ancient_castle_of_the_lion__back")
def _the_ancient_castle_of_the_lion__back_stat_grant(
    game: GameState, source: L5RCard, card: L5RCard, stat: Stat
) -> int:
    """Your attacking Lion Clan Personalities have +1F: the controller's Lion Personalities in an
    attacking army, at any battlefield of the controller's own attack (CR, Attack)."""
    attack = game.attack
    if stat is not Stat.FORCE or card.owner is not source.owner or attack is None:
        return 0
    if attack.attacker is not source.owner or ruleset.LION not in card_alignments(card):
        return 0
    return 1 if location_of(game.table, card).battlefield is not None else 0


def _the_ancient_castle_of_the_lion__back_effects(
    game: GameState, source: L5RCard, target: L5RCard
) -> list[Effect]:
    return [
        Move(target.id, Location.home(target.owner)),
        GainHonor(source.owner, ANCIENT_CASTLE_HONOR),
    ]


register_ability(
    "the_ancient_castle_of_the_lion__back",
    Ability(
        timings=(ActionTiming.BATTLE,),
        cost=bow_cost,
        targets=_the_ancient_castle_of_the_lion_targets,
        effects=_the_ancient_castle_of_the_lion__back_effects,
    ),
)


# --- The Dark Capital of the Spider ---

register_honor_loss_reduction("the_dark_capital_of_the_spider", honor_loss_reduced_by(1))
register_honor_loss_reduction("the_dark_capital_of_the_spider__back", honor_loss_reduced_by(2))


def _the_dark_capital_of_the_spider_targets(
    game: GameState, source: L5RCard, picked: PickedTargets
) -> list[str]:
    return [card.id for card in personalities_in_play(game)]


def _the_dark_capital_of_the_spider_feared(
    game: GameState, source: L5RCard, picked: PickedTargets
) -> list[str]:
    """The Fear's target, chosen with the action's other targets (CR, Good Faith Rule)."""
    return attack_targets(game, source, Fear)


def _the_dark_capital_of_the_spider_fear_count(
    game: GameState, source: L5RCard, picked: PickedTargets, offered: tuple[str, ...]
) -> tuple[int, int]:
    """One Fear target when the Personality targeted first is yours, and none otherwise, since
    there is then no Fear."""
    yours = game.table.cards_by_id[picked[0][0]].owner is source.owner
    return (1, 1) if yours else (0, 0)


def _the_dark_capital_of_the_spider_effects(
    game: GameState, source: L5RCard, groups: tuple[tuple[L5RCard, ...], ...]
) -> list[Effect]:
    """ "Give a target Personality Shadowlands. If they are yours, Fear equal to their Force.
    Otherwise, take an additional action." """
    (target,), feared = groups
    shadowlands = GrantKeyword(
        source.id, target.id, keywords.SHADOWLANDS, Duration.UNTIL_END_OF_TURN
    )
    if target.owner is not source.owner:
        return [shadowlands, AdditionalAction(source.owner, source.id)]
    fears = (Fear(0, card.id, source.owner, force_of=target.id) for card in feared)
    return [shadowlands, *fears]


register_ability(
    "the_dark_capital_of_the_spider",
    Ability(
        timings=(ActionTiming.BATTLE,),
        cost=no_cost,
        target_groups=(
            TargetGroup(candidates=_the_dark_capital_of_the_spider_targets),
            TargetGroup(
                candidates=_the_dark_capital_of_the_spider_feared,
                count=_the_dark_capital_of_the_spider_fear_count,
                targeting_message=ATTACK_TARGET,
            ),
        ),
        effects_for_groups=_the_dark_capital_of_the_spider_effects,
        tireless=True,
    ),
)


# --- The Dark Capital of the Spider (back) ---


def _the_dark_capital_of_the_spider__back_in_battle(game: GameState, source: L5RCard) -> bool:
    return ActionTiming.BATTLE in permitted_timings_in(game, action_round(game), source.owner)


def _the_dark_capital_of_the_spider__back_fear_count(
    game: GameState, source: L5RCard, picked: PickedTargets, offered: tuple[str, ...]
) -> tuple[int, int]:
    """As the front's, and only when "this is a Battle"."""
    if not _the_dark_capital_of_the_spider__back_in_battle(game, source):
        return (0, 0)
    return _the_dark_capital_of_the_spider_fear_count(game, source, picked, offered)


def _the_dark_capital_of_the_spider__back_effects(
    game: GameState, source: L5RCard, groups: tuple[tuple[L5RCard, ...], ...]
) -> list[Effect]:
    """ "If they are yours and this is a Battle, Fear equal to their Force. Otherwise, take an
    additional action." Taken as an Open, even on the controller's own Personality, it is the
    additional action."""
    if _the_dark_capital_of_the_spider__back_in_battle(game, source):
        return _the_dark_capital_of_the_spider_effects(game, source, groups)
    (target,), _ = groups
    return [
        GrantKeyword(source.id, target.id, keywords.SHADOWLANDS, Duration.UNTIL_END_OF_TURN),
        AdditionalAction(source.owner, source.id),
    ]


register_ability(
    "the_dark_capital_of_the_spider__back",
    Ability(
        timings=(ActionTiming.BATTLE, ActionTiming.OPEN),
        cost=no_cost,
        target_groups=(
            TargetGroup(candidates=_the_dark_capital_of_the_spider_targets),
            TargetGroup(
                candidates=_the_dark_capital_of_the_spider_feared,
                count=_the_dark_capital_of_the_spider__back_fear_count,
                targeting_message=ATTACK_TARGET,
            ),
        ),
        effects_for_groups=_the_dark_capital_of_the_spider__back_effects,
        tireless=True,
    ),
)


# --- The Indomitable Fortress of the Crab ---


def _the_indomitable_fortress_of_the_crab_targets(game: GameState, source: L5RCard) -> list[str]:
    return list(opposed_units_in_battle(game, source.owner))


def _the_indomitable_fortress_of_the_crab_effects(
    game: GameState, source: L5RCard, target: L5RCard
) -> list[Effect]:
    """ "Straighten your target opposed Personality. Straighten their attachments if your current
    army is outnumbered." """
    effects: list[Effect] = [Straighten(target.id)]
    attack = game.attack
    if attack is None or attack.current is None:
        return effects
    if outnumbered_at(game, attack.current, source.owner):
        attachments = attachments_of(game, target)
        effects.append(Simultaneously(tuple(Straighten(attached.id) for attached in attachments)))
    return effects


def _the_indomitable_fortress_of_the_crab_cost(game: GameState, source: L5RCard) -> list[Effect]:
    """ "If you bow your Fortification when announcing it": one of your unbowed Fortifications,
    chosen and bowed as the ability is announced."""
    fortifications = tuple(
        card.id
        for card in owned_holdings(game, source.owner, keywords.FORTIFICATION)
        if not card.bowed
    )
    if not fortifications:
        return [Unpayable(f"{source.owner.name} has no unbowed Fortification")]
    return [
        Choose(
            source.owner, fortifications, 1, 1, "the_indomitable_fortress_of_the_crab", source.id
        )
    ]


@choice_resolver(
    "the_indomitable_fortress_of_the_crab", prompt="Bow your Fortification for Tireless"
)
def _resolve_the_indomitable_fortress_of_the_crab(
    game: GameState, source_id: str, chosen: tuple[str, ...], seat: PlayerId
) -> list[Effect]:
    return [Bow(chosen[0])]


def _the_indomitable_fortress_of_the_crab_battle_bowing_a_fortification_label(
    card: L5RCard, index: int
) -> str:
    return f"{printed_ability_line(card, index)} (bow your Fortification: Tireless)"


register_ability(
    "the_indomitable_fortress_of_the_crab",
    Ability(
        timings=(ActionTiming.BATTLE,),
        cost=no_cost,
        targets=_the_indomitable_fortress_of_the_crab_targets,
        targeting_message="your opposed Personality",
        effects=_the_indomitable_fortress_of_the_crab_effects,
        key="battle",
    ),
)

# One printed ability, offered twice: as printed, and with the Fortification bowed at announcement,
# which gives it Tireless. Both count as its one use this turn.
register_ability(
    "the_indomitable_fortress_of_the_crab",
    Ability(
        timings=(ActionTiming.BATTLE,),
        label=_the_indomitable_fortress_of_the_crab_battle_bowing_a_fortification_label,
        cost=_the_indomitable_fortress_of_the_crab_cost,
        targets=_the_indomitable_fortress_of_the_crab_targets,
        targeting_message="your opposed Personality",
        effects=_the_indomitable_fortress_of_the_crab_effects,
        tireless=True,
        key="battle_bowing_a_fortification",
        limit_key="battle",
    ),
)


# --- The Indomitable Fortress of the Crab (back) ---


@keyword_grant("the_indomitable_fortress_of_the_crab__back")
def _the_indomitable_fortress_of_the_crab__back_keywords(
    game: GameState, fortress: L5RCard, card: L5RCard
) -> tuple[str, ...]:
    """ "The first time each turn you Recruit a Fortification, refill its Province face-up", read
    as your Fortifications having Renew until another of them has been Recruited this turn. A
    Recruit's refill reads Renew before its own arrival is recorded."""
    if not _the_indomitable_fortress_of_the_crab__back_yours(fortress, card):
        return ()
    recruited_earlier = any(
        isinstance(event, EnteredPlay)
        and event.recruited
        and event.card_id != card.id
        and _the_indomitable_fortress_of_the_crab__back_yours(
            fortress, game.table.cards_by_id[event.card_id]
        )
        for event in game.turn_events
    )
    return () if recruited_earlier else (keywords.RENEW,)


def _the_indomitable_fortress_of_the_crab__back_yours(fortress: L5RCard, card: L5RCard) -> bool:
    """Whether ``card`` is a Fortification of the Fortress's controller. Its printed keywords are
    read, since this grant is itself part of its effective keywords."""
    return card.owner is fortress.owner and keywords.FORTIFICATION in card.keywords


register_ability(
    "the_indomitable_fortress_of_the_crab__back",
    Ability(
        timings=(ActionTiming.BATTLE,),
        cost=no_cost,
        targets=_the_indomitable_fortress_of_the_crab_targets,
        targeting_message="your opposed Personality",
        effects=_the_indomitable_fortress_of_the_crab_effects,
        tireless=True,
    ),
)


# --- The Palatial Estate of the Crane ---


def _the_palatial_estate_of_the_crane_targets(game: GameState, source: L5RCard) -> list[str]:
    """Itself, once the action just resolved was its controller's and paid the Favor."""
    paid = game.action_is_favor and game.action_seat is source.owner
    return [source.id] if paid else []


def _the_palatial_estate_of_the_crane_effects(
    game: GameState, source: L5RCard, target: L5RCard
) -> list[Effect]:
    return [TakeFavor(source.owner)]


register_ability(
    "the_palatial_estate_of_the_crane",
    Ability(
        timings=(ActionTiming.RESPONSE,),
        keywords=frozenset({keywords.POLITICAL}),
        cost=no_cost,
        targets=_the_palatial_estate_of_the_crane_targets,
        effects=_the_palatial_estate_of_the_crane_effects,
        hits_every_target=True,
    ),
)


# --- The Sacred Ground of the Phoenix ---


def _the_sacred_ground_of_the_phoenix_effects(
    game: GameState, source: L5RCard, target: L5RCard
) -> list[Effect]:
    return [
        GrantSeatAbility(source.id, source.owner, (form, source.id), Duration.UNTIL_END_OF_TURN)
        for form in (KHARMIC_DRAW, KHARMIC_REFILL)
    ]


# Cached: the factory runs on every read of every card the seat owns, for two forms at two prices.
@cache
def _the_sacred_ground_of_the_phoenix_licensed(context: tuple[str, ...], *, free: bool) -> Ability:
    """The rulebook Kharmic ability of the form ``context`` names, as the Stronghold licenses it:
    under the rulebook ability's own key, so it stands in for it on a Kharmic card and is the only
    one on any other, and costing nothing when ``free``. The label rewords the datasheet's clause
    for the card it sits on."""
    form, _ = context
    rulebook = kharmic_ability(form)
    outcome = "draw a card" if form == KHARMIC_DRAW else "refill its Province face-up"
    designator = "Open" if free else f"Open, :g{KHARMIC_COST}:"
    return replace(
        rulebook,
        label=f"{designator}: Discard this card to {outcome}",
        cost=no_cost if free else rulebook.cost,
    )


def _the_sacred_ground_of_the_phoenix_action_resolved(ctx: TriggerContext) -> list[Effect]:
    """Revoke the license once the seat has used the rulebook Kharmic ability: "the next time (this
    turn)". After the action, so every trigger and the Response Step read the licensed ability as
    the action's own, and outside its effects, so nothing offers the revoke to an Interrupt."""
    licensed = any(
        isinstance(recorded, SeatAbilityGrant) and recorded.source_id == ctx.card.id
        for recorded in ctx.game.ongoing
    )
    if not licensed or ctx.event.seat is not ctx.card.owner or not is_kharmic_action(ctx.game):
        return []
    return [RevokeGrants(ctx.card.id)]


on(ActionResolved, "the_sacred_ground_of_the_phoenix")(
    _the_sacred_ground_of_the_phoenix_action_resolved
)

register_ability(
    "the_sacred_ground_of_the_phoenix",
    Ability(
        timings=(ActionTiming.OPEN,),
        cost=no_cost,
        targets=itself,
        effects=_the_sacred_ground_of_the_phoenix_effects,
        hits_every_target=True,
    ),
)


@granted_ability("the_sacred_ground_of_the_phoenix")
def _the_sacred_ground_of_the_phoenix_granted_ability(
    game: GameState, card: L5RCard, context: tuple[str, ...]
) -> Ability:
    """The front's "or": free on a Kharmic card and the printed gold on any other, decided by the
    card the seat spends."""
    return _the_sacred_ground_of_the_phoenix_licensed(
        context, free=has_keyword(game, card, keywords.KHARMIC)
    )


# --- The Sacred Ground of the Phoenix (back) ---

on(ActionResolved, "the_sacred_ground_of_the_phoenix__back")(
    _the_sacred_ground_of_the_phoenix_action_resolved
)


register_ability(
    "the_sacred_ground_of_the_phoenix__back",
    Ability(
        timings=(ActionTiming.OPEN,),
        cost=no_cost,
        targets=itself,
        effects=_the_sacred_ground_of_the_phoenix_effects,
        hits_every_target=True,
    ),
)


@granted_ability("the_sacred_ground_of_the_phoenix__back")
def _the_sacred_ground_of_the_phoenix__back_granted_ability(
    game: GameState, card: L5RCard, context: tuple[str, ...]
) -> Ability:
    """The back's "and": free on any card."""
    return _the_sacred_ground_of_the_phoenix_licensed(context, free=True)


# --- Togashi Hiyoku ---


@on(DuelResolved, "togashi_hiyoku")
def _togashi_hiyoku_duel_resolved(ctx: TriggerContext) -> list[Effect]:
    """ "After Hiyoku wins a duel during battle, give him a +1F/+1C token."

    Any duel he wins, not only the one his own ability creates. Whether a battle is being fought is
    read off the attack rather than off the open round, because a duel's steps stand over a battle
    segment without being one. Both Personalities can win a duel, and Hiyoku is given his token on
    either reading.
    """
    event = ctx.event
    if not isinstance(event, DuelResolved):
        return []
    duel, attack = ctx.game.duel, ctx.game.attack
    if duel is None or attack is None or attack.current is None:
        return []
    if ctx.card.id not in (duel.challenger_duelist, duel.challenged_duelist):
        return []
    if ctx.card.owner not in event.winners:
        return []
    return [AdjustCounter(ctx.card.id, PLUS_1F_PLUS_1C, 1)]


def _togashi_hiyoku_targets(game: GameState, source: L5RCard) -> list[str]:
    """The enemy Personalities Hiyoku faces at the battle, which the card challenges."""
    return list(opposing_units_in_battle(game, source.owner))


def _togashi_hiyoku_effects(game: GameState, source: L5RCard, target: L5RCard) -> list[Effect]:
    """ "Hiyoku challenges a target enemy Personality. The winner may take an additional action."

    The duel compares the arc's duel stat, since the card names none, and nothing happens to the
    loser. Who won is known only once the duel is decided, so the offer waits for the duel's end.
    """
    return [
        StartDuel(source.id, target.id, source.id),
        DelayedEffect(
            Evaluate("togashi_hiyoku_winner", source.id, source.owner), DUEL_CONSEQUENCES
        ),
    ]


@choice_resolver("togashi_hiyoku_winner")
def _resolve_togashi_hiyoku_winner(
    game: GameState, source_id: str, chosen: tuple[str, ...], seat: PlayerId
) -> list[Effect]:
    """Give whoever won, which may be the challenged seat, the additional action. The "may" is the
    seat's to exercise by taking the action or declining it. A tie neither won grants nothing."""
    duel = duel_decided_by(game, source_id)
    if duel is None:
        return []
    return [AdditionalAction(winner, source_id) for winner in duel.outcome.winners]


register_ability(
    "togashi_hiyoku",
    Ability(
        timings=(ActionTiming.BATTLE,),
        cost=no_cost,
        targets=_togashi_hiyoku_targets,
        targeting_message="an enemy Personality",
        effects=_togashi_hiyoku_effects,
    ),
)


# --- Togashi's Library ---

register_recruit_restriction("togashis_library", clan_player(ruleset.DRAGON))


def _togashis_library_targets(game: GameState, source: L5RCard) -> list[str]:
    return [card.id for card in owned_personalities(game, source.owner) if not card.bowed]


def _togashis_library_effects(game: GameState, source: L5RCard, target: L5RCard) -> list[Effect]:
    """Show the top card of your Fate deck, and draw it if its Focus Value is less than the
    target's Chi. Otherwise it goes to the bottom of the deck. An empty deck shows nothing."""
    seat = source.owner
    fate = DeckKey(seat, Side.FATE)
    seen = top_of_deck(game, fate, 1)
    if not seen:
        return []
    top = game.table.cards_by_id[seen[0]]
    if effective_stat(game, top, Stat.FOCUS) < effective_chi(game, target):
        return [Show(top.id), DrawCard(seat)]
    return [Show(top.id), MoveToDeck(top.id, fate, from_bottom=0)]


register_ability(
    "togashis_library",
    Ability(
        timings=(ActionTiming.OPEN,),
        cost=bow_cost,
        targets=_togashis_library_targets,
        targeting_message="your unbowed Personality",
        effects=_togashis_library_effects,
    ),
)


# --- Training Court ---


def _training_court_targets(game: GameState, source: L5RCard) -> list[str]:
    """The controller's token-less Sincerity cards still in a Province, once the action just
    resolved was the one that Recruited this Holding."""
    if not action_recruited(game, source.id):
        return []
    return sincerity_seed_targets(game, source.owner)


def _training_court_effects(game: GameState, source: L5RCard, target: L5RCard) -> list[Effect]:
    return [AdjustCounter(target.id, SINCERITY, 1)]


register_ability(
    "training_court",
    Ability(
        # Tireless, so it asks nothing of the Holding it is on: a Response costs no bow, and this
        # one is taken in the Step that follows the Recruit which brought the Holding into play.
        timings=(ActionTiming.RESPONSE,),
        keywords=frozenset({keywords.POLITICAL}),
        cost=no_cost,
        targets=_training_court_targets,
        targeting_message="a Sincerity card without tokens in your Province",
        effects=_training_court_effects,
        tireless=True,
    ),
)

register_invest("training_court", InvestAbility(amounts=(1,), effect=one_wealth))


# --- Utaku Gorou, Stablemaster ---

CAVALRY_FOLLOWER = "cavalry"


def _utaku_gorou_stablemaster_targets(game: GameState, source: L5RCard) -> list[str]:
    cavalry = game.table.creatable_tokens[CAVALRY_FOLLOWER]
    riders = creation_targets(game, source.owner, cavalry, keyword=keywords.SAMURAI)
    return [rider.id for rider in riders]


def _utaku_gorou_stablemaster_effects(
    game: GameState, source: L5RCard, target: L5RCard
) -> list[Effect]:
    return [CreateToken(CAVALRY_FOLLOWER, source.owner, source.id, attach_to=target.id)]


register_ability(
    "utaku_gorou_stablemaster",
    Ability(
        timings=(ActionTiming.OPEN,),
        cost=bow_cost,
        targets=_utaku_gorou_stablemaster_targets,
        targeting_message="your Samurai",
        effects=_utaku_gorou_stablemaster_effects,
    ),
)


# --- Yamigatai (Experienced) ---

YAMIGATAI_EQUIP_DISCOUNT = 1
YAMIGATAI_COMBAT_FORCE = 2


@attach_restriction("yamigatai_experienced")
def _yamigatai_experienced_attach_restriction(
    game: GameState, personality: L5RCard, card: L5RCard
) -> bool:
    """ "Will not attach to a Shadowlands Personality." """
    return not has_keyword(game, personality, keywords.SHADOWLANDS)


@equip_discount("yamigatai_experienced")
def _yamigatai_experienced_equip_discount(
    game: GameState, personality: L5RCard, card: L5RCard
) -> int:
    """ "Equips to a Crab Clan Personality for 1 less." """
    return YAMIGATAI_EQUIP_DISCOUNT if ruleset.CRAB in card_alignments(personality) else 0


@on(ProvinceDestroying, "yamigatai_experienced")
def _yamigatai_experienced_province_destroying(ctx: TriggerContext) -> list[Effect]:
    """ "Before this Personality's army destroys a Province, put the Ring of Earth into play from
    your hand." The army destroys a Province at its battle's resolution."""
    event = ctx.event
    bearer = attached_to(ctx.game, ctx.card)
    if (
        not isinstance(event, ProvinceDestroying)
        or bearer is None
        or event.seat is not bearer.owner
    ):
        return []
    attack = ctx.game.attack
    if (
        attack is None
        or attack.current is None
        or attack.battle_segment is not BattleSegment.RESOLUTION
    ):
        return []
    at_battle = location_of(ctx.game.table, bearer).battlefield == attack.current
    if not at_battle or attack.current_province != event.province:
        return []
    hand = cards_in_hand(ctx.game, bearer.owner)
    ring = next((card for card in hand if card.printed_id == "ring_of_earth"), None)
    return [] if ring is None else [PutIntoPlay(ring.id)]


@stat_grant("yamigatai_experienced")
def _yamigatai_experienced_stat_grant(
    game: GameState, yamigatai: L5RCard, card: L5RCard, stat: Stat
) -> int:
    """ "This Personality has +2F during the Combat Segment (not battle resolution)." """
    if stat is not Stat.FORCE or card is not attached_to(game, yamigatai):
        return 0
    attack = game.attack
    in_combat = attack is not None and attack.battle_segment is BattleSegment.COMBAT
    return YAMIGATAI_COMBAT_FORCE if in_combat else 0
