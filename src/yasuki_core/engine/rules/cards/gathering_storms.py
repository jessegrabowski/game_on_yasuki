from yasuki_core.engine.players import PlayerId
from yasuki_core.engine.rules.abilities.costs import bow_cost
from yasuki_core.engine.rules.abilities.idioms import plus_one_gp_this_turn
from yasuki_core.engine.rules.abilities.model import Ability
from yasuki_core.engine.rules.abilities.registry import register_ability
from yasuki_core.engine.rules.board.queries import (
    attack_targets,
    followers_in_play,
    owned_holdings,
    personalities_in_play,
)
from yasuki_core.engine.rules.gold.production import gold_handler
from yasuki_core.engine.rules.legality import location_permits
from yasuki_core.engine.rules.board.seats import opposing_seats, seat_stronghold
from yasuki_core.engine.rules.effects import (
    AdjustCounter,
    BanishTopFate,
    Choose,
    Destroy,
    DrawCard,
    Effect,
    GrantModifier,
    RangedAttack,
    Unpayable,
)
from yasuki_core.engine.rules.triggers import choice_resolver
from yasuki_core.engine.rules.units.composition import followers_of
from yasuki_core.engine.rules.vocabulary.actions import ActionTiming
from yasuki_core.engine.rules.vocabulary.modifiers import Duration, Stat
from yasuki_core.engine.rules.state import GameState
from yasuki_core.engine.rules.vocabulary import keywords
from yasuki_core.game_pieces.cards import L5RCard
from yasuki_core.game_pieces.counters import WEALTH
from yasuki_core.game_pieces.prints import PersonalityPrint


# --- Ancestral Estate ---


@gold_handler("ancestral_estate")
def _ancestral_estate_gold(
    card: L5RCard, game: GameState, seat: PlayerId, targets: tuple[L5RCard, ...]
) -> int:
    """+1 GP while another player's Stronghold has higher Gold Production than yours.

    Your own missing Stronghold counts as producing nothing. An opponent's missing Stronghold has
    no production to compare and never grants the bonus.
    """
    own = seat_stronghold(game, seat)
    own_production = own.gold_production if own is not None else 0
    rivals = (seat_stronghold(game, other) for other in opposing_seats(game, seat))
    outproduced = any(
        rival is not None and rival.gold_production > own_production for rival in rivals
    )
    return card.gold_production + (1 if outproduced else 0)


# --- Ichiba District ---


def _ichiba_district_cost(game: GameState, source: L5RCard) -> list[Effect]:
    return [BanishTopFate(source.owner)]


def _ichiba_district_targets(game: GameState, card: L5RCard) -> list[str]:
    return [port.id for port in owned_holdings(game, card.owner, keywords.PORT)]


register_ability(
    "ichiba_district",
    Ability(
        timings=(ActionTiming.OPEN,),
        label="Banish a Fate card: give a Port +1 Gold Production",
        cost=_ichiba_district_cost,
        targets=_ichiba_district_targets,
        effects=plus_one_gp_this_turn,
    ),
)


# --- Mantis Kama ---

MANTIS_KAMA_PENALTY = -2


def _mantis_kama_penalty(source_id: str, target_id: str) -> GrantModifier:
    """The -2F the card gives, whichever of its two targets takes it."""
    return GrantModifier(
        source_id, target_id, Stat.FORCE, MANTIS_KAMA_PENALTY, Duration.UNTIL_END_OF_TURN
    )


def _mantis_kama_targets(game: GameState, source: L5RCard) -> list[str]:
    """Every Personality and Follower in play: the card reaches either a single Personality or a
    Follower, and a Follower target may bring in a second one through the effect."""
    return [card.id for card in personalities_in_play(game)] + [
        follower.id for follower in followers_in_play(game)
    ]


