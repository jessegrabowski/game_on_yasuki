from yasuki_core.engine.players import PlayerId
from yasuki_core.engine.rules.rulebook.lobby import lobby_bar
from yasuki_core.engine.rules.abilities.costs import bow_cost
from yasuki_core.engine.rules.abilities.model import Ability, itself
from yasuki_core.engine.rules.abilities.registry import EntryState, entry_state, register_ability
from yasuki_core.engine.rules.vocabulary.actions import ActionTiming
from yasuki_core.engine.rules.effects import Effect, GainHonor
from yasuki_core.engine.rules.state import GameState
from yasuki_core.game_pieces.cards import L5RCard


# --- Poorly Placed Garden ---


@entry_state("poorly_placed_garden")
def _poorly_placed_garden_entry_state(game: GameState, card: L5RCard) -> EntryState:
    return EntryState(bowed=False)


def _poorly_placed_garden_targets(game: GameState, source: L5RCard) -> list[str]:
    """The Holding itself while it is its owner's turn. An Open designator lets any seat act, so
    the printed "If it is your turn" has to close the ability on the other seats' turns."""
    return itself(game, source) if game.active is source.owner else []


def _poorly_placed_garden_effects(
    game: GameState, source: L5RCard, target: L5RCard
) -> list[Effect]:
    return [GainHonor(source.owner, 2)]


register_ability(
    "poorly_placed_garden",
    Ability(
        timings=(ActionTiming.OPEN,),
        cost=bow_cost,
        targets=_poorly_placed_garden_targets,
        effects=_poorly_placed_garden_effects,
        hits_every_target=True,
    ),
)


# --- Wasp Sensei ---


@lobby_bar("wasp_sensei")
def _wasp_sensei_lobby_bar(game: GameState, card: L5RCard, seat: PlayerId) -> bool:
    """ "You may not Lobby." Its own controller, and nobody else. Its other two lines need no
    handler here."""
    return seat is card.owner
