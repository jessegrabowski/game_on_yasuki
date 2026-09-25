from yasuki_core import ruleset
from yasuki_core.engine.rules.abilities.model import Ability
from yasuki_core.engine.rules.abilities.registry import ability_for, recruit_timing_of
from yasuki_core.engine.rules.state import GameState
from yasuki_core.engine.rules.turn.structure import ActionRound, RoundKind
from yasuki_core.engine.rules.vocabulary.actions import (
    ACTION_TIMINGS,
    ActivateAbility,
    Lobby,
    PlayStrategy,
    Recruit,
    UseFavorAbility,
)


def action_round(game: GameState) -> ActionRound:
    """The round the action now resolving was taken in: the one beneath an open Interrupt step or
    Response Step, else the round that is open."""
    if game.round.kind in (RoundKind.INTERRUPT, RoundKind.RESPONSE) and game.round_stack:
        return game.round_stack[-1]
    return game.round


def resolving_ability(game: GameState) -> Ability | None:
    """The ability the action now resolving was taken from, or None for an action taken from none:
    a Recruit, a rulebook action, or no action at all."""
    match game.action:
        case (
            ActivateAbility(card_id=card_id, ability_key=key)
            | PlayStrategy(card_id=card_id, ability_key=key)
        ):
            card = game.table.cards_by_id.get(card_id)
            return None if card is None else ability_for(game, card, key)
        case _:
            return None


def action_is_unstoppable(game: GameState) -> bool:
    """Whether the action now resolving is Unstoppable: from an ability printing the modifier
    (ShE datasheet, Unstoppable). A rulebook action never is."""
    ability = resolving_ability(game)
    return ability is not None and ability.unstoppable


def action_keywords(game: GameState) -> frozenset[str]:
    """The ability keywords of the action now resolving, such as Political, or none outside one.

    A card's ability carries the keywords its registration declares. A rulebook action carries what
    the arc's ruleset says it is designated, so Lobby is Political under the ShE datasheet.
    """
    match game.action:
        case (
            ActivateAbility(card_id=card_id, ability_key=key)
            | PlayStrategy(card_id=card_id, ability_key=key)
        ):
            ability = resolving_ability(game)
            return frozenset() if ability is None else ability.keywords
        case Recruit(card_id=card_id):
            added = recruit_timing_of(game, card_id)
            as_rulebook = ACTION_TIMINGS[Recruit] in game.round.timings.active
            return frozenset() if added is None or as_rulebook else added.keywords
        case Lobby():
            return ruleset.ACTIVE.lobby_keywords
        case UseFavorAbility(key=key):
            return next(
                (a.keywords for a in ruleset.ACTIVE.favor_abilities if a.key == key), frozenset()
            )
        case _:
            return frozenset()
