from dataclasses import replace

from yasuki_core.engine.players import PlayerId, Trait
from yasuki_core.engine.rules.board.counts_as import Asking, counts_as
from yasuki_core.engine.rules.board.seats import cards_in_play, cards_named, has_compassion
from yasuki_core.engine.rules.abilities.costs import bow_cost, no_cost
from yasuki_core.engine.rules.abilities.idioms import register_event_entry
from yasuki_core.engine.rules.abilities.model import (
    Ability,
    CardLocation,
    Interrupt,
    Interruption,
    TargetGroup,
    itself,
)
from yasuki_core.engine.rules.abilities.registry import (
    abilities_for,
    register_ability,
    register_interrupt,
)
from yasuki_core.engine.rules.vocabulary.actions import (
    ActionTiming,
    ActivateAbility,
    BattleDesignator,
)
from yasuki_core.engine.rules.gold.producers import reachable_gold
from yasuki_core.engine.rules.gold.self_grants import register_self_grant, SELF_GRANT
from yasuki_core.engine.rules.effects import (
    AdditionalAction,
    AdjustCounter,
    AskOption,
    AttackEffect,
    Bow,
    Choose,
    CreateToken,
    DeclareOptions,
    Destroy,
    Discard,
    Effect,
    Evaluate,
    Fear,
    GainHonor,
    GrantModifier,
    MeleeAttack,
    Move,
    MoveToHand,
    Negated,
    PayGold,
    PlaceInProvince,
    RangedAttack,
    Simultaneously,
    Straighten,
    To,
    seppuku,
)
from yasuki_core.engine.rules.rulebook.equip import creation_targets, equips_from_discard
from yasuki_core.engine.rules.vocabulary.game_events import (
    Destroyed,
    Dishonored,
    EnteredPlay,
    ProducedGold,
    ProducingGold,
)
from yasuki_core.engine.rules.board.queries import (
    attack_targets,
    has_keyword,
    opposed_units_in_battle,
    opposing_units_in_battle,
    owned_holdings,
    owned_personalities,
    personalities_in_play,
    province_key_holding,
)
from yasuki_core.engine.rules.gold.cost import effective_gold_cost
from yasuki_core.engine.rules.stats.card_values import effective_chi, effective_force
from yasuki_core.engine.rules.stats.keyword_grants import effective_keywords
from yasuki_core.engine.rules.units.composition import followers_of
from yasuki_core.engine.rules.vocabulary.decisions import (
    PickedTargets,
    PickLimit,
    TotalAtMost,
)
from yasuki_core.engine.rules.vocabulary.modifiers import Duration, Stat
from yasuki_core.engine.rules.gold.payment import offer_self_grant
from yasuki_core.engine.rules.state import GameState, claim_once_per_turn, used_this_turn
from yasuki_core.engine.rules.triggers import TriggerContext, choice_resolver, on
from yasuki_core.engine.rules.vocabulary import keywords
from yasuki_core.engine.rules.units.membership import unit_of
from yasuki_core.engine.table import DeckKey, Location, ZoneKey, ZoneRole, location_of
from yasuki_core.game_pieces.cards import L5RCard
from yasuki_core.game_pieces.constants import Side
from yasuki_core.game_pieces.counters import MINUS_1F
from yasuki_core.game_pieces.prints import (
    AttachmentPrint,
    HoldingPrint,
    PersonalityPrint,
    RingPrint,
)


# --- Desperate Melee ---

DESPERATE_MELEE_MOST_FOLLOWERS = 2
DESPERATE_MELEE_MOST_FOR_A_BERSERKER = 5


def _desperate_melee_targets(game: GameState, source: L5RCard, picked: PickedTargets) -> list[str]:
    """ "Target your Personality": the one whose Gold Cost bounds what the melee reaches."""
    return [card.id for card in owned_personalities(game, source.owner)]


def _desperate_melee_followers(
    game: GameState, source: L5RCard, picked: PickedTargets
) -> list[str]:
    """ "Target and destroy ... enemy Followers": the Followers carried by the units facing you."""
    by_id = game.table.cards_by_id
    return [
        follower.id
        for enemy_id in opposing_units_in_battle(game, source.owner)
        for follower in followers_of(game, by_id[enemy_id])
    ]


