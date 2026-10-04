from yasuki_core import ruleset
from yasuki_core.engine.players import PlayerId
from yasuki_core.engine.rules.rulebook.favor_payment import favor_cost
from yasuki_core.engine.rules.rulebook.lobby import LOBBIED_TAG
from yasuki_core.engine.rules.abilities.costs import bow_cost, no_cost
from yasuki_core.engine.rules.abilities.model import Ability, CardLocation, itself
from yasuki_core.engine.rules.abilities.registry import register_ability
from yasuki_core.engine.rules.board.queries import (
    followers_in_play,
    opposed_units_in_battle,
    personalities_in_play,
)
from yasuki_core.engine.rules.vocabulary.actions import ActionTiming
from yasuki_core.engine.rules.stats.province_strength import province_strength_grant
from yasuki_core.engine.rules.gold.discounts import recruit_discount
from yasuki_core.engine.rules.rulebook.lobby import lobby_bonus_grant
from yasuki_core.engine.rules.board.clans import is_clan
from yasuki_core.engine.rules.board.seats import opposing_seats
from yasuki_core.engine.rules.duel.focus_effects import focus_effect
from yasuki_core.engine.rules.effects import (
    AskOption,
    Choose,
    Effect,
    EndDuel,
    GainHonor,
    GrantModifier,
    Straighten,
)
from yasuki_core.engine.rules.state import GameState, used_this_turn
from yasuki_core.engine.rules.triggers import choice_resolver
from yasuki_core.engine.rules.vocabulary import keywords
from yasuki_core.engine.rules.vocabulary.modifiers import Duration, Stat
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
def _doji_natsuyo_recruit_discount(card: L5RCard, game: GameState, seat: PlayerId) -> int:
    """Enters play for 1 less Gold if another player is Scorpion Clan."""
    rivals = opposing_seats(game, seat)
    return 1 if any(is_clan(game, other, ruleset.SCORPION) for other in rivals) else 0


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
        keywords=frozenset({keywords.POLITICAL}),
        cost=_doji_natsuyo_cost,
        targets=itself,
        effects=_doji_natsuyo_effects,
        hits_every_target=True,
    ),
)


# --- Relentless ---


@focus_effect("relentless")
def _relentless_focus_effect(game: GameState, card: L5RCard) -> list[Effect]:
    """ "As a Focus Effect, if the duel is not during a battle, end the duel without resolution."

    Whether a battle is being fought is read off the attack, because a duel's steps stand over a
    battle segment without being one.
    """
    attack = game.attack
    if attack is not None and attack.current is not None:
        return []
    return [EndDuel()]


RELENTLESS_FORCE = 1
RELENTLESS_STRONGER = "Give it +1F"
RELENTLESS_WEAKER = "Give it -1F"


def _relentless_targets(game: GameState, source: L5RCard) -> list[str]:
    """Your Personalities opposed at the battle being fought, which the card straightens. Empty
    outside a battle, which is what withholds the action."""
    return list(opposed_units_in_battle(game, source.owner))


def _relentless_effects(game: GameState, source: L5RCard, target: L5RCard) -> list[Effect]:
    """ "Straighten your target opposed card. Give a target Follower or Personality +1F or -1F."

    Two targets from two pools, so the first is the ability's and the second a pick of its own, as
    one ability takes one target. The second names no battlefield, where the first says "opposed",
    so it reaches any Follower or Personality in play rather than only the ones standing at the
    battle being fought.
    """
    candidates = tuple(card.id for card in (*personalities_in_play(game), *followers_in_play(game)))
    return [
        Straighten(target.id),
        Choose(
            seat=source.owner,
            candidates=candidates,
            minimum=1,
            maximum=1,
            resolver="relentless_force",
            source_id=source.id,
        ),
    ]


@choice_resolver(
    "relentless_force", prompt="Choose a Follower or Personality to strengthen or weaken"
)
def _resolve_relentless_force(
    game: GameState, source_id: str, chosen: tuple[str, ...], seat: PlayerId
) -> list[Effect]:
    """Having picked the card, the seat picks which way its Force moves."""
    card = game.table.cards_by_id[chosen[0]]
    return [
        AskOption(
            seat=seat,
            options=(RELENTLESS_STRONGER, RELENTLESS_WEAKER),
            question=f"{card.name}: which way does its Force move?",
            resolver="relentless_force_direction",
            source_id=source_id,
            resolver_context=(chosen[0],),
        )
    ]


@choice_resolver("relentless_force_direction")
def _resolve_relentless_force_direction(
    game: GameState,
    source_id: str,
    chosen: tuple[str, ...],
    seat: PlayerId,
    resolver_context: tuple[str, ...] = (),
) -> list[Effect]:
    """The text gives the change no duration, so it runs to the end of the turn (CR, Ongoing)."""
    (target_id,) = resolver_context
    amount = RELENTLESS_FORCE if chosen[0] == RELENTLESS_STRONGER else -RELENTLESS_FORCE
    return [
        GrantModifier(
            source_id=source_id,
            target_id=target_id,
            stat=Stat.FORCE,
            amount=amount,
            duration=Duration.UNTIL_END_OF_TURN,
        )
    ]


register_ability(
    "relentless",
    Ability(
        timings=(ActionTiming.BATTLE,),
        cost=no_cost,
        targets=_relentless_targets,
        targeting_message="your opposed Personality",
        effects=_relentless_effects,
        located_at=(CardLocation.HAND,),
    ),
)


# --- Shigekawa's Court ---


@lobby_bonus_grant("shigekawas_court")
def _shigekawas_court_lobby_bonus(game: GameState, card: L5RCard) -> int:
    """ "You have a +5 Lobby Bonus." Whatever amount a Lobby action checks about its controller, not
    Family Honor alone. Its ":bow:: Produce 1 Gold" is the Gold Production it prints."""
    return 5


def _shigekawas_court_targets(game: GameState, source: L5RCard) -> list[str]:
    """The Personalities who Lobbied this turn. Anyone's is legal, since the card says "a target
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
        cost=bow_cost,
        targets=_shigekawas_court_targets,
        targeting_message="a Personality who Lobbied this turn",
        effects=_shigekawas_court_effects,
    ),
)
