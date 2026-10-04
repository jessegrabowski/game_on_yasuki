from dataclasses import replace

from yasuki_core import ruleset
from yasuki_core.engine.players import PlayerId, Trait
from yasuki_core.engine.rules.abilities.costs import bow_cost, ignoring_bow_costs, no_cost
from yasuki_core.engine.rules.abilities.idioms import (
    RING_PITCH,
    plays_clan,
    register_condition_entry,
    register_entry,
    register_ring,
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
    itself,
    once_tag,
)
from yasuki_core.engine.rules.abilities.registry import (
    before_entering_play,
    granted_ability,
    granted_interrupt,
    printed_abilities,
    printed_interrupt,
    register_ability,
    register_cannot_attack,
    register_interrupt,
    register_invest,
)
from yasuki_core.engine.rules.vocabulary.actions import (
    Action,
    ActionTiming,
    ActivateAbility,
    BattleDesignator,
    PlayInterrupt,
    PlayStrategy,
)
from yasuki_core.engine.rules.board.clans import card_alignments
from yasuki_core.engine.rules.board.seats import (
    cards_in_hand,
    cards_in_play,
    fate_cards_in_play,
    seat_wind,
)
from yasuki_core.engine.rules.board.counts_as import (
    AskedBy,
    Asking,
    CountsAs,
    anywhere,
    counts_as,
    register_counts_as,
)
from yasuki_core.engine.rules.board.queries import (
    ATTACK_TARGET,
    attack_targets,
    controls_terrain_at,
    followers_in_play,
    has_keyword,
    opposed_units_in_battle,
    opposing_units_in_battle,
    owned_personalities,
    personalities_in_play,
    province_zones,
    rings_in_play,
    top_of_deck,
    units_at,
)
from yasuki_core.engine.rules.effects import (
    AdditionalAction,
    Bow,
    Choose,
    CreateToken,
    DelayedEffect,
    Destroy,
    DiscardFromHand,
    Dishonor,
    DrawCard,
    Effect,
    EndLook,
    Evaluate,
    GrantDuelStat,
    GrantProvinceStrength,
    GainHonor,
    GrantModifier,
    GrantNegation,
    GrantSeatAbility,
    LookAtTop,
    MeleeAttack,
    Move,
    MoveToDeck,
    Negated,
    Rehonor,
    ShuffleDeck,
    SpendOncePerTurn,
    Straighten,
    seppuku,
)
from yasuki_core.engine.rules.gold.discounts import recruit_discount
from yasuki_core.engine.rules.rulebook.lobby import lobby_bar, lobby_bonus_grant
from yasuki_core.engine.rules.rulebook.recruit import proclaim_gain
from yasuki_core.engine.rules.stats.card_values import (
    effective_chi,
    effective_force,
    effective_personal_honor,
)
from yasuki_core.engine.rules.stats.keyword_grants import effective_keywords
from yasuki_core.engine.rules.stats.calculation import unbounded_stat
from yasuki_core.engine.rules.stats.stat_grants import stat_grant
from yasuki_core.engine.rules.action_record import action_round
from yasuki_core.engine.rules.interrupts import INTERRUPT_TAG, answered_by
from yasuki_core.engine.rules.legality import permitted_timings_in
from yasuki_core.engine.rules.triggers import TriggerContext, action_did, choice_resolver, on
from yasuki_core.engine.rules.duel.focus_effects import focus_effect
from yasuki_core.engine.rules.duel.procedure import decided_duel, decided_outcome
from yasuki_core.engine.rules.turn.structure import (
    ADDITIONAL_ACTION_SPENT,
    DUEL_CONSEQUENCES,
    END_OF_BATTLE,
    END_OF_TURN,
)
from yasuki_core.engine.rules.units.membership import attached_to, attachments_of, unit_of
from yasuki_core.engine.rules.vocabulary import keywords
from yasuki_core.engine.rules.vocabulary.modifiers import Duration, Negation, Stat
from yasuki_core.engine.rules.vocabulary.segments import Boundary
from yasuki_core.engine.rules.vocabulary.game_events import (
    ActionResolved,
    BattleResolved,
    Bowed,
    DuelDeclared,
    DuelResolved,
    FavorDiscarded,
    HonorChanged,
    TurnBoundary,
)
from yasuki_core.engine.rules.rulebook.equip import creation_targets
from yasuki_core.engine.rules.state import GameState, used_this_turn
from yasuki_core.engine.table import DeckKey, Location, ZoneKey, ZoneRole, location_of
from yasuki_core.game_pieces.cards import L5RCard
from yasuki_core.game_pieces.constants import Side
from yasuki_core.game_pieces.prints import (
    AttachmentPrint,
    FatePrint,
    PersonalityPrint,
    RingPrint,
)


# --- Daidoji Tashiko ---

TASHIKO_HONOR = 2

register_cannot_attack("daidoji_tashiko")


@stat_grant("daidoji_tashiko")
def _daidoji_tashiko_stat_grant(game: GameState, source: L5RCard, card: L5RCard, stat: Stat) -> int:
    """While opposed, a Force bonus equal to the highest Personal Honor among Courtiers in her
    army."""
    if card is not source or stat is not Stat.FORCE:
        return 0
    if source.id not in opposed_units_in_battle(game, source.owner):
        return 0
    honors = [
        effective_personal_honor(game, personality)
        for personality in units_at(game, game.attack.current, source.owner)
        if has_keyword(game, personality, keywords.COURTIER)
    ]
    return max(honors, default=0)


