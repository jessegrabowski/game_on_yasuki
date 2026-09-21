from yasuki_core import ruleset
from yasuki_core.engine.rules.abilities.costs import no_cost
from yasuki_core.engine.rules.abilities.model import Ability
from yasuki_core.engine.rules.abilities.registry import register_ability
from yasuki_core.engine.rules.board.clans import card_alignments
from yasuki_core.engine.rules.board.queries import (
    has_keyword,
    opposed_units_in_battle,
    opposing_units_in_battle,
)
from yasuki_core.engine.rules.effects import Effect, GrantModifier
from yasuki_core.engine.rules.stats.card_values import effective_personal_honor
from yasuki_core.engine.rules.stats.stat_grants import stat_grant
from yasuki_core.engine.rules.state import GameState
from yasuki_core.engine.rules.vocabulary import keywords
from yasuki_core.engine.rules.vocabulary.actions import ActionTiming
from yasuki_core.engine.rules.vocabulary.modifiers import Duration, Stat
from yasuki_core.engine.table import location_of
from yasuki_core.game_pieces.cards import L5RCard


# --- The Honorable Garrison of the Lion ---

HONORABLE_GARRISON_LABEL = (
    "Battle: Give your target opposed Lion Clan Samurai a Force bonus equal to his Personal Honor"
    " (this turn)"
)


def _the_honorable_garrison_of_the_lion_targets(game: GameState, source: L5RCard) -> list[str]:
    opposed = (
        game.table.cards_by_id[card_id] for card_id in opposed_units_in_battle(game, source.owner)
    )
    return [
        card.id
        for card in opposed
        if ruleset.LION in card_alignments(card) and has_keyword(game, card, keywords.SAMURAI)
    ]


def _the_honorable_garrison_of_the_lion_effects(
    game: GameState, source: L5RCard, target: L5RCard
) -> list[Effect]:
    return [
        GrantModifier(
            source.id,
            target.id,
            Stat.FORCE,
            effective_personal_honor(game, target),
            Duration.UNTIL_END_OF_TURN,
        )
    ]


register_ability(
    "the_honorable_garrison_of_the_lion",
    Ability(
        timings=(ActionTiming.BATTLE,),
        label=HONORABLE_GARRISON_LABEL,
        cost=no_cost,
        targets=_the_honorable_garrison_of_the_lion_targets,
        effects=_the_honorable_garrison_of_the_lion_effects,
    ),
)


# --- The Honorable Garrison of the Lion (back) ---

register_ability(
    "the_honorable_garrison_of_the_lion__back",
    Ability(
        timings=(ActionTiming.BATTLE,),
        label=HONORABLE_GARRISON_LABEL,
        cost=no_cost,
        targets=_the_honorable_garrison_of_the_lion_targets,
        effects=_the_honorable_garrison_of_the_lion_effects,
    ),
)


# --- The Impregnable Fortress of the Crab ---


@stat_grant("the_impregnable_fortress_of_the_crab")
def _the_impregnable_fortress_of_the_crab_stat_grant(
    game: GameState, source: L5RCard, card: L5RCard, stat: Stat
) -> int:
    """Your Crab Clan Personalities have +1F while opposed."""
    attack = game.attack
    if stat is not Stat.FORCE or card.owner is not source.owner or attack is None:
        return 0
    if ruleset.CRAB not in card_alignments(card):
        return 0
    if location_of(game.table, card).battlefield != attack.current:
        return 0
    return 1 if opposing_units_in_battle(game, source.owner) else 0


# --- The Impregnable Fortress of the Crab (back) ---


@stat_grant("the_impregnable_fortress_of_the_crab__back")
def _the_impregnable_fortress_of_the_crab__back_stat_grant(
    game: GameState, source: L5RCard, card: L5RCard, stat: Stat
) -> int:
    return _the_impregnable_fortress_of_the_crab_stat_grant(game, source, card, stat)
