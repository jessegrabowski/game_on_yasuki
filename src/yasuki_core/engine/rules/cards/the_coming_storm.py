from yasuki_core import ruleset
from yasuki_core.engine.rules.abilities import (
    Ability,
    LOBBIED_TAG,
    bow_cost,
    favor_cost,
    itself,
    personalities_in_play,
    register_ability,
)
from yasuki_core.engine.rules.actions import ActionTiming
from yasuki_core.engine.rules.economy import (
    PlayerState,
    is_clan,
    lobby_bonus_grant,
    province_strength_grant,
    recruit_discount,
)
from yasuki_core.engine.rules.effects import Effect, GainHonor, Straighten
from yasuki_core.engine.rules.state import GameState, used_this_turn
from yasuki_core.engine.table import ZoneKey
from yasuki_core.game_pieces.cards import L5RCard


# --- Defensive Memorial ---


@province_strength_grant("defensive_memorial")
def _defensive_memorial_province_strength(game: GameState, card: L5RCard, province: ZoneKey) -> int:
    """ "This Province has +2 strength." Its other two lines need no handler: a Holding enters play
    bowed by the rulebook, and ":bow:: Produce 2 Gold" is the Gold Production it prints."""
    return 2


# --- Doji Natsuyo ---

NATSUYO_HONOR = 1


@recruit_discount("doji_natsuyo")
def _doji_natsuyo_recruit_discount(
    card: L5RCard, me: PlayerState, opponents: tuple[PlayerState, ...]
) -> int:
    """Enters play for 1 less Gold if another player is Scorpion Clan."""
    return 1 if any(is_clan(other, ruleset.SCORPION) for other in opponents) else 0


def _doji_natsuyo_cost(game: GameState, source: L5RCard) -> list[Effect]:
    """Bow her and pay the Favor. Either half alone leaves the ability unpayable, so both are
    settled before it resolves (CR, Action Sequence step B)."""
    return [*bow_cost(game, source), *favor_cost(game, source)]


def _doji_natsuyo_effects(game: GameState, source: L5RCard, target: L5RCard) -> list[Effect]:
    """Gain 1 Honor."""
    return [GainHonor(source.owner, NATSUYO_HONOR)]


register_ability(
    "doji_natsuyo",
    Ability(
        timings=(ActionTiming.OPEN,),
        label="Open: Bow and pay the Imperial Favor to gain 1 Honor",
        cost=_doji_natsuyo_cost,
        targets=itself,
        effects=_doji_natsuyo_effects,
        all_targets=True,
    ),
)


# --- Shigekawa's Court ---


@lobby_bonus_grant("shigekawas_court")
def _shigekawas_court_lobby_bonus(game: GameState, card: L5RCard) -> int:
    """ "You have a +5 Lobby Bonus." Whatever amount a Lobby action checks about its controller, not
    Family Honor alone. Its ":bow:: Produce 1 Gold" is the Gold Production it prints."""
    return 5


def _shigekawas_court_targets(game: GameState, source: L5RCard) -> list[str]:
    """The Personalities who Lobbied this turn — anyone's, since the card says "a target
    Personality" rather than "your target Personality"."""
    return [
        card.id for card in personalities_in_play(game) if used_this_turn(game, card, LOBBIED_TAG)
    ]


def _shigekawas_court_effects(game: GameState, source: L5RCard, target: L5RCard) -> list[Effect]:
    return [Straighten(target.id)]


register_ability(
    "shigekawas_court",
    Ability(
        timings=(ActionTiming.OPEN,),
        label="Open: Bow to straighten a Personality who Lobbied this turn",
        cost=bow_cost,
        targets=_shigekawas_court_targets,
        effects=_shigekawas_court_effects,
    ),
)