def _daidoji_tashiko_effects(game: GameState, source: L5RCard, target: L5RCard) -> list[Effect]:
    return [DelayedEffect(Evaluate("daidoji_tashiko", source.id, source.owner), END_OF_BATTLE)]


@choice_resolver("daidoji_tashiko")
def _resolve_daidoji_tashiko(
    game: GameState, source_id: str, chosen: tuple[str, ...], seat: PlayerId
) -> list[Effect]:
    """After the battle resolves, gain 2 Honor if its Province was not destroyed. Every battle is
    fought at a Province, so "if it was at a Province" always holds."""
    outcome = game.attack.battlefields[game.attack.current].outcome
    return [] if outcome.province_destroyed else [GainHonor(seat, TASHIKO_HONOR)]


register_ability(
    "daidoji_tashiko",
    Ability(
        timings=(ActionTiming.ENGAGE,),
        cost=no_cost,
        targets=itself,
        effects=_daidoji_tashiko_effects,
        hits_every_target=True,
    ),
)


# --- Doji Meiji, Regent (Experienced) ---


@proclaim_gain("doji_meiji_regent_experienced")
def _doji_meiji_regent_experienced_proclaim_gain(game: GameState, card: L5RCard) -> int:
    """When Proclaiming Meiji, you may choose to gain Honor equal to his Chi instead of equal to
    his Personal Honor."""
    return effective_chi(game, card)


@lobby_bar("doji_meiji_regent_experienced")
def _doji_meiji_regent_experienced_lobby_bar(
    game: GameState, card: L5RCard, seat: PlayerId
) -> bool:
    """While Meiji is unbowed, players without your Wind may not Lobby.

    "Your Wind" names a Wind his controller has, so a controller with none bars nobody; this is
    a ruling, the CR being silent. A rival with no Wind, or a different one, is without yours.
    His Political Open has no handler yet: it waits on duels and on a per-turn record of Favor
    discards.
    """
    if card.bowed or seat is card.owner:
        return False
    yours = seat_wind(game, card.owner)
    if yours is None:
        return False
    theirs = seat_wind(game, seat)
    return theirs is None or theirs.printed_id != yours.printed_id


# --- Doji Yasuko, Soul of Doji Takeji ---

YASUKO_DISCOUNT = 2
YASUKO_COMPANIONS = (keywords.DUELIST, keywords.COURTIER)


@recruit_discount("doji_yasuko_soul_of_doji_takeji")
def _doji_yasuko_soul_of_doji_takeji_recruit_discount(
    card: L5RCard, game: GameState, seat: PlayerId
) -> int:
    """Enters play for 2 less while the seat controls a Crane Clan Duelist or Courtier."""
    for personality in owned_personalities(game, seat):
        if ruleset.CRANE not in card_alignments(personality):
            continue
        if any(word in effective_keywords(game, personality) for word in YASUKO_COMPANIONS):
            return YASUKO_DISCOUNT
    return 0


def _doji_yasuko_soul_of_doji_takeji_targets(game: GameState, source: L5RCard) -> list[str]:
    """Itself, once the action just resolved was a Strategy from which a player gained Honor."""
    if not isinstance(game.action, PlayStrategy):
        return []
    gained = any(event.amount > 0 for event in action_did(game, HonorChanged))
    return [source.id] if gained else []


def _doji_yasuko_soul_of_doji_takeji_effects(
    game: GameState, source: L5RCard, target: L5RCard
) -> list[Effect]:
    return [DrawCard(source.owner)]


register_ability(
    "doji_yasuko_soul_of_doji_takeji",
    Ability(
        timings=(ActionTiming.RESPONSE,),
        keywords=frozenset({keywords.POLITICAL}),
        cost=no_cost,
        targets=_doji_yasuko_soul_of_doji_takeji_targets,
        effects=_doji_yasuko_soul_of_doji_takeji_effects,
        hits_every_target=True,
    ),
)


# --- Hida Sanjiro ---

SANJIROS_ARMOR = "armor_item_plus2f"


def _hida_sanjiro_invest(game: GameState, source: L5RCard, amount: int) -> list[Effect]:
    """A +2F Armor Item, made and worn as he arrives."""
    return [CreateToken(SANJIROS_ARMOR, source.owner, source.id, attach_to=source.id)]


register_invest("hida_sanjiro", InvestAbility(amounts=(2,), effect=_hida_sanjiro_invest))


# --- Matsu Gonshiro, Soul of Matsu Shimei ---

GONSHIRO_UNIT_COST = 9


@before_entering_play("matsu_gonshiro_soul_of_matsu_shimei")
def _matsu_gonshiro_soul_of_matsu_shimei_before_entering_play(
    game: GameState, card: L5RCard
) -> list[Effect]:
    """Before Gonshiro enters play, dishonor him. "You must assign Gonshiro to a battlefield
    whenever legal" is a restriction on the seat and is not modeled."""
    return [Dishonor(card.id, Trait(card.id))]