def _mantis_kama_effects(game: GameState, source: L5RCard, target: L5RCard) -> list[Effect]:
    """-2F to the chosen target. Only a Follower target may bring in a second, since the card reads
    "a target Personality or ... one or two target Followers".

    The second Follower is filtered here rather than centrally: ``legal_targets`` narrows what an
    ability's own predicate offers, and a choice an effect raises never passes through it.
    """
    penalty = _mantis_kama_penalty(source.id, target.id)
    if isinstance(target.printed, PersonalityPrint):
        return [penalty]
    others = tuple(
        follower.id
        for follower in followers_in_play(game)
        if follower.id != target.id and location_permits(game, follower)
    )
    if not others:
        return [penalty]
    return [penalty, Choose(source.owner, others, 0, 1, "mantis_kama", source.id)]


@choice_resolver("mantis_kama", prompt="Give a second target Follower -2F")
def _resolve_mantis_kama(
    game: GameState, source_id: str, chosen: tuple[str, ...], seat: PlayerId
) -> list[Effect]:
    return [_mantis_kama_penalty(source_id, follower_id) for follower_id in chosen]


register_ability(
    "mantis_kama",
    Ability(
        timings=(ActionTiming.BATTLE,),
        label="Battle, Bow: Give -2F to a target Personality or to one or two target Followers",
        cost=bow_cost,
        targets=_mantis_kama_targets,
        effects=_mantis_kama_effects,
    ),
)


# --- Otokoshi District ---


def _otokoshi_district_cost(game: GameState, source: L5RCard) -> list[Effect]:
    return [Destroy(source.id, source.owner)]


def _otokoshi_district_targets(game: GameState, card: L5RCard) -> list[str]:
    return [market.id for market in owned_holdings(game, card.owner, keywords.MARKET)]


def _otokoshi_district_effects(game: GameState, source: L5RCard, target: L5RCard) -> list[Effect]:
    return [DrawCard(source.owner), AdjustCounter(target.id, WEALTH, 1)]


register_ability(
    "otokoshi_district",
    Ability(
        timings=(ActionTiming.OPEN,),
        label="Tireless Open: Destroy this Holding to draw a card and give your target Market a +1GP Wealth token",
        cost=_otokoshi_district_cost,
        targets=_otokoshi_district_targets,
        effects=_otokoshi_district_effects,
        tireless=True,
    ),
)


# --- Yoritomo Bunrakuken ---

BUNRAKUKEN_RANGED = 2


def _yoritomo_bunrakuken_cost(game: GameState, source: L5RCard) -> list[Effect]:
    """Destroy Bunrakuken's target Follower. Unpayable with none attached, since the destruction
    is the whole cost rather than something else the ability could pay instead. With more than one
    attached, the seat picks which; with exactly one there is nothing to ask.
    """
    followers = followers_of(game, source)
    if not followers:
        return [Unpayable(f"{source.id} carries no Follower to destroy")]
    if len(followers) == 1:
        return [Destroy(followers[0].id, source.owner)]
    return [
        Choose(
            source.owner,
            tuple(follower.id for follower in followers),
            1,
            1,
            "yoritomo_bunrakuken_follower",
            source.id,
        )
    ]


@choice_resolver("yoritomo_bunrakuken_follower", prompt="Destroy Bunrakuken's target Follower")
def _resolve_yoritomo_bunrakuken_follower(
    game: GameState, source_id: str, chosen: tuple[str, ...], seat: PlayerId
) -> list[Effect]:
    return [Destroy(chosen[0], seat)]


def _yoritomo_bunrakuken_effects(game: GameState, source: L5RCard, target: L5RCard) -> list[Effect]:
    return [RangedAttack(BUNRAKUKEN_RANGED, target.id, source.owner)]


register_ability(
    "yoritomo_bunrakuken",
    Ability(
        timings=(ActionTiming.BATTLE,),
        label=f"Battle: Destroy Bunrakuken's target Follower to make Ranged {BUNRAKUKEN_RANGED}",
        cost=_yoritomo_bunrakuken_cost,
        targets=attack_targets,
        effects=_yoritomo_bunrakuken_effects,
    ),
)
