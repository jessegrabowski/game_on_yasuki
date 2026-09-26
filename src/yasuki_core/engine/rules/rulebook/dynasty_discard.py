from typing import TypeGuard

from yasuki_core.engine.rules.abilities.costs import no_cost
from yasuki_core.engine.rules.abilities.model import Ability, CardLocation, itself
from yasuki_core.engine.rules.abilities.registry import register_location_ability
from yasuki_core.engine.rules.board.queries import province_key_of
from yasuki_core.engine.rules.effects import Discard, Effect, RefillProvince, Then
from yasuki_core.engine.rules.state import GameState
from yasuki_core.engine.rules.vocabulary.actions import Action, ActionTiming, ActivateAbility
from yasuki_core.game_pieces.cards import L5RCard

DYNASTY_DISCARD = "dynasty_discard"


def is_dynasty_discard(action: Action) -> TypeGuard[ActivateAbility]:
    """Whether ``action`` takes the Dynasty Discard ability on a Province card."""
    return isinstance(action, ActivateAbility) and action.ability_key == DYNASTY_DISCARD


def _discard_and_refill(game: GameState, source: L5RCard, target: L5RCard) -> list[Effect]:
    vacated = province_key_of(game, source.owner, source.id)
    return [Discard(source.id, source.owner), Then((RefillProvince(vacated),))]


# Repeatable Dynasty, at no cost: discard a face-up Province card of any type and refill the
# Province face-down behind the reactions to the discard. A face-down card is not offered,
# because its owner has not seen it.
register_location_ability(
    Ability(
        timings=(ActionTiming.DYNASTY,),
        label="Discard from province",
        cost=no_cost,
        targets=itself,
        effects=_discard_and_refill,
        hits_every_target=True,
        key=DYNASTY_DISCARD,
        repeatable=True,
        located_at=(CardLocation.PROVINCE,),
        from_rulebook=True,
    )
)