def _matsu_gonshiro_soul_of_matsu_shimei_unit_gold_cost(
    game: GameState, personality: L5RCard
) -> int:
    return sum(card.gold_cost or 0 for card in (personality, *attachments_of(game, personality)))


def _matsu_gonshiro_soul_of_matsu_shimei_targets(game: GameState, source: L5RCard) -> list[str]:
    """The enemy Personalities at this battle whose unit's total Gold Cost is 9 or less."""
    return [
        card_id
        for card_id in opposing_units_in_battle(game, source.owner)
        if _matsu_gonshiro_soul_of_matsu_shimei_unit_gold_cost(
            game, game.table.cards_by_id[card_id]
        )
        <= GONSHIRO_UNIT_COST
    ]


def _matsu_gonshiro_soul_of_matsu_shimei_cost(game: GameState, source: L5RCard) -> list[Effect]:
    """Rehonor Gonshiro: unpayable, so the ability is withheld, while he is honorable."""
    return [Rehonor(source.id)]


def _matsu_gonshiro_soul_of_matsu_shimei_effects(
    game: GameState, source: L5RCard, target: L5RCard
) -> list[Effect]:
    """Destroy the target's unit, and after this battle ends Gonshiro commits seppuku."""
    return [
        Destroy(target.id, source.owner),
        *(DelayedEffect(effect, END_OF_BATTLE) for effect in seppuku(source.id, source.owner)),
    ]


register_ability(
    "matsu_gonshiro_soul_of_matsu_shimei",
    Ability(
        timings=(ActionTiming.BATTLE,),
        cost=_matsu_gonshiro_soul_of_matsu_shimei_cost,
        targets=_matsu_gonshiro_soul_of_matsu_shimei_targets,
        targeting_message="an enemy Personality whose unit's total Gold Cost is 9 or less",
        effects=_matsu_gonshiro_soul_of_matsu_shimei_effects,
    ),
)


# --- Ring of Air ---

# "Play after you resolve two or more Favor actions in one turn."
register_trait_entry(
    "ring_of_air", ActionResolved, resolved_favor_actions(2), ruleset=ruleset.SHATTERED_EMPIRE.name
)


def _ring_of_air_unit(game: GameState, card: L5RCard) -> tuple[L5RCard, ...]:
    personality = card if isinstance(card.printed, PersonalityPrint) else attached_to(game, card)
    return unit_of(game, personality) if personality is not None else (card,)


def _ring_of_air_targets(game: GameState, source: L5RCard) -> list[str]:
    return [
        card.id
        for card in cards_in_play(game, source.owner)
        if card.bowed and isinstance(card.printed, PersonalityPrint | AttachmentPrint)
    ]


def _ring_of_air_effects(game: GameState, source: L5RCard, target: L5RCard) -> list[Effect]:
    """ "Straighten one or two of your target cards in one unit": the first is the target, and the
    second is offered from the rest of that unit."""
    others = tuple(
        card.id for card in _ring_of_air_unit(game, target) if card.bowed and card is not target
    )
    if not others:
        return [Straighten(target.id)]
    return [
        Straighten(target.id),
        Choose(source.owner, others, 0, 1, "ring_of_air_second", source.id),
    ]


@choice_resolver("ring_of_air_second")
def _resolve_ring_of_air_second(
    game: GameState, source_id: str, chosen: tuple[str, ...], seat: PlayerId
) -> list[Effect]:
    return [Straighten(card_id) for card_id in chosen]


register_ring(
    "ring_of_air",
    ability=Ability(
        timings=(ActionTiming.BATTLE, ActionTiming.OPEN),
        cost=bow_cost,
        targets=_ring_of_air_targets,
        effects=_ring_of_air_effects,
        key="air",
        repeatable=True,
    ),
    pitch=RING_PITCH,
    ruleset=ruleset.SHATTERED_EMPIRE.name,
)


# --- Ring of Earth ---

# The pitch is the Interrupt taken from hand, which the Interrupt step plays as a Strategy.


def _ring_of_earth_condition(ctx: TriggerContext) -> bool:
    """ "Play after a battle resolves at a Province if it was not destroyed, you were not the
    Attacker, and any enemy units were ever at its battlefield." """
    event = ctx.event
    if not isinstance(event, BattleResolved) or event.province_destroyed:
        return False
    owner = ctx.card.owner
    return event.attacker is not owner and enemy_units_ever_present(event, owner)


register_trait_entry(
    "ring_of_earth",
    BattleResolved,
    _ring_of_earth_condition,
    ruleset=ruleset.SHATTERED_EMPIRE.name,
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
        ruleset=ruleset.SHATTERED_EMPIRE.name,
    ),
)


# --- Ring of Fire ---

RING_OF_FIRE_PENALTY = -4


def _ring_of_fire_condition(ctx: TriggerContext) -> bool:
    """ "Play after you win a duel during a battle, if your Personality did not enter the duel with
    higher duel stat than the other." The stats it entered on are the ones its declaration
    recorded."""
    game, owner = ctx.game, ctx.card.owner
    if owner not in ctx.event.winners or game.attack is None or game.attack.current is None:
        return False
    declared = next(
        event
        for event in reversed(game.turn_events)
        if isinstance(event, DuelDeclared) and event.source_card_id == ctx.event.source_card_id
    )
    if declared.challenger is owner:
        return declared.challenger_stat <= declared.challenged_stat
    return declared.challenged_stat <= declared.challenger_stat