def _desperate_melee_personality(game: GameState, picked: PickedTargets) -> L5RCard:
    """The Personality the first phrase targeted, whose Berserker keyword and Gold Cost the second
    phrase is read against."""
    return game.table.cards_by_id[picked[0][0]]


def _desperate_melee_count(
    game: GameState, source: L5RCard, picked: PickedTargets, offered: tuple[str, ...]
) -> tuple[int, int]:
    """ "one to two enemy Followers, or one to five enemy Followers if your Personality is a
    Berserker"."""
    personality = _desperate_melee_personality(game, picked)
    berserker = keywords.BERSERKER in effective_keywords(game, personality)
    return 1, DESPERATE_MELEE_MOST_FOR_A_BERSERKER if berserker else DESPERATE_MELEE_MOST_FOLLOWERS


def _desperate_melee_limits(
    game: GameState, source: L5RCard, picked: PickedTargets
) -> tuple[PickLimit, ...]:
    """ "with total Gold Cost less than your Personality's"."""
    bound = effective_gold_cost(game, _desperate_melee_personality(game, picked)) - 1
    weights = tuple(
        (follower_id, effective_gold_cost(game, game.table.cards_by_id[follower_id]))
        for follower_id in _desperate_melee_followers(game, source, picked)
    )
    return (TotalAtMost(weights, bound, unit="GC"),)


def _desperate_melee_effects(
    game: GameState, source: L5RCard, groups: tuple[tuple[L5RCard, ...], ...]
) -> list[Effect]:
    """The enemy Followers die together, and then your Personality's own, which the card destroys
    whether or not the melee reached anything."""
    (personality,), followers = groups
    seat = source.owner
    dying = (followers, followers_of(game, personality))
    return [
        Simultaneously(tuple(Destroy(follower.id, seat) for follower in dead))
        for dead in dying
        if dead
    ]


register_ability(
    "desperate_melee",
    Ability(
        timings=(ActionTiming.BATTLE,),
        cost=no_cost,
        target_groups=(
            TargetGroup(
                candidates=_desperate_melee_targets,
                targeting_message="your Personality",
            ),
            TargetGroup(
                candidates=_desperate_melee_followers,
                count=_desperate_melee_count,
                limits=_desperate_melee_limits,
                targeting_message="the enemy Followers",
            ),
        ),
        effects_for_groups=_desperate_melee_effects,
        located_at=(CardLocation.HAND,),
    ),
)


# --- Dull Tanto ---


def _dull_tanto_targets(game: GameState, source: L5RCard) -> list[str]:
    """Every Personality on the board. The card says "a target Personality" and narrows it no
    further, so the controller's own are legal targets."""
    return [card.id for card in personalities_in_play(game)]


def _dull_tanto_effects(game: GameState, source: L5RCard, target: L5RCard) -> list[Effect]:
    """Two -1F tokens on the target, then destroy this Item. Two separate tokens rather than one
    worth -2F, so an effect that removes a single token removes only 1 Force."""
    return [
        AdjustCounter(target.id, MINUS_1F, 2),
        Destroy(source.id, source.owner),
    ]


register_ability(
    "dull_tanto",
    Ability(
        timings=(ActionTiming.OPEN,),
        cost=no_cost,
        targets=_dull_tanto_targets,
        targeting_message="a Personality",
        effects=_dull_tanto_effects,
    ),
)


# --- "Is That All?" ---


def _is_that_all_fear_targets(game: GameState, source: L5RCard) -> list[str]:
    return [card.id for card in owned_personalities(game, source.owner) if card.bowed]


def _is_that_all_fear_effects(game: GameState, source: L5RCard, target: L5RCard) -> list[Effect]:
    return [Evaluate("is_that_all_fear_target", source.id, source.owner, (target.id,))]


