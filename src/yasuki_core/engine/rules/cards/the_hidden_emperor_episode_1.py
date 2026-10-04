from yasuki_core.engine.players import PlayerId
from yasuki_core.engine.rules.abilities.costs import no_cost
from yasuki_core.engine.rules.abilities.model import Ability, CardLocation
from yasuki_core.engine.rules.abilities.registry import register_ability
from yasuki_core.engine.rules.board.queries import (
    owned_carrying,
    personalities_in_play,
)
from yasuki_core.engine.rules.effects import Bow, Choose, Effect, GrantModifier
from yasuki_core.engine.rules.legality import location_permits
from yasuki_core.engine.rules.state import GameState
from yasuki_core.engine.rules.stats.card_values import effective_force, effective_personal_honor
from yasuki_core.engine.rules.triggers import choice_resolver
from yasuki_core.engine.rules.vocabulary import keywords
from yasuki_core.engine.rules.vocabulary.actions import ActionTiming
from yasuki_core.engine.rules.vocabulary.modifiers import Duration, Stat
from yasuki_core.game_pieces.cards import L5RCard


# --- Chasing Osano-Wo ---


def _chasing_osano_wo_recipients(game: GameState) -> tuple[str, ...]:
    """The Personalities the action may target where they stand. Only the performer is targeted
    "at any location"."""
    return tuple(card.id for card in personalities_in_play(game) if location_permits(game, card))


def _chasing_osano_wo_targets(game: GameState, source: L5RCard) -> list[str]:
    """Your unbowed Monks and Shugenja, Followers among them, at any location, once there is a
    Personality to give the bonus to."""
    if not _chasing_osano_wo_recipients(game):
        return []
    return [
        card.id
        for card in owned_carrying(game, source.owner, keywords.MONK, keywords.SHUGENJA)
        if not card.bowed
    ]


def _chasing_osano_wo_effects(game: GameState, source: L5RCard, target: L5RCard) -> list[Effect]:
    """Bow the first target, then give the bonus. The first target stands as the choice's source so
    its resolver can read his Force."""
    recipients = _chasing_osano_wo_recipients(game)
    return [Bow(target.id), Choose(source.owner, recipients, 1, 1, "chasing_osano_wo", target.id)]


@choice_resolver("chasing_osano_wo", prompt="Give a target Personality the Force bonus")
def _resolve_chasing_osano_wo(
    game: GameState, source_id: str, chosen: tuple[str, ...], seat: PlayerId
) -> list[Effect]:
    """ "A Force bonus equal to their Personal Honor plus the Force of the first target." """
    first = game.table.cards_by_id[source_id]
    recipient = game.table.cards_by_id[chosen[0]]
    bonus = effective_personal_honor(game, recipient) + effective_force(game, first)
    return [GrantModifier(source_id, recipient.id, Stat.FORCE, bonus, Duration.UNTIL_END_OF_TURN)]


register_ability(
    "chasing_osano_wo",
    Ability(
        timings=(ActionTiming.BATTLE,),
        keywords=frozenset({keywords.KIHO, keywords.THUNDER}),
        cost=no_cost,
        targets=_chasing_osano_wo_targets,
        targeting_message="your performing Monk or Shugenja",
        effects=_chasing_osano_wo_effects,
        located_at=(CardLocation.HAND,),
        targets_any_location=True,
    ),
)