register_trait_entry(
    "ring_of_fire",
    DuelResolved,
    _ring_of_fire_condition,
    ruleset=ruleset.SHATTERED_EMPIRE.name,
)


def _ring_of_fire_targets(game: GameState, source: L5RCard) -> list[str]:
    enemy = (*personalities_in_play(game), *followers_in_play(game))
    return [card.id for card in enemy if card.owner is not source.owner]


def _ring_of_fire_effects(game: GameState, source: L5RCard, target: L5RCard) -> list[Effect]:
    return [
        GrantModifier(
            source.id, target.id, Stat.FORCE, RING_OF_FIRE_PENALTY, Duration.UNTIL_END_OF_TURN
        )
    ]


register_ring(
    "ring_of_fire",
    ability=Ability(
        timings=(ActionTiming.BATTLE,),
        cost=bow_cost,
        targets=_ring_of_fire_targets,
        effects=_ring_of_fire_effects,
        key="fire",
        repeatable=True,
    ),
    pitch=RING_PITCH,
    ruleset=ruleset.SHATTERED_EMPIRE.name,
)


# --- Ring of the Void ---

# The draw's follow-up is the resolver the Onyx printing registers under "ring_of_the_void": the
# two texts differ only in the designator.


def _ring_of_the_void_condition(game: GameState, source: L5RCard) -> bool:
    """ "Play if you ever have the same number of Fate cards in play as in your hand, not counting
    this Ring." """
    hand = cards_in_hand(game, source.owner)
    in_hand = sum(1 for card in hand if card is not source and isinstance(card.printed, FatePrint))
    return len(fate_cards_in_play(game, source.owner)) == in_hand


register_condition_entry(
    "ring_of_the_void", _ring_of_the_void_condition, ruleset=ruleset.SHATTERED_EMPIRE.name
)


def _ring_of_the_void_effects(game: GameState, source: L5RCard, target: L5RCard) -> list[Effect]:
    return [DrawCard(source.owner), Evaluate("ring_of_the_void", source.id, source.owner)]


register_ring(
    "ring_of_the_void",
    ability=Ability(
        timings=(ActionTiming.OPEN,),
        cost=bow_cost,
        targets=itself,
        effects=_ring_of_the_void_effects,
        hits_every_target=True,
        key="void",
    ),
    pitch=RING_PITCH,
    ruleset=ruleset.SHATTERED_EMPIRE.name,
)


# --- Ring of Water ---


def _ring_of_water_condition(ctx: TriggerContext) -> bool:
    """ "Play after a battle resolves where you control a Terrain and destroyed a Province." The
    Attacker is the one who destroys a Province (CR, Battle Resolution)."""
    event = ctx.event
    if not isinstance(event, BattleResolved) or not event.province_destroyed:
        return False
    owner = ctx.card.owner
    return event.attacker is owner and controls_terrain_at(
        ctx.game, owner, battlefield=event.battlefield
    )


register_trait_entry(
    "ring_of_water",
    BattleResolved,
    _ring_of_water_condition,
    ruleset=ruleset.SHATTERED_EMPIRE.name,
)


def _ring_of_water_targets(game: GameState, source: L5RCard) -> list[str]:
    """Your Personalities at the current battlefield, to move home, and, while an enemy unit is
    there to oppose them, your Personalities anywhere else, to move to it."""
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
        repeatable=True,
    ),
    pitch=RING_PITCH,
    ruleset=ruleset.SHATTERED_EMPIRE.name,
)


# --- Shinjo Mayuko, Soul of Shinjo Wei ---

MAYUKO_FIRST_MELEE = 4
MAYUKO_SECOND_MELEE = 3


def _shinjo_mayuko_soul_of_shinjo_wei_cost(game: GameState, source: L5RCard) -> list[Effect]:
    """Dishonor Mayuko: unpayable, so the ability is withheld, once she is dishonorable."""
    return [Dishonor(source.id, source.owner)]


def _shinjo_mayuko_soul_of_shinjo_wei_effects(
    game: GameState, source: L5RCard, target: L5RCard
) -> list[Effect]:
    """A Melee 4, then a Melee 3 with its own target. The second is chosen once the first has
    resolved, and the first target is left out of it: a survivor of Melee 4 is beyond Melee 3."""
    others = tuple(card_id for card_id in attack_targets(game, source) if card_id != target.id)
    second = (
        [Choose(source.owner, others, 1, 1, "shinjo_mayuko_second_melee", source.id)]
        if others
        else []
    )
    return [MeleeAttack(MAYUKO_FIRST_MELEE, target.id, source.owner), *second]


@choice_resolver("shinjo_mayuko_second_melee", prompt=f"Melee {MAYUKO_SECOND_MELEE} Attack")
def _resolve_shinjo_mayuko_second_melee(
    game: GameState, source_id: str, chosen: tuple[str, ...], seat: PlayerId
) -> list[Effect]:
    return [MeleeAttack(MAYUKO_SECOND_MELEE, chosen[0], seat)] if chosen else []


