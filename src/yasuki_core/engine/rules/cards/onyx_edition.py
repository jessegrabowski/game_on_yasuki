from yasuki_core import ruleset
from yasuki_core.engine.players import PlayerId
from yasuki_core.engine.rules.rulebook.lobby import register_may_not_lobby
from yasuki_core.engine.rules.abilities.costs import bow_cost, no_cost
from yasuki_core.engine.rules.abilities.idioms import (
    RING_PITCH,
    one_wealth,
    register_entry,
    register_event_entry,
    register_ring,
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
)
from yasuki_core.engine.rules.abilities.registry import (
    invest_amounts,
    register_ability,
    register_interrupt,
    register_invest,
)
from yasuki_core.engine.rules.vocabulary.actions import ActionTiming, BattleDesignator
from yasuki_core.engine.rules.effects import (
    AdditionalAction,
    AdjustCounter,
    Banish,
    Choose,
    CreateToken,
    DelayedEffect,
    Destroy,
    Discard,
    DrawCard,
    Effect,
    Evaluate,
    Fear,
    GainHonor,
    GrantKeyword,
    Move,
    Negated,
    Straighten,
    TakeFavor,
)
from yasuki_core.engine.rules.rulebook.equip import creation_targets
from yasuki_core.engine.rules.vocabulary.game_events import (
    ActionResolved,
    CardDiscarded,
    EnteredPlay,
)
from yasuki_core.engine.rules.state import GameState
from yasuki_core.engine.rules.action_record import action_keywords, action_round
from yasuki_core.engine.rules.legality import permitted_timings_in
from yasuki_core.engine.rules.turn.structure import END_OF_BATTLE
from yasuki_core.engine.rules.units.membership import attached_to, attachments_of
from yasuki_core.engine.rules.triggers import TriggerContext, action_did, choice_resolver, on
from yasuki_core.engine.rules.board.clans import card_alignments
from yasuki_core.engine.rules.board.queries import (
    attack_targets,
    opposing_units_in_battle,
    owned_personalities,
    personalities_in_play,
    rings_in_play,
    sincerity_seed_targets,
    units_at,
)
from yasuki_core.engine.rules.board.seats import cards_in_play
from yasuki_core.engine.rules.stats.card_values import effective_force, effective_personal_honor
from yasuki_core.engine.rules.stats.stat_grants import stat_grant
from yasuki_core.engine.rules.vocabulary.modifiers import Duration, Stat
from yasuki_core.engine.rules.vocabulary import keywords
from yasuki_core.engine.table import Location, ZoneKey, ZoneRole, location_of
from yasuki_core.game_pieces.cards import L5RCard
from yasuki_core.game_pieces.prints import AttachmentPrint, PersonalityPrint, StrongholdPrint
from yasuki_core.game_pieces.counters import SINCERITY


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
    return [CreateToken(LION_ANCESTOR, source.owner, source.id) for _ in range(ancestors)]


register_invest(
    "kitsu_hayako",
    InvestAbility(amounts=(ONE_ANCESTOR, TWO_ANCESTORS), effect=_kitsu_hayako_invest),
)


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
    pitch=RING_PITCH,
    ruleset=ruleset.ONYX.name,
)


# --- Ring of Earth ---

# "Play after a battle resolves at your Province, if it was not destroyed and any enemy units were
# ever at its battlefield." Nothing records what a battle did once it resolves, so the entry has no
# handler. The pitch is the Interrupt taken from hand, which the Interrupt step plays as a Strategy.


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
# higher Chi than the other." Duels are not modeled, so the entry has no handler.


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
    pitch=RING_PITCH,
    ruleset=ruleset.ONYX.name,
)


# --- Ring of the Void ---

VOID_RINGS_ALLOWED = 2


def _ring_of_the_void_condition(game: GameState, source: L5RCard) -> bool:
    """ "Play if you have two or fewer Rings in play." """
    return len(rings_in_play(game, source.owner)) <= VOID_RINGS_ALLOWED


def _ring_of_the_void_entry_effects(game: GameState, source: L5RCard) -> list[Effect]:
    """ "Discard your hand." The Ring itself has entered play by the time these resolve, so it is
    left out of what was in hand."""
    hand = game.table.zones[ZoneKey(source.owner, ZoneRole.HAND)].cards
    return [Discard(card.id, source.owner) for card in hand if card.id != source.id]


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
        each: tuple(card.id for card in game.table.zones[ZoneKey(each, ZoneRole.HAND)].cards)
        for each in game.table.seats
    }
    mine = hands.pop(seat)
    if len(mine) <= max((len(theirs) for theirs in hands.values()), default=0):
        return []
    return [Choose(seat, mine, 1, 1, "ring_of_the_void_discard", source_id)]


