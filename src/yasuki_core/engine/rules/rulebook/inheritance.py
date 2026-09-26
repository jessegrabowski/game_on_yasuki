from typing import TypeGuard

from yasuki_core.engine.rules.abilities.model import Ability, CardLocation
from yasuki_core.engine.rules.abilities.registry import register_ability
from yasuki_core.engine.rules.board.queries import owned_holdings
from yasuki_core.engine.rules.board.seats import seat_stronghold
from yasuki_core.engine.rules.effects import (
    Effect,
    GrantModifier,
    SpendSeatOncePerGame,
    TurnOver,
    Unpayable,
)
from yasuki_core.engine.rules.state import GameState, seat_used_this_game
from yasuki_core.engine.rules.vocabulary.actions import Action, ActionTiming, ActivateAbility
from yasuki_core.engine.rules.vocabulary.modifiers import Duration, Stat
from yasuki_core.game_pieces.cards import L5RCard
from yasuki_core.game_pieces.constants import INHERITANCE_PROXY_ID, Side
from yasuki_core.game_pieces.prints import RulebookPrint

INHERITANCE = "inheritance"

# The Gold Production the Inheritance ability grants the Holding it targets (ShE).
INHERITANCE_PRODUCTION = 3

# The print each seat's Inheritance proxy presents. ``rulebook/proxies.py`` deals it.
INHERITANCE_PROXY = RulebookPrint(
    name="The Inheritance Rule",
    side=Side.FATE,
    printed_id=INHERITANCE_PROXY_ID,
    card_type="Other",
)


def is_inheritance(action: Action) -> TypeGuard[ActivateAbility]:
    """Whether ``action`` takes the Inheritance ability on a seat's Inheritance proxy."""
    return isinstance(action, ActivateAbility) and action.ability_key == INHERITANCE


def _inheritance_cost(game: GameState, source: L5RCard) -> list[Effect]:
    """The once-per-game use and the Stronghold's turn-over, which cannot be paid by a Stronghold
    with no back face."""
    stronghold = seat_stronghold(game, source.owner)
    if stronghold is None:
        return [Unpayable(f"{source.owner.name} has no Stronghold to turn over")]
    return [SpendSeatOncePerGame(seat=source.owner, tag=INHERITANCE), TurnOver(stronghold.id)]


def _inheritance_targets(game: GameState, source: L5RCard) -> list[str]:
    """The seat's Holdings, while it did not go first and has not spent the ability."""
    seat = source.owner
    if seat is game.first_player or seat_used_this_game(game, seat, INHERITANCE):
        return []
    return [card.id for card in owned_holdings(game, seat)]


def _inheritance_effects(game: GameState, source: L5RCard, target: L5RCard) -> list[Effect]:
    return [
        GrantModifier(
            source_id=source.id,
            target_id=target.id,
            stat=Stat.GOLD_PRODUCTION,
            amount=INHERITANCE_PRODUCTION,
            duration=Duration.UNTIL_END_OF_TURN,
        )
    ]


register_ability(
    INHERITANCE_PROXY_ID,
    Ability(
        timings=(ActionTiming.DYNASTY,),
        label=(
            "Dynasty: Turn your Stronghold over to give your target Holding +3GP. This may not be "
            "prevented."
        ),
        cost=_inheritance_cost,
        targets=_inheritance_targets,
        effects=_inheritance_effects,
        targeting_message="your Holding",
        key=INHERITANCE,
        located_at=(CardLocation.RULEBOOK,),
        from_rulebook=True,
    ),
)