register_ability(
    "shinjo_mayuko_soul_of_shinjo_wei",
    Ability(
        timings=(ActionTiming.BATTLE,),
        cost=_shinjo_mayuko_soul_of_shinjo_wei_cost,
        targets=attack_targets,
        targeting_message=ATTACK_TARGET,
        effects=_shinjo_mayuko_soul_of_shinjo_wei_effects,
    ),
)


# --- The Enlightened Path of the Dragon ---

# The key a target Ring's ability or Interrupt is copied under, for the additional action taken
# from it "ignoring bow costs".
ENLIGHTENED_PATH_COPY = "enlightened_path"


def _the_enlightened_path_of_the_dragon_rings(game: GameState, source: L5RCard) -> list[L5RCard]:
    """Your Rings in play, unbowed since a bowed card's abilities cannot be used, and those in your
    Fate discard pile."""
    asking = Asking.action(source)
    in_play = [ring for ring in rings_in_play(game, source.owner, asking) if not ring.bowed]
    pile = game.table.zones[ZoneKey(source.owner, ZoneRole.FATE_DISCARD)].cards
    return in_play + [card for card in pile if counts_as(game, card, RingPrint, asking)]


def _the_enlightened_path_of_the_dragon_printed(
    ring: L5RCard, taken_as: ActionTiming
) -> Ability | None:
    """The ability ``ring`` prints in play under ``taken_as``, leaving out its cast from hand. None
    for the Interrupt, which no Ring's ability is taken as."""
    return next(
        (
            ability
            for ability in printed_abilities(ring)
            if CardLocation.BATTLEFIELD in ability.located_at and taken_as in ability.timings
        ),
        None,
    )


def _the_enlightened_path_of_the_dragon_taken_as(game: GameState, source: L5RCard) -> ActionTiming:
    """Battle during a battle, where an Open action cannot be taken, and Open otherwise."""
    permitted = permitted_timings_in(game, action_round(game), source.owner)
    return ActionTiming.BATTLE if ActionTiming.BATTLE in permitted else ActionTiming.OPEN


def _the_enlightened_path_of_the_dragon_follow_up(
    game: GameState, source: L5RCard, ring: L5RCard, taken_as: ActionTiming, follow_up: Action
) -> list[Effect]:
    """Grant ``ring`` its copy for ``taken_as`` until the additional action is spent, open that
    action to ``follow_up`` alone, and reshuffle a Ring taken from the discard pile once it is."""
    seat = source.owner
    effects: list[Effect] = [
        GrantSeatAbility(source.id, seat, (ring.id, taken_as.name), ADDITIONAL_ACTION_SPENT),
        AdditionalAction(seat, frozenset({follow_up})),
    ]
    pile = game.table.zones[ZoneKey(seat, ZoneRole.FATE_DISCARD)].cards
    if any(card is ring for card in pile):
        fate = DeckKey(seat, Side.FATE)
        effects += [
            DelayedEffect(MoveToDeck(ring.id, fate, from_top=0), ADDITIONAL_ACTION_SPENT),
            DelayedEffect(ShuffleDeck(fate), ADDITIONAL_ACTION_SPENT),
        ]
    return effects


def _the_enlightened_path_of_the_dragon_cost(game: GameState, source: L5RCard) -> list[Effect]:
    """Taken as a Battle or Open action, the one ability spends its use as an Interrupt too."""
    return [SpendOncePerTurn(source.id, INTERRUPT_TAG)]


def _the_enlightened_path_of_the_dragon_targets(game: GameState, source: L5RCard) -> list[str]:
    taken_as = _the_enlightened_path_of_the_dragon_taken_as(game, source)
    return [
        ring.id
        for ring in _the_enlightened_path_of_the_dragon_rings(game, source)
        if _the_enlightened_path_of_the_dragon_printed(ring, taken_as) is not None
    ]


def _the_enlightened_path_of_the_dragon_effects(
    game: GameState, source: L5RCard, target: L5RCard
) -> list[Effect]:
    taken_as = _the_enlightened_path_of_the_dragon_taken_as(game, source)
    follow_up = ActivateAbility(target.id, ENLIGHTENED_PATH_COPY)
    return _the_enlightened_path_of_the_dragon_follow_up(game, source, target, taken_as, follow_up)


ENLIGHTENED_PATH_ABILITY = Ability(
    timings=(ActionTiming.BATTLE,),
    cost=_the_enlightened_path_of_the_dragon_cost,
    targets=_the_enlightened_path_of_the_dragon_targets,
    effects=_the_enlightened_path_of_the_dragon_effects,
    tireless=True,
)

register_ability("the_enlightened_path_of_the_dragon", ENLIGHTENED_PATH_ABILITY)


@granted_ability("the_enlightened_path_of_the_dragon")
def _the_enlightened_path_of_the_dragon_granted_ability(
    game: GameState, card: L5RCard, context: tuple[str, ...]
) -> Ability | None:
    ring_id, taken_as = context
    if card.id != ring_id:
        return None
    printed = _the_enlightened_path_of_the_dragon_printed(card, ActionTiming[taken_as])
    if printed is None:
        return None
    copied = _the_enlightened_path_of_the_dragon_copied(printed)
    return replace(copied, limit_key=printed.key or "")