@choice_resolver("is_that_all_fear_target")
def _resolve_is_that_all_fear_target(
    game: GameState, source_id: str, chosen: tuple[str, ...], seat: PlayerId
) -> list[Effect]:
    """The Fear targets the way any Fear does, among what stands at the battle as it resolves, and
    is not raised when nothing there can be targeted. ``chosen`` is your bowed Personality."""
    feared = attack_targets(game, game.table.cards_by_id[source_id])
    if not feared:
        return []
    return [Choose(seat, tuple(feared), 1, 1, "is_that_all_fear", source_id, chosen)]


@choice_resolver(
    "is_that_all_fear", prompt="Fear equal to your Personality's Force: choose its target"
)
def _resolve_is_that_all_fear(
    game: GameState,
    source_id: str,
    chosen: tuple[str, ...],
    seat: PlayerId,
    resolver_context: tuple[str, ...] = (),
) -> list[Effect]:
    """ "If this bowed an enemy Personality, straighten your Personality": the straightening
    follows the Fear's bow only if that bow happened."""
    (yours_id,) = resolver_context
    feared = game.table.cards_by_id[chosen[0]]
    strength = effective_force(game, game.table.cards_by_id[yours_id])
    if not isinstance(feared.printed, PersonalityPrint):
        return [Fear(strength, feared.id, seat)]
    outcome = (To(Bow(feared.id), (Straighten(yours_id),)),)
    return [Fear(strength, feared.id, seat, outcome=outcome)]


def _is_that_all_destroy_targets(game: GameState, source: L5RCard) -> list[str]:
    """The attachment the action was from, while it is in play with 0 Gold Cost."""
    match game.action:
        case ActivateAbility(card_id=card_id):
            card = game.table.cards_by_id.get(card_id)
        case _:
            return []
    if card is None or card not in game.table.battlefield.cards:
        return []
    if not isinstance(card.printed, AttachmentPrint) or effective_gold_cost(game, card) != 0:
        return []
    return [card.id]


def _is_that_all_destroy_effects(game: GameState, source: L5RCard, target: L5RCard) -> list[Effect]:
    return [Destroy(target.id, source.owner)]


register_ability(
    "is_that_all",
    Ability(
        timings=(ActionTiming.BATTLE,),
        cost=no_cost,
        targets=_is_that_all_fear_targets,
        targeting_message="your bowed Personality",
        effects=_is_that_all_fear_effects,
        located_at=(CardLocation.HAND,),
        key="fear",
    ),
)
register_ability(
    "is_that_all",
    Ability(
        timings=(ActionTiming.RESPONSE,),
        cost=no_cost,
        targets=_is_that_all_destroy_targets,
        effects=_is_that_all_destroy_effects,
        hits_every_target=True,
        located_at=(CardLocation.HAND,),
        key="destroy",
        printed_index=1,
    ),
)


# --- Kakita Harudei, Drunkard ---

HARUDEI_USES_WITH_COMPASSION = 2


def _kakita_harudei_drunkard_targets(game: GameState, source: L5RCard) -> list[str]:
    """Enemy Personalities opposing Harudei with lower Chi than his."""
    own_chi = effective_chi(game, source)
    return [
        card_id
        for card_id in opposing_units_in_battle(game, source.owner)
        if effective_chi(game, game.table.cards_by_id[card_id]) < own_chi
    ]


def _kakita_harudei_drunkard_effects(
    game: GameState, source: L5RCard, target: L5RCard
) -> list[Effect]:
    return [Bow(target.id)]


def _kakita_harudei_drunkard_uses_per_turn(game: GameState, source: L5RCard) -> int:
    """Compassion: You may use Harudei's printed ability an additional time per turn."""
    return HARUDEI_USES_WITH_COMPASSION if has_compassion(game, source.owner, source) else 1


register_ability(
    "kakita_harudei_drunkard",
    Ability(
        timings=(ActionTiming.BATTLE,),
        keywords=frozenset({keywords.IAIJUTSU}),
        cost=no_cost,
        targets=_kakita_harudei_drunkard_targets,
        targeting_message="an enemy Personality with lower Chi",
        effects=_kakita_harudei_drunkard_effects,
        uses_per_turn=_kakita_harudei_drunkard_uses_per_turn,
    ),
)


# --- Kitsune Rumiko ---

