from yasuki_core.engine.players import PlayerId
from yasuki_core.engine.rules.abilities.costs import no_cost
from yasuki_core.engine.rules.abilities.model import Ability, CardLocation
from yasuki_core.engine.rules.abilities.registry import register_ability
from yasuki_core.engine.rules.board.queries import (
    has_keyword,
    owned_personalities,
    personalities_in_play,
)
from yasuki_core.engine.rules.effects import Bow, Choose, Effect
from yasuki_core.engine.rules.legality import location_permits
from yasuki_core.engine.rules.state import GameState
from yasuki_core.engine.rules.triggers import choice_resolver
from yasuki_core.engine.rules.units.membership import attachments_of
from yasuki_core.engine.rules.vocabulary import keywords
from yasuki_core.engine.rules.vocabulary.actions import ActionTiming
from yasuki_core.game_pieces.cards import L5RCard


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