def _the_enlightened_path_of_the_dragon_copied[T: Ability | Interrupt[Effect]](printed: T) -> T:
    """``printed`` taken from play or the discard pile, ignoring bow costs."""
    return replace(
        printed,
        key=ENLIGHTENED_PATH_COPY,
        cost=ignoring_bow_costs(printed.cost),
        located_at=(CardLocation.BATTLEFIELD, CardLocation.DISCARD),
    )


@granted_interrupt("the_enlightened_path_of_the_dragon")
def _the_enlightened_path_of_the_dragon_granted_interrupt(
    game: GameState, card: L5RCard, context: tuple[str, ...]
) -> Interrupt[Effect] | None:
    ring_id, taken_as = context
    if card.id != ring_id or taken_as != ActionTiming.INTERRUPT.name:
        return None
    printed = printed_interrupt(card)
    return None if printed is None else _the_enlightened_path_of_the_dragon_copied(printed)


def _the_enlightened_path_of_the_dragon_interrupt_cost(
    game: GameState, source: L5RCard
) -> list[Effect]:
    """Taken as an Interrupt, the one ability spends its use as a Battle or Open action too."""
    return [SpendOncePerTurn(source.id, once_tag(ENLIGHTENED_PATH_ABILITY))]


def _the_enlightened_path_of_the_dragon_interrupt_targets(
    game: GameState, source: L5RCard, effect: Effect
) -> tuple[str, ...]:
    """Your Rings whose Interrupt could be taken against ``effect``."""
    return tuple(
        ring.id
        for ring in _the_enlightened_path_of_the_dragon_rings(game, source)
        if (printed := printed_interrupt(ring)) is not None
        and answered_by(game, ring, _the_enlightened_path_of_the_dragon_copied(printed), (effect,))
    )


def _the_enlightened_path_of_the_dragon_interrupt(
    game: GameState, source: L5RCard, effect: Effect, target: L5RCard
) -> Interruption:
    follow_up = PlayInterrupt(target.id, ENLIGHTENED_PATH_COPY)
    effects = _the_enlightened_path_of_the_dragon_follow_up(
        game, source, target, ActionTiming.INTERRUPT, follow_up
    )
    return Interruption(effect, tuple(effects))


ENLIGHTENED_PATH_INTERRUPT = Interrupt(
    answers=Effect,
    interrupt=_the_enlightened_path_of_the_dragon_interrupt,
    targets=_the_enlightened_path_of_the_dragon_interrupt_targets,
    located_at=(CardLocation.BATTLEFIELD,),
    cost=_the_enlightened_path_of_the_dragon_interrupt_cost,
    tireless=True,
)

register_interrupt("the_enlightened_path_of_the_dragon", ENLIGHTENED_PATH_INTERRUPT)


# --- The Enlightened Path of the Dragon (back) ---

register_ability(
    "the_enlightened_path_of_the_dragon__back",
    replace(ENLIGHTENED_PATH_ABILITY, timings=(ActionTiming.BATTLE, ActionTiming.OPEN)),
)
granted_ability("the_enlightened_path_of_the_dragon__back")(
    _the_enlightened_path_of_the_dragon_granted_ability
)
register_interrupt("the_enlightened_path_of_the_dragon__back", ENLIGHTENED_PATH_INTERRUPT)
granted_interrupt("the_enlightened_path_of_the_dragon__back")(
    _the_enlightened_path_of_the_dragon_granted_interrupt
)


# --- Togashi Toyonobu, Soul of Togashi Binya ---


def _togashi_toyonobu_soul_of_togashi_binya_targets(game: GameState, source: L5RCard) -> list[str]:
    return [card.id for card in personalities_in_play(game)]


def _togashi_toyonobu_soul_of_togashi_binya_effects(
    game: GameState, source: L5RCard, target: L5RCard
) -> list[Effect]:
    """Set the target's Force to Toyonobu's with the bonus or penalty that reaches it, measured from
    the target's Force before its minimum and maximum (CR, Setting Stats to Values). Equal Force
    needs none, and a +0 would not count as a bonus anyway."""
    change = effective_force(game, source) - unbounded_stat(game, target, Stat.FORCE)
    if change == 0:
        return []
    return [GrantModifier(source.id, target.id, Stat.FORCE, change, Duration.UNTIL_END_OF_TURN)]


register_ability(
    "togashi_toyonobu_soul_of_togashi_binya",
    Ability(
        timings=(ActionTiming.BATTLE,),
        cost=no_cost,
        targets=_togashi_toyonobu_soul_of_togashi_binya_targets,
        targeting_message="a Personality",
        effects=_togashi_toyonobu_soul_of_togashi_binya_effects,
    ),
)


# Each prints the same entry. "Open: If you are an X Clan player, put this Edict into play."
# What they grant while in play has a handler only where a block below says so.


# --- Way of the Akasha ---

register_entry("way_of_the_akasha", clears=keywords.EDICT, condition=plays_clan(ruleset.AKASHA))


# --- Way of the Crab (Experienced) ---

register_entry(
    "way_of_the_crab_experienced", clears=keywords.EDICT, condition=plays_clan(ruleset.CRAB)
)

# "Your Personalities have Siege while opposed" has no handler: Siege has no rules behind it yet.
WAY_OF_THE_CRAB_TAG = "way_of_the_crab_straighten"