RUMIKO_HONOR = 1
RUMIKO_HONOR_WITH_BEIKO = 2
BEIKO_SENSEI = "beiko_sensei"


@on(Dishonored, "kitsune_rumiko")
def _kitsune_rumiko_dishonored(ctx: TriggerContext) -> list[Effect]:
    """If Rumiko is ever dishonorable, she commits seppuku. "If ever" is timed after the
    dishonoring (CR, "If" Triggers), and the seppuku is her own trait's doing."""
    if ctx.event.card_id != ctx.card.id:
        return []
    return seppuku(ctx.card.id, Trait(ctx.card.id))


def _kitsune_rumiko_cost(game: GameState, source: L5RCard) -> list[Effect]:
    """Bow Rumiko, a cost Compassion has her ignore."""
    return [] if has_compassion(game, source.owner, source) else bow_cost(game, source)


def _kitsune_rumiko_effects(game: GameState, source: L5RCard, target: L5RCard) -> list[Effect]:
    """Gain 1 Honor, or 2 Honor if your Sensei is Beiko Sensei."""
    amount = (
        RUMIKO_HONOR_WITH_BEIKO if cards_named(game, source.owner, BEIKO_SENSEI) else RUMIKO_HONOR
    )
    return [GainHonor(source.owner, amount, personalities=(source.id,))]


register_ability(
    "kitsune_rumiko",
    Ability(
        timings=(ActionTiming.LIMITED,),
        cost=_kitsune_rumiko_cost,
        targets=itself,
        effects=_kitsune_rumiko_effects,
        hits_every_target=True,
    ),
)


# --- Outlying Farms ---


OUTLYING_FARMS_GRANT = 2

register_self_grant("outlying_farms", OUTLYING_FARMS_GRANT)


@on(ProducingGold, "outlying_farms")
def _outlying_farms_producing_gold(ctx: TriggerContext) -> list[Effect]:
    """ "Before this Holding bows to produce Gold, you may give it +2GP." Offered in the window, so
    the grant is inside the yield the bow reads."""
    return offer_self_grant(
        ctx,
        f"Give Outlying Farms +{OUTLYING_FARMS_GRANT}GP? It is destroyed after it bows.",
        "outlying_farms_grant",
    )


@choice_resolver("outlying_farms_grant")
def _resolve_outlying_farms_grant(
    game: GameState, source_id: str | None, chosen: tuple[str, ...], seat: PlayerId
) -> list[Effect]:
    if not chosen:
        return []
    card = game.table.cards_by_id[chosen[0]]
    claim_once_per_turn(game, card, SELF_GRANT)
    return [
        GrantModifier(
            card.id,
            card.id,
            Stat.GOLD_PRODUCTION,
            OUTLYING_FARMS_GRANT,
            Duration.UNTIL_END_OF_TURN,
        )
    ]


@on(ProducedGold, "outlying_farms")
def _outlying_farms_produced_gold(ctx: TriggerContext) -> list[Effect]:
    """ "...if you did, destroy it after it bows." The price waits for the bow, so the Gold the
    grant bought reaches the pool before the card leaves play."""
    if ctx.event.card_id != ctx.card.id or not used_this_turn(ctx.game, ctx.card, SELF_GRANT):
        return []
    return [Destroy(ctx.card.id, Trait(ctx.card.id))]


# --- Repairing the Ruins ---


def _repairing_the_ruins_targets(game: GameState, source: L5RCard) -> list[str]:
    """Non-Unique Holdings in the seat's Dynasty deck or discard pile that they control no copy
    of."""
    seat = source.owner
    held = {card.printed_id for card in owned_holdings(game, seat)}
    searched = [
        *game.table.decks[DeckKey(seat, Side.DYNASTY)].cards,
        *game.table.zones[ZoneKey(seat, ZoneRole.DYNASTY_DISCARD)].cards,
    ]
    return [
        card.id
        for card in searched
        if isinstance(card.printed, HoldingPrint)
        and not card.printed.is_unique
        and card.printed_id not in held
    ]


