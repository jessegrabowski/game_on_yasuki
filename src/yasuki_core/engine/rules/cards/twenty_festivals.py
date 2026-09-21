from yasuki_core.engine.rules.abilities.costs import no_cost
from yasuki_core.engine.rules.abilities.model import Ability, InvestAbility
from yasuki_core.engine.rules.abilities.registry import register_ability, register_invest
from yasuki_core.engine.rules.board.queries import has_keyword, opposed_units_in_battle, units_at
from yasuki_core.engine.rules.effects import AdjustCounter, Effect, GrantModifier, Straighten
from yasuki_core.engine.rules.stats.card_values import effective_personal_honor
from yasuki_core.engine.rules.state import GameState
from yasuki_core.engine.rules.units.membership import attachments_of
from yasuki_core.engine.rules.vocabulary import keywords
from yasuki_core.engine.rules.vocabulary.actions import ActionTiming
from yasuki_core.engine.rules.vocabulary.modifiers import Duration, Stat
from yasuki_core.game_pieces.cards import L5RCard
from yasuki_core.game_pieces.counters import WEALTH


# --- Questionable Market ---


def _questionable_market_invest(game: GameState, source: L5RCard, amount: int) -> list[Effect]:
    return [AdjustCounter(source.id, WEALTH, 2)]


register_invest(
    "questionable_market", InvestAbility(amounts=(2,), effect=_questionable_market_invest)
)


# --- The Grand Halls of the Lion ---

GRAND_HALLS_LABEL = (
    "Battle: Give your target opposed Samurai a Force bonus equal to his Personal Honor"
)


def _the_grand_halls_of_the_lion_targets(game: GameState, source: L5RCard) -> list[str]:
    return [
        card_id
        for card_id in opposed_units_in_battle(game, source.owner)
        if has_keyword(game, game.table.cards_by_id[card_id], keywords.SAMURAI)
    ]


def _the_grand_halls_of_the_lion_effects(
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
    "the_grand_halls_of_the_lion",
    Ability(
        timings=(ActionTiming.BATTLE,),
        label=GRAND_HALLS_LABEL,
        cost=no_cost,
        targets=_the_grand_halls_of_the_lion_targets,
        effects=_the_grand_halls_of_the_lion_effects,
    ),
)


# --- The Grand Halls of the Lion (back) ---

register_ability(
    "the_grand_halls_of_the_lion__back",
    Ability(
        timings=(ActionTiming.BATTLE,),
        label=f"Tireless {GRAND_HALLS_LABEL}",
        cost=no_cost,
        targets=_the_grand_halls_of_the_lion_targets,
        effects=_the_grand_halls_of_the_lion_effects,
        tireless=True,
    ),
)


# --- The Unassailable Fortress of the Crab ---


def _the_unassailable_fortress_of_the_crab_targets(game: GameState, source: L5RCard) -> list[str]:
    return list(opposed_units_in_battle(game, source.owner))


def _the_unassailable_fortress_of_the_crab_effects(
    game: GameState, source: L5RCard, target: L5RCard
) -> list[Effect]:
    """ "Straighten your target opposed Personality. Straighten his attachments if your army has
    fewer units than the opposing army." A unit is a Personality with his attachments (CR, Unit),
    so the armies are compared by Personalities."""
    attack = game.attack
    enemy = attack.attacker if source.owner is attack.defender else attack.defender
    own_army = units_at(game, attack.current, source.owner)
    enemy_army = units_at(game, attack.current, enemy)
    outnumbered = len(own_army) < len(enemy_army)
    effects: list[Effect] = [Straighten(target.id)]
    if outnumbered:
        effects.extend(Straighten(attached.id) for attached in attachments_of(game, target))
    return effects


register_ability(
    "the_unassailable_fortress_of_the_crab",
    Ability(
        timings=(ActionTiming.BATTLE,),
        label="Battle: Straighten your target opposed Personality, and his attachments if your "
        "army has fewer units than the opposing army",
        cost=no_cost,
        targets=_the_unassailable_fortress_of_the_crab_targets,
        effects=_the_unassailable_fortress_of_the_crab_effects,
    ),
)
