from yasuki_core import ruleset
from yasuki_core.engine.rules.abilities.registry import ability_for, recruit_timing_of
from yasuki_core.engine.rules.state import GameState
from yasuki_core.engine.rules.vocabulary.actions import (
    ACTION_TIMINGS,
    ActivateAbility,
    Lobby,
    PlayStrategy,
    Recruit,
    UseFavorAbility,
)


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
            card = game.table.cards_by_id.get(card_id)
            return frozenset() if card is None else ability_for(card, key).keywords
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
