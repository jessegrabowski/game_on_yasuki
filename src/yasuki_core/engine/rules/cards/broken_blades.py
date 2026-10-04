from yasuki_core.engine.players import PlayerId
from yasuki_core.engine.rules.abilities.costs import no_cost
from yasuki_core.engine.rules.abilities.model import Ability, CardLocation, itself
from yasuki_core.engine.rules.abilities.registry import register_ability
from yasuki_core.engine.rules.board.queries import (
    has_keyword,
    opposed_units_in_battle,
    opposing_units_in_battle,
    owned_personalities,
    personalities_in_play,
    units_at,
)
from yasuki_core.engine.rules.effects import (
    Bow,
    Choose,
    Destroy,
    Effect,
    Evaluate,
    Move,
    Simultaneously,
    Unpayable,
)
from yasuki_core.engine.rules.legality import location_permits
from yasuki_core.engine.rules.stats.card_values import effective_force
from yasuki_core.engine.rules.state import GameState
from yasuki_core.engine.rules.triggers import choice_resolver
from yasuki_core.engine.rules.units.membership import attachments_of
from yasuki_core.engine.rules.vocabulary import keywords
from yasuki_core.engine.rules.vocabulary.actions import ActionTiming
from yasuki_core.engine.table import Location, location_of
from yasuki_core.game_pieces.cards import L5RCard


# --- Overwhelmed ---

OVERWHELMED_MOVED = 2


def _overwhelmed_highest(game: GameState, card_ids: tuple[str, ...]) -> tuple[str, ...]:
    """The cards among ``card_ids`` with the highest Force, ties included."""
    forces = {
        card_id: effective_force(game, game.table.cards_by_id[card_id]) for card_id in card_ids
    }
    highest = max(forces.values(), default=None)
    return tuple(card_id for card_id, force in forces.items() if force == highest)


def _overwhelmed_performers(game: GameState, seat: PlayerId) -> tuple[str, ...]:
    """Your unbowed Personalities at the current battlefield with the highest Force of all you
    control there."""
    highest = _overwhelmed_highest(game, opposed_units_in_battle(game, seat))
    return tuple(card_id for card_id in highest if not game.table.cards_by_id[card_id].bowed)


def _overwhelmed_cost(game: GameState, source: L5RCard) -> list[Effect]:
    """Destroy the performing Personality, the seat picking among ties. The seat destroys it, so
    a Yu it carries does not resolve (ShE datasheet, The Yu Trait)."""
    performers = _overwhelmed_performers(game, source.owner)
    if not performers:
        return [Unpayable(f"{source.owner.name} has no unbowed Personality with the highest Force")]
    if len(performers) == 1:
        return [Destroy(performers[0], source.owner)]
    return [Choose(source.owner, performers, 1, 1, "overwhelmed_performer", source.id)]


@choice_resolver(
    "overwhelmed_performer", prompt="Overwhelmed: choose your performing Personality to destroy"
)
def _resolve_overwhelmed_performer(
    game: GameState, source_id: str, chosen: tuple[str, ...], seat: PlayerId
) -> list[Effect]:
    return [Destroy(chosen[0], seat)]


def _overwhelmed_targets(game: GameState, source: L5RCard) -> list[str]:
    """The Strategy itself, once you have a Personality to perform it and an enemy army stands at
    the battlefield."""
    if not _overwhelmed_performers(game, source.owner):
        return []
    return itself(game, source)


def _overwhelmed_effects(game: GameState, source: L5RCard, target: L5RCard) -> list[Effect]:
    """The enemy leader may move home exactly two units, or decline. An army too small for that
    leaves him nothing to choose."""
    army = opposing_units_in_battle(game, source.owner)
    if not army:
        return []
    leader = game.table.cards_by_id[army[0]].owner
    if len(army) < OVERWHELMED_MOVED:
        return _overwhelmed_destroys(game, source.id, leader)
    moved = OVERWHELMED_MOVED
    resolver = "overwhelmed_units"
    return [Choose(leader, army, moved, moved, resolver, source.id, declinable=True)]


@choice_resolver(
    "overwhelmed_units", prompt="Overwhelmed: choose two units to move home, or decline"
)
def _resolve_overwhelmed_units(
    game: GameState, source_id: str, chosen: tuple[str, ...], seat: PlayerId
) -> list[Effect]:
    """Move both home, then read whether both actually went: "If he did not" follows what
    happened, so a move something prevents leaves the destruction to come."""
    if not chosen:
        return _overwhelmed_destroys(game, source_id, seat)
    home = Location.home(seat)
    return [
        Simultaneously(tuple(Move(card_id, home) for card_id in chosen)),
        Evaluate("overwhelmed_moved", source_id, seat, chosen),
    ]


