from yasuki_core.engine.rules.abilities.costs import bow_cost, no_cost
from yasuki_core.engine.rules.abilities.model import Ability, CardLocation
from yasuki_core.engine.rules.abilities.registry import register_ability
from yasuki_core.engine.rules.vocabulary.actions import ActionTiming
from yasuki_core.engine.rules.effects import DestroyProvince, Dishonor, DrawCard, Effect
from yasuki_core.engine.rules.board.queries import (
    has_keyword,
    owned_personalities,
    personalities_in_play,
    province_key_holding,
)
from yasuki_core.engine.rules.vocabulary import keywords
from yasuki_core.engine.rules.state import GameState
from yasuki_core.game_pieces.cards import L5RCard


# --- Harsh Choices ---


def _harsh_choices_targets(game: GameState, card: L5RCard) -> list[str]:
    """The Event itself. It names no target, and it acts on the Province it is sitting in."""
    return [card.id]


def _harsh_choices_effects(game: GameState, source: L5RCard, target: L5RCard) -> list[Effect]:
    """Destroy the Province the Event sits in, then draw three. Destroying it discards the
    Province's contents face-up, so the Event spends itself in the same stroke and needs no
    discard of its own.
    """
    province = province_key_holding(game, source.owner, source.id)
    if province is None:
        return []
    return [
        DestroyProvince(source.owner, province),
        *(DrawCard(source.owner) for _ in range(3)),
    ]


register_ability(
    "harsh_choices",
    Ability(
        timings=(ActionTiming.OPEN,),
        cost=no_cost,
        targets=_harsh_choices_targets,
        effects=_harsh_choices_effects,
        hits_every_target=True,
        located_at=(CardLocation.PROVINCE,),
    ),
)


# --- Slanderer ---


def _slanderer_targets(game: GameState, source: L5RCard) -> list[str]:
    """Every Personality, while the controller has a Courtier or Magistrate: "If you control a
    Courtier or Magistrate" is the whole condition, and an ability with nobody it may dishonor
    is not offered."""
    if not any(
        has_keyword(game, card, keywords.COURTIER) or has_keyword(game, card, keywords.MAGISTRATE)
        for card in owned_personalities(game, source.owner)
    ):
        return []
    return [card.id for card in personalities_in_play(game)]


def _slanderer_effects(game: GameState, source: L5RCard, target: L5RCard) -> list[Effect]:
    return [Dishonor(target.id, source.owner)]


register_ability(
    "slanderer",
    Ability(
        timings=(ActionTiming.OPEN,),
        keywords=frozenset({keywords.POLITICAL}),
        cost=bow_cost,
        targets=_slanderer_targets,
        targeting_message="a Personality",
        effects=_slanderer_effects,
    ),
)