@focus_effect("way_of_the_crab_experienced")
def _way_of_the_crab_experienced_focus_effect(game: GameState, card: L5RCard) -> list[Effect]:
    """ "As a Focus Effect, both Personalities use their Force as their duel stat."

    The CR names the duel stat per Personality rather than per duel, so each duelist is told to
    compare it (CR, Duel Stat).
    """
    duel = game.duel
    if duel is None:
        return []
    return [
        GrantDuelStat(card.id, duel.duelist_of(seat), Stat.FORCE, DUEL_CONSEQUENCES)
        for seat in (duel.challenger, duel.challenged)
    ]


@on(Bowed, "way_of_the_crab_experienced")
def _way_of_the_crab_experienced_bowed(ctx: TriggerContext) -> list[Effect]:
    """After your Fortification bows, once per turn, straighten it. Negate its bowing (this
    turn)."""
    bowed = ctx.game.table.cards_by_id[ctx.event.card_id]
    if bowed.owner is not ctx.card.owner or not has_keyword(
        ctx.game, bowed, keywords.FORTIFICATION
    ):
        return []
    if used_this_turn(ctx.game, ctx.card, WAY_OF_THE_CRAB_TAG):
        return []
    negation = Negation(ctx.card.id, END_OF_TURN, effect_kind=Bow, subject_id=bowed.id)
    return [
        SpendOncePerTurn(ctx.card.id, WAY_OF_THE_CRAB_TAG),
        Straighten(bowed.id),
        GrantNegation(negation),
    ]


# --- Way of the Crane (Experienced) ---

WAY_OF_THE_CRANE_HONOR = 1
WAY_OF_THE_CRANE_STRENGTH = 1


@focus_effect("way_of_the_crane_experienced")
def _way_of_the_crane_experienced_focus_effect(game: GameState, card: L5RCard) -> list[Effect]:
    """ "As a Focus Effect, after this duel ends, if you won it, gain 1 Honor and give your
    provinces +1PS." """
    evaluation = Evaluate("way_of_the_crane_experienced_won", card.id, card.owner)
    return [DelayedEffect(evaluation, DUEL_CONSEQUENCES)]


@choice_resolver("way_of_the_crane_experienced_won")
def _resolve_way_of_the_crane_experienced_won(
    game: GameState, source_id: str, chosen: tuple[str, ...], seat: PlayerId
) -> list[Effect]:
    """Nothing for a duel the seat did not win, which includes one both Personalities lost. The
    Province bonus has no printed duration, so it runs to the end of the turn (CR, Ongoing)."""
    outcome = decided_outcome(game)
    if outcome is None or seat not in outcome.winners:
        return []
    return [
        GainHonor(seat, WAY_OF_THE_CRANE_HONOR, source_id=source_id),
        *(
            GrantProvinceStrength(
                source_id, province, WAY_OF_THE_CRANE_STRENGTH, Duration.UNTIL_END_OF_TURN
            )
            for province, _ in province_zones(game, seat)
        ),
    ]


register_entry(
    "way_of_the_crane_experienced",
    clears=keywords.EDICT,
    condition=plays_clan(ruleset.CRANE),
    key="enter",
)


@lobby_bonus_grant("way_of_the_crane_experienced")
def _way_of_the_crane_experienced_lobby_bonus(game: GameState, card: L5RCard) -> int:
    """ "You have a +1 Lobby bonus for each of your Provinces." """
    return sum(1 for _ in province_zones(game, card.owner))


def _way_of_the_crane_experienced_targets(game: GameState, source: L5RCard) -> list[str]:
    """Itself, once the action just resolved was its controller's and discarded the Favor.

    Whose Favor it was does not matter: the text names the action, so an action of yours that makes
    the holder discard it counts, and a discard of your own Favor that was not your action does
    not.
    """
    if game.action_seat is not source.owner:
        return []
    return [source.id] if action_did(game, FavorDiscarded) else []


def _way_of_the_crane_experienced_effects(
    game: GameState, source: L5RCard, target: L5RCard
) -> list[Effect]:
    """The seat picks the discard from its hand after the draw, so the drawn card is among the
    choices."""
    seat = source.owner
    return [DrawCard(seat), DiscardFromHand(seat, 1, Trait(source.id), seat)]


# Once per turn under the ruleset's rationing of abilities, which the printed "once per turn"
# restates.
register_ability(
    "way_of_the_crane_experienced",
    Ability(
        timings=(ActionTiming.RESPONSE,),
        label="After your action discards :favor:, once per turn you may draw, then discard a card.",
        cost=no_cost,
        targets=_way_of_the_crane_experienced_targets,
        effects=_way_of_the_crane_experienced_effects,
        hits_every_target=True,
        tireless=True,
        trait=True,
        key="draw_and_discard",
    ),
)


# --- Way of the Dragon (Experienced) ---

register_entry(
    "way_of_the_dragon_experienced", clears=keywords.EDICT, condition=plays_clan(ruleset.DRAGON)
)

# "This Strategy counts as a Ring for actions."
register_counts_as(
    "way_of_the_dragon_experienced", CountsAs(RingPrint, frozenset({AskedBy.ACTION}), anywhere)
)

