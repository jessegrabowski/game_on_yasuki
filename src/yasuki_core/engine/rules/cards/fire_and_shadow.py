from yasuki_core.engine.players import PlayerId
from yasuki_core.engine.rules.abilities.costs import no_cost
from yasuki_core.engine.rules.abilities.model import Ability, CardLocation, itself
from yasuki_core.engine.rules.abilities.registry import register_ability
from yasuki_core.engine.rules.board.queries import units_at
from yasuki_core.engine.rules.board.seats import seat_named
from yasuki_core.engine.rules.effects import AskOption, Choose, Effect, Evaluate, Move, To
from yasuki_core.engine.rules.state import GameState
from yasuki_core.engine.rules.stats.card_values import effective_chi
from yasuki_core.engine.rules.triggers import choice_resolver
from yasuki_core.engine.rules.vocabulary.actions import ActionTiming
from yasuki_core.engine.table import Location
from yasuki_core.game_pieces.cards import L5RCard


# --- Defeat the Reserves ---


def _defeat_the_reserves_effects(game: GameState, source: L5RCard, target: L5RCard) -> list[Effect]:
    names = tuple(info.name for info in game.table.seats.values())
    question = "Defeat the Reserves: target a player"
    return [AskOption(source.owner, names, question, "defeat_the_reserves_player", source.id)]


@choice_resolver("defeat_the_reserves_player")
def _resolve_defeat_the_reserves_player(
    game: GameState, source_id: str, chosen: tuple[str, ...], seat: PlayerId
) -> list[Effect]:
    return [Evaluate("defeat_the_reserves_move", source_id, seat_named(game, chosen[0]))]


@choice_resolver("defeat_the_reserves_move")
def _resolve_defeat_the_reserves_move(
    game: GameState, source_id: str, chosen: tuple[str, ...], seat: PlayerId
) -> list[Effect]:
    """While ``seat`` has more units at the current battlefield than the highest Chi among its
    Personalities there, it targets one of those units to move home."""
    attack = game.attack
    if attack is None or attack.current is None:
        return []
    units = units_at(game, attack.current, seat)
    if len(units) <= max((effective_chi(game, unit) for unit in units), default=0):
        return []
    candidates = tuple(unit.id for unit in units)
    return [Choose(seat, candidates, 1, 1, "defeat_the_reserves_home", source_id)]


@choice_resolver(
    "defeat_the_reserves_home", prompt="Defeat the Reserves: move one of your units home"
)
def _resolve_defeat_the_reserves_home(
    game: GameState, source_id: str, chosen: tuple[str, ...], seat: PlayerId
) -> list[Effect]:
    """Move the unit home, and ask again only if it moved: a unit that cannot move ends the
    repetition."""
    again = Evaluate("defeat_the_reserves_move", source_id, seat)
    return [To(Move(chosen[0], Location.home(seat)), (again,))]


register_ability(
    "defeat_the_reserves",
    Ability(
        timings=(ActionTiming.BATTLE,),
        cost=no_cost,
        targets=itself,
        effects=_defeat_the_reserves_effects,
        hits_every_target=True,
        located_at=(CardLocation.HAND,),
    ),
)