def _repairing_the_ruins_effects(game: GameState, source: L5RCard, target: L5RCard) -> list[Effect]:
    """Discard the Event and put the found Holding in the Province it vacated, permanently +1 Gold
    Cost unless it came from the discard pile."""
    province = province_key_holding(game, source.owner, source.id)
    if province is None:
        return []
    # The discard is an effect rather than a cost: a cost resolves first, and the Province is read
    # off the Event, which by then is no longer in one.
    effects = [Discard(source.id, source.owner), PlaceInProvince(target.id, province)]
    discard = game.table.zones[ZoneKey(source.owner, ZoneRole.DYNASTY_DISCARD)]
    from_discard = any(card.id == target.id for card in discard.cards)
    if not from_discard:
        effects.append(GrantModifier(source.id, target.id, Stat.GOLD_COST, 1, Duration.PERMANENT))
    return effects


register_ability(
    "repairing_the_ruins",
    Ability(
        timings=(ActionTiming.OPEN,),
        keywords=frozenset({keywords.ECONOMIC}),
        cost=no_cost,
        targets=_repairing_the_ruins_targets,
        targeting_message="a non-Unique Holding of which you do not control any copies",
        effects=_repairing_the_ruins_effects,
        located_at=(CardLocation.PROVINCE,),
    ),
)


# --- Siege of the Great Wall ---

register_event_entry("siege_of_the_great_wall")


# --- Tao Defenders ---


@equips_from_discard("tao_defenders")
def _tao_defenders_equips_from_discard(game: GameState, card: L5RCard) -> bool:
    """Compassion: The rulebook Equip ability may target this Follower in the discard pile."""
    return has_compassion(game, card.owner, card)


def _tao_defenders_targets(game: GameState, source: L5RCard) -> list[str]:
    """The non-Shadowlands Rings in your discard pile, as the Follower's action counts them."""
    asking = Asking.action(source)
    return [
        card.id
        for card in game.table.zones[ZoneKey(source.owner, ZoneRole.FATE_DISCARD)].cards
        if counts_as(game, card, RingPrint, asking)
        and keywords.SHADOWLANDS not in effective_keywords(game, card)
    ]


def _tao_defenders_effects(game: GameState, source: L5RCard, target: L5RCard) -> list[Effect]:
    return [MoveToHand(target.id, source.owner), Destroy(source.id, source.owner)]


register_ability(
    "tao_defenders",
    Ability(
        timings=(ActionTiming.BATTLE, ActionTiming.OPEN),
        cost=no_cost,
        targets=_tao_defenders_targets,
        targeting_message="a non-Shadowlands Ring in your discard pile",
        effects=_tao_defenders_effects,
    ),
)


# --- The Forgotten ---


FORGOTTEN_DEAD = "forgotten_dead"
FORGOTTEN_HONOR_LOSS = 2


def _the_forgotten_entered_play_or_destroyed(ctx: TriggerContext) -> list[Effect]:
    """Lose 2 Honor and Equip another of the dead to a Personality.

    The Honor is lost whether or not there is anyone left to carry them, since the card asks for no
    target before charging it.
    """
    if ctx.event.card_id != ctx.card.id:
        return []
    seat = ctx.card.owner
    dead = ctx.game.table.creatable_tokens[FORGOTTEN_DEAD]
    effects: list[Effect] = [GainHonor(seat, -FORGOTTEN_HONOR_LOSS, source_id=ctx.card.id)]
    bearers = tuple(bearer.id for bearer in creation_targets(ctx.game, seat, dead))
    if bearers:
        effects.append(Choose(seat, bearers, 1, 1, "the_forgotten", ctx.card.id))
    return effects


# "After this Follower enters play or is destroyed" is one clause, so one handler on both events.
on(EnteredPlay, "the_forgotten")(_the_forgotten_entered_play_or_destroyed)
on(Destroyed, "the_forgotten")(_the_forgotten_entered_play_or_destroyed)


@choice_resolver("the_forgotten", prompt="Attach the Undead Follower to your target Personality")
def _resolve_the_forgotten(
    game: GameState, source_id: str, chosen: tuple[str, ...], seat: PlayerId
) -> list[Effect]:
    return [CreateToken(FORGOTTEN_DEAD, seat, source_id, attach_to=chosen[0])]