WAY_OF_THE_DRAGON_DISCARDS = (ZoneRole.FATE_DISCARD, ZoneRole.DYNASTY_DISCARD)


@lobby_bonus_grant("way_of_the_dragon_experienced")
def _way_of_the_dragon_experienced_lobby_bonus(game: GameState, card: L5RCard) -> int:
    """ "You have a +1 Lobby bonus for each Ring in play or in a discard pile." The bonus is a
    trait, so a card counting as a Ring only for actions, this one included, is not counted."""
    asking = Asking.trait(card)
    discarded = (
        held
        for seat in game.table.seats
        for role in WAY_OF_THE_DRAGON_DISCARDS
        for held in game.table.zones[ZoneKey(seat, role)].cards
    )
    return sum(
        counts_as(game, held, RingPrint, asking)
        for held in (*game.table.battlefield.cards, *discarded)
    )


@on(TurnBoundary, "way_of_the_dragon_experienced", boundary=Boundary.BEGINNING)
def _way_of_the_dragon_experienced_turn_boundary(ctx: TriggerContext) -> list[Effect]:
    """After your turn begins, look at the top card of your Fate deck. You may put it on the bottom
    of the deck."""
    seat = ctx.card.owner
    if seat is not ctx.event.seat:
        return []
    fate = DeckKey(seat, Side.FATE)
    seen = top_of_deck(ctx.game, fate, 1)
    if not seen:
        return []
    return [
        LookAtTop(seat, fate, 1),
        Choose(seat, seen, 0, 1, "way_of_the_dragon_experienced_bottom", ctx.card.id),
    ]


@choice_resolver(
    "way_of_the_dragon_experienced_bottom", prompt="You may put it on the bottom of the deck"
)
def _resolve_way_of_the_dragon_experienced_bottom(
    game: GameState, source_id: str, chosen: tuple[str, ...], seat: PlayerId
) -> list[Effect]:
    fate = DeckKey(seat, Side.FATE)
    return [*(MoveToDeck(card_id, fate, from_bottom=0) for card_id in chosen), EndLook()]


# --- Way of the Lion (Experienced) ---

register_entry(
    "way_of_the_lion_experienced", clears=keywords.EDICT, condition=plays_clan(ruleset.LION)
)


# --- Way of the Mantis (Experienced) ---

register_entry(
    "way_of_the_mantis_experienced", clears=keywords.EDICT, condition=plays_clan(ruleset.MANTIS)
)


# --- Way of the Phoenix (Experienced) ---

register_entry(
    "way_of_the_phoenix_experienced", clears=keywords.EDICT, condition=plays_clan(ruleset.PHOENIX)
)


# --- Way of the Scorpion (Experienced) ---

register_entry(
    "way_of_the_scorpion_experienced", clears=keywords.EDICT, condition=plays_clan(ruleset.SCORPION)
)


@focus_effect("way_of_the_scorpion_experienced")
def _way_of_the_scorpion_experienced_focus_effect(game: GameState, card: L5RCard) -> list[Effect]:
    """ "As a Focus Effect, after this duel ends, if you were not the challenger, dishonor the
    winner." """
    evaluation = Evaluate("way_of_the_scorpion_experienced_winner", card.id, card.owner)
    return [DelayedEffect(evaluation, DUEL_CONSEQUENCES)]


@choice_resolver("way_of_the_scorpion_experienced_winner")
def _resolve_way_of_the_scorpion_experienced_winner(
    game: GameState, source_id: str, chosen: tuple[str, ...], seat: PlayerId
) -> list[Effect]:
    """The challenger is the seat whose card created the duel, so a card focused by that seat does
    nothing. A duel both Personalities lost has no winner to dishonor."""
    duel = decided_duel(game)
    outcome = decided_outcome(game)
    if duel is None or outcome is None or duel.challenger is seat:
        return []
    return [Dishonor(duel.duelist_of(winner), seat) for winner in outcome.winners]


# --- Way of the Spider (Experienced) ---

register_entry(
    "way_of_the_spider_experienced", clears=keywords.EDICT, condition=plays_clan(ruleset.SPIDER)
)


# --- Way of the Unicorn (Experienced) ---

register_entry(
    "way_of_the_unicorn_experienced", clears=keywords.EDICT, condition=plays_clan(ruleset.UNICORN)
)


# --- Weapon Artist ---

FINE_SWORD = "weapon_item_sword_plus2f_plus1c"


def _weapon_artist_targets(game: GameState, source: L5RCard) -> list[str]:
    """The Personalities with room for the sword. It is a One-Handed Weapon, so a Personality
    already carrying a Weapon has nowhere to put it."""
    sword = game.table.creatable_tokens[FINE_SWORD]
    return [target.id for target in creation_targets(game, source.owner, sword)]


def _weapon_artist_effects(game: GameState, source: L5RCard, target: L5RCard) -> list[Effect]:
    return [CreateToken(FINE_SWORD, source.owner, source.id, attach_to=target.id)]


register_ability(
    "weapon_artist",
    Ability(
        timings=(ActionTiming.OPEN,),
        cost=bow_cost,
        targets=_weapon_artist_targets,
        targeting_message="your Personality",
        effects=_weapon_artist_effects,
    ),
)