@choice_resolver("overwhelmed_moved")
def _resolve_overwhelmed_moved(
    game: GameState, source_id: str, chosen: tuple[str, ...], seat: PlayerId
) -> list[Effect]:
    home = Location.home(seat)
    if all(_overwhelmed_is_at(game, card_id, home) for card_id in chosen):
        return []
    return _overwhelmed_destroys(game, source_id, seat)


def _overwhelmed_is_at(game: GameState, card_id: str, where: Location) -> bool:
    card = game.table.cards_by_id.get(card_id)
    return card is not None and location_of(game.table, card) == where


def _overwhelmed_army(game: GameState, leader: PlayerId) -> tuple[str, ...]:
    """The enemy leader's units at the current battlefield."""
    return tuple(card.id for card in units_at(game, game.attack.current, leader))


def _overwhelmed_destroys(game: GameState, strategy_id: str, leader: PlayerId) -> list[Effect]:
    """The enemy leader targets and destroys a Personality in his army with the highest Force, as
    an effect of the action of the Strategy's player, whose seat is the destruction's cause."""
    highest = _overwhelmed_highest(game, _overwhelmed_army(game, leader))
    if not highest:
        return []
    if len(highest) == 1:
        return [Destroy(highest[0], game.table.cards_by_id[strategy_id].owner)]
    return [Choose(leader, highest, 1, 1, "overwhelmed_destroy", strategy_id)]


@choice_resolver(
    "overwhelmed_destroy",
    prompt="Overwhelmed: choose a Personality in your army with the highest Force to destroy",
)
def _resolve_overwhelmed_destroy(
    game: GameState, source_id: str, chosen: tuple[str, ...], seat: PlayerId
) -> list[Effect]:
    return [Destroy(chosen[0], game.table.cards_by_id[source_id].owner)]


register_ability(
    "overwhelmed",
    Ability(
        timings=(ActionTiming.BATTLE,),
        cost=_overwhelmed_cost,
        targets=_overwhelmed_targets,
        hits_every_target=True,
        effects=_overwhelmed_effects,
        located_at=(CardLocation.HAND,),
    ),
)


# --- Palm Strike ---


def _palm_strike_unarmed(game: GameState, card: L5RCard) -> bool:
    return not any(
        has_keyword(game, attached, keywords.WEAPON) for attached in attachments_of(game, card)
    )


def _palm_strike_enemies(game: GameState, seat: PlayerId) -> tuple[str, ...]:
    """The enemy Personalities without a Weapon that the action may target where they stand."""
    return tuple(
        card.id
        for card in personalities_in_play(game)
        if card.owner is not seat
        and _palm_strike_unarmed(game, card)
        and location_permits(game, card)
    )


def _palm_strike_targets(game: GameState, source: L5RCard) -> list[str]:
    """Your unbowed Monks without a Weapon, once there is an enemy Personality to bow."""
    if not _palm_strike_enemies(game, source.owner):
        return []
    return [
        card.id
        for card in owned_personalities(game, source.owner)
        if not card.bowed
        and has_keyword(game, card, keywords.MONK)
        and _palm_strike_unarmed(game, card)
    ]


def _palm_strike_effects(game: GameState, source: L5RCard, target: L5RCard) -> list[Effect]:
    """The Monk is the performer and does nothing more. The enemy is the second target."""
    enemies = _palm_strike_enemies(game, source.owner)
    return [Choose(source.owner, enemies, 1, 1, "palm_strike", source.id)]


@choice_resolver("palm_strike", prompt="Bow a target enemy Personality without a Weapon")
def _resolve_palm_strike(
    game: GameState, source_id: str, chosen: tuple[str, ...], seat: PlayerId
) -> list[Effect]:
    return [Bow(chosen[0])]


register_ability(
    "palm_strike",
    Ability(
        timings=(ActionTiming.BATTLE,),
        keywords=frozenset({keywords.KIHO}),
        cost=no_cost,
        targets=_palm_strike_targets,
        targeting_message="your unbowed Monk without a Weapon",
        effects=_palm_strike_effects,
        located_at=(CardLocation.HAND,),
    ),
)