# --- The Unicorn Expedition ---

# The two Invest traits as printed, each its price and what it adds to the move. Either may be
# paid, or both together, on top of the action (CR, Invest).
UNICORN_EXPEDITION_STRAIGHTEN = "Invest 3: Straighten the target's unit as they move."
UNICORN_EXPEDITION_FOLLOW_UP = (
    "Invest 2: Take an additional action from a card in the target's unit after they move."
)
UNICORN_EXPEDITION_INVESTS = ((UNICORN_EXPEDITION_FOLLOW_UP, 2), (UNICORN_EXPEDITION_STRAIGHTEN, 3))
UNICORN_EXPEDITION_INVEST = "the_unicorn_expedition_invest"


def _the_unicorn_expedition_targets(game: GameState, source: L5RCard) -> list[str]:
    """Your Personalities away from the current battlefield, while an enemy unit there would
    oppose them."""
    attack = game.attack
    if attack is None or attack.current is None or not opposing_units_in_battle(game, source.owner):
        return []
    return [
        card.id
        for card in owned_personalities(game, source.owner)
        if location_of(game.table, card).battlefield != attack.current
    ]


def _the_unicorn_expedition_effects(
    game: GameState, source: L5RCard, target: L5RCard
) -> list[Effect]:
    """If they would be opposed, move the target to the current battlefield, with what each Invest
    the action was paid with adds. Both depend on the move happening, and the straightening is part
    of the same occurrence as the move."""
    if not opposing_units_in_battle(game, source.owner):
        return []
    invested = game.options_declared
    straighten = UNICORN_EXPEDITION_STRAIGHTEN in invested
    unit = unit_of(game, target)
    move = Move(target.id, Location.at_battlefield(game.attack.current))
    contingent: list[Effect] = []
    if straighten:
        contingent.extend(Straighten(card.id) for card in unit)
    if UNICORN_EXPEDITION_FOLLOW_UP in invested:
        follow_ups = frozenset(
            ActivateAbility(card.id, ability.key)
            for card in unit
            for ability in abilities_for(game, card)
        )
        contingent.append(AdditionalAction(source.owner, source.id, follow_ups))
    if not contingent:
        return [move]
    moved = To(move, tuple(contingent))
    return [Simultaneously((moved,))] if straighten else [moved]


def _the_unicorn_expedition_invest_cost(game: GameState, source: L5RCard) -> list[Effect]:
    """Ask which Invests to pay on top of the action, offering only what the seat can raise: each
    one it can afford, and both when it can afford the two together."""
    reach = reachable_gold(game, source.owner)
    affordable = tuple(line for line, price in UNICORN_EXPEDITION_INVESTS if price <= reach)
    both = sum(price for _, price in UNICORN_EXPEDITION_INVESTS) <= reach
    return [
        AskOption(
            source.owner,
            affordable,
            "Which Invests do you pay?",
            UNICORN_EXPEDITION_INVEST,
            source.id,
            maximum=2 if both else 1,
        )
    ]


@choice_resolver(UNICORN_EXPEDITION_INVEST)
def _the_unicorn_expedition_invest_paid(
    game: GameState, source_id: str, chosen: tuple[str, ...], seat: PlayerId
) -> list[Effect]:
    """Declare the Invests ticked, and pay them as one payment."""
    invested = sum(price for line, price in UNICORN_EXPEDITION_INVESTS if line in chosen)
    name = game.table.cards_by_id[source_id].name
    return [DeclareOptions(chosen), PayGold(seat, invested, f"{name} Invest")]


_THE_UNICORN_EXPEDITION = Ability(
    timings=(ActionTiming.BATTLE,),
    cost=no_cost,
    targets=_the_unicorn_expedition_targets,
    targeting_message="your Personality at any location",
    effects=_the_unicorn_expedition_effects,
    battle_designators=frozenset({BattleDesignator.ABSENT}),
    targets_any_location=True,
    located_at=(CardLocation.HAND,),
    key="battle",
)

