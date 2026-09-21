from yasuki_core import ruleset
from yasuki_core.engine.players import PlayerId
from yasuki_core.engine.rules.rulebook.lobby import register_may_not_lobby
from yasuki_core.engine.rules.abilities.costs import bow_cost, no_cost
from yasuki_core.engine.rules.abilities.idioms import one_wealth, register_event_entry
from yasuki_core.engine.rules.abilities.model import Ability, InvestAbility
from yasuki_core.engine.rules.abilities.registry import (
    invest_amounts,
    register_ability,
    register_invest,
)
from yasuki_core.engine.rules.vocabulary.actions import ActionTiming, BattleDesignator
from yasuki_core.engine.rules.effects import (
    AdditionalAction,
    AdjustCounter,
    Banish,
    Choose,
    CreateToken,
    Effect,
    Fear,
    GainHonor,
    GrantKeyword,
    Move,
    Straighten,
    TakeFavor,
)
from yasuki_core.engine.rules.rulebook.equip import creation_targets
from yasuki_core.engine.rules.vocabulary.game_events import CardDiscarded, EnteredPlay
from yasuki_core.engine.rules.state import GameState
from yasuki_core.engine.rules.action_record import action_keywords
from yasuki_core.engine.rules.triggers import TriggerContext, action_did, choice_resolver, on
from yasuki_core.engine.rules.board.clans import card_alignments
from yasuki_core.engine.rules.board.queries import (
    attack_targets,
    opposing_units_in_battle,
    owned_personalities,
    personalities_in_play,
    sincerity_seed_targets,
    units_at,
)
from yasuki_core.engine.rules.stats.card_values import effective_force, effective_personal_honor
from yasuki_core.engine.rules.stats.stat_grants import stat_grant
from yasuki_core.engine.rules.vocabulary.modifiers import Duration, Stat
from yasuki_core.engine.rules.vocabulary import keywords
from yasuki_core.engine.table import Location, location_of
from yasuki_core.game_pieces.cards import L5RCard
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
        label="Home Tireless Response: after a Political action, move your target Personality to "
        "Aoi and straighten them",
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
        label="Battle, bow: Move home a target enemy defending Personality. You may target your "
        "Personality with higher Personal Honor to straighten this Stronghold and gain 1 Honor",
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
        label="Battle, bow: Move home a target enemy defending Personality. Gain 1 Honor",
        cost=bow_cost,
        targets=_the_ancient_castle_of_the_lion_targets,
        effects=_the_ancient_castle_of_the_lion__back_effects,
    ),
)


# --- The Dark Capital of the Spider ---

# "You lose 1 Honor less from your cards" is not modeled: nothing reads how much Honor a card's
# effect costs its own controller. The Battle ability is.

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
        label="Tireless Battle: Give a target Personality Shadowlands. If they are yours, Fear "
        "equal to their Force. Otherwise, take an additional action.",
        cost=no_cost,
        targets=_the_dark_capital_of_the_spider_targets,
        effects=_the_dark_capital_of_the_spider_effects,
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
        label="Political Response: after paying the Imperial Favor, take it",
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
        label="Response: seed a Sincerity token onto one of your Sincerity cards",
        cost=no_cost,
        targets=_training_court_targets,
        targeting_message="one of your Sincerity cards",
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
        label="Open: Bow to Equip a 1F Cavalry Follower to your Samurai",
        cost=bow_cost,
        targets=_utaku_gorou_stablemaster_targets,
        targeting_message="your Samurai",
        effects=_utaku_gorou_stablemaster_effects,
    ),
)