@choice_resolver("ring_of_the_void_discard")
def _resolve_ring_of_the_void_discard(
    game: GameState, source_id: str, chosen: tuple[str, ...], seat: PlayerId
) -> list[Effect]:
    return [Discard(chosen[0], seat)]


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
    pitch="You may discard this Ring from your hand to use its Void ability without cost.",
    ruleset=ruleset.ONYX.name,
)


# --- Ring of Water ---

# "Play after a battle resolves in which you played a Terrain, destroyed a Terrain, and destroyed
# any cards or provinces during resolution." Terrain is not modeled and nothing records what a
# battle did once it resolves, so the entry has no handler.


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
    pitch=RING_PITCH,
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

# "You lose 1 Honor less from your cards" (2 on the back) is not modeled: nothing reads how much
# Honor a card's effect costs its own controller. The Battle ability is.

DARK_CAPITAL_FEAR = "the_dark_capital_of_the_spider"


def _the_dark_capital_of_the_spider_targets(game: GameState, source: L5RCard) -> list[str]:
    return [card.id for card in personalities_in_play(game)]


def _the_dark_capital_of_the_spider_effects(
    game: GameState, source: L5RCard, target: L5RCard
) -> list[Effect]:
    """ "Give a target Personality Shadowlands. If they are yours, Fear equal to their Force.
    Otherwise, take an additional action." The Fear targets the way any Fear does, chosen as it
    resolves, and is not raised when nothing at the battle can be targeted."""
    effects: list[Effect] = [
        GrantKeyword(source.id, target.id, keywords.SHADOWLANDS, Duration.UNTIL_END_OF_TURN)
    ]
    if target.owner is not source.owner:
        return [*effects, AdditionalAction(source.owner)]
    feared = attack_targets(game, source)
    if feared:
        effects.append(Choose(source.owner, tuple(feared), 1, 1, DARK_CAPITAL_FEAR, target.id))
    return effects


@choice_resolver(DARK_CAPITAL_FEAR, prompt="Fear equal to their Force: choose its target")
def _the_dark_capital_of_the_spider_fear(
    game: GameState, source_id: str, chosen: tuple[str, ...], seat: PlayerId
) -> list[Effect]:
    """``source_id`` is the Personality given Shadowlands, whose Force the Fear reads as it
    resolves."""
    strength = effective_force(game, game.table.cards_by_id[source_id])
    return [Fear(strength, chosen[0], seat)]


register_ability(
    "the_dark_capital_of_the_spider",
    Ability(
        timings=(ActionTiming.BATTLE,),
        cost=no_cost,
        targets=_the_dark_capital_of_the_spider_targets,
        effects=_the_dark_capital_of_the_spider_effects,
        tireless=True,
    ),
)


# --- The Dark Capital of the Spider (back) ---


def _the_dark_capital_of_the_spider__back_effects(
    game: GameState, source: L5RCard, target: L5RCard
) -> list[Effect]:
    """ "If they are yours and this is a Battle, Fear equal to their Force. Otherwise, take an
    additional action." Taken as an Open, even on the controller's own Personality, it is the
    additional action."""
    in_battle = ActionTiming.BATTLE in permitted_timings_in(game, action_round(game), source.owner)
    if in_battle:
        return _the_dark_capital_of_the_spider_effects(game, source, target)
    return [
        GrantKeyword(source.id, target.id, keywords.SHADOWLANDS, Duration.UNTIL_END_OF_TURN),
        AdditionalAction(source.owner),
    ]


register_ability(
    "the_dark_capital_of_the_spider__back",
    Ability(
        timings=(ActionTiming.BATTLE, ActionTiming.OPEN),
        cost=no_cost,
        targets=_the_dark_capital_of_the_spider_targets,
        effects=_the_dark_capital_of_the_spider__back_effects,
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


# --- Training Court ---


def _training_court_targets(game: GameState, source: L5RCard) -> list[str]:
    """The controller's token-less Sincerity cards still in a Province, once the action just
    resolved was the one that Recruited this Holding."""
    if not any(event.card_id == source.id for event in action_did(game, EnteredPlay)):
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