register_ability("the_unicorn_expedition", _THE_UNICORN_EXPEDITION)
register_ability(
    "the_unicorn_expedition",
    replace(
        _THE_UNICORN_EXPEDITION,
        key="invest",
        label="Invest",
        cost=_the_unicorn_expedition_invest_cost,
    ),
)


# --- Unity of Spirit ---

UNITY_BONUS = 2
UNITY_FORCE = f"+{UNITY_BONUS}F"
UNITY_CHI = f"+{UNITY_BONUS}C"


def _unity_of_spirit_targets(game: GameState, source: L5RCard) -> list[str]:
    return list(opposed_units_in_battle(game, source.owner))


def _unity_of_spirit_effects(game: GameState, source: L5RCard, target: L5RCard) -> list[Effect]:
    """Straighten the target, and offer a Yojimbo +2F or +2C."""
    straightened: list[Effect] = [Straighten(target.id)]
    if keywords.YOJIMBO not in effective_keywords(game, target):
        return straightened
    offer = AskOption(
        source.owner,
        (UNITY_FORCE, UNITY_CHI),
        f"Give {target.name} which?",
        "unity_of_spirit_bonus",
        source.id,
        resolver_context=(target.id,),
    )
    return [*straightened, offer]


@choice_resolver("unity_of_spirit_bonus")
def _resolve_unity_of_spirit_bonus(
    game: GameState,
    source_id: str,
    chosen: tuple[str, ...],
    seat: PlayerId,
    resolver_context: tuple[str, ...] = (),
) -> list[Effect]:
    if not chosen:
        return []
    stat = Stat.FORCE if chosen[0] == UNITY_FORCE else Stat.CHI
    yojimbo_id = resolver_context[0]
    return [GrantModifier(source_id, yojimbo_id, stat, UNITY_BONUS, Duration.UNTIL_END_OF_TURN)]


register_ability(
    "unity_of_spirit",
    Ability(
        timings=(ActionTiming.BATTLE,),
        cost=no_cost,
        targets=_unity_of_spirit_targets,
        targeting_message="your opposed Personality",
        effects=_unity_of_spirit_effects,
        located_at=(CardLocation.HAND,),
    ),
)


def _unity_of_spirit_applies(game: GameState, source: L5RCard, effect: AttackEffect) -> bool:
    """The attack targets your Yojimbo and you control a Courtier or Shugenja."""
    target = game.table.cards_by_id.get(effect.target_id)
    return (
        target is not None
        and target in owned_personalities(game, source.owner)
        and keywords.YOJIMBO in effective_keywords(game, target)
        and any(
            has_keyword(game, card, keywords.COURTIER) or has_keyword(game, card, keywords.SHUGENJA)
            for card in owned_personalities(game, source.owner)
        )
    )


def _unity_of_spirit_interrupt(
    game: GameState, source: L5RCard, effect: AttackEffect
) -> Interruption:
    return Interruption(Negated(effect))


register_interrupt(
    "unity_of_spirit",
    Interrupt(
        printed_index=1,
        answers=MeleeAttack | RangedAttack,
        interrupt=_unity_of_spirit_interrupt,
        applies=_unity_of_spirit_applies,
    ),
)


# --- Verdant Wilds ---


def _verdant_wilds_targets(game: GameState, source: L5RCard) -> list[str]:
    """The controller's own bowed cards in play: "your target card" is one this seat owns.

    Narrowed to the bowed because straightening presupposes one, and no further. A card another card
    forbids to straighten stays on the list, since that prohibition is the other card's to enforce
    when the effect resolves, not this one's to read while choosing targets.
    """
    return [card.id for card in cards_in_play(game, source.owner) if card.bowed]


def _verdant_wilds_effects(game: GameState, source: L5RCard, target: L5RCard) -> list[Effect]:
    return [Straighten(target.id)]


register_ability(
    "verdant_wilds",
    Ability(
        printed_index=1,
        timings=(ActionTiming.OPEN,),
        cost=bow_cost,
        targets=_verdant_wilds_targets,
        targeting_message="your card",
        effects=_verdant_wilds_effects,
    ),
)
