from yasuki_core.engine.players import PlayerId
from yasuki_core.engine.rules.abilities.costs import no_cost, register_bow_waiver
from yasuki_core.engine.rules.abilities.model import Ability, CardLocation
from yasuki_core.engine.rules.abilities.registry import register_ability
from yasuki_core.engine.rules.board.queries import personalities_in_play
from yasuki_core.engine.rules.effects import Choose, Destroy, Effect, Move
from yasuki_core.engine.rules.stats.attachment_grants import attachment_grant
from yasuki_core.engine.rules.triggers import choice_resolver
from yasuki_core.engine.rules.units.membership import attachments_of
from yasuki_core.engine.rules.vocabulary.actions import ActionTiming
from yasuki_core.engine.rules.vocabulary.modifiers import Stat
from yasuki_core.engine.rules.state import GameState
from yasuki_core.engine.table import Location
from yasuki_core.game_pieces.cards import L5RCard


# --- Rout ---


def _rout_targets(game: GameState, source: L5RCard) -> list[str]:
    """Every Personality on the board, each naming his unit: a unit is a Personality and the cards
    attached to him (CR, Unit), and the card names no side."""
    return [card.id for card in personalities_in_play(game)]


def _rout_effects(game: GameState, source: L5RCard, target: L5RCard) -> list[Effect]:
    """Send the unit home, then destroy one of its attachments.

    Moving home keeps the unit together, so the attachments read here are still attached when the
    choice resolves. The card names no chooser, so the seat playing it makes the choice, and "if
    any" is the whole of the clause when the unit carries nothing.
    """
    effects: list[Effect] = [Move(target.id, Location.home(target.owner))]
    attached = attachments_of(game, target)
    if attached:
        candidates = tuple(card.id for card in attached)
        effects.append(Choose(source.owner, candidates, 1, 1, "rout", source.id))
    return effects


@choice_resolver("rout", prompt="Destroy one of the unit's attachments")
def _resolve_rout(
    game: GameState, source_id: str, chosen: tuple[str, ...], seat: PlayerId
) -> list[Effect]:
    return [Destroy(chosen[0], seat)]


register_ability(
    "rout",
    Ability(
        timings=(ActionTiming.BATTLE,),
        label="Battle: move a target unit home and destroy one of its attachments",
        cost=no_cost,
        targets=_rout_targets,
        effects=_rout_effects,
        located_at=(CardLocation.HAND,),
    ),
)


# --- Shadowlands Ambassador ---


@attachment_grant("shadowlands_ambassador")
def _shadowlands_ambassador_attachment_grant(
    game: GameState, card: L5RCard, host: L5RCard
) -> dict[Stat, int]:
    """This Personality has -1PH. The Force 2 and the -1 Chi are printed on the card."""
    return {Stat.PERSONAL_HONOR: -1}


# Once a turn, his Personality may ignore the cost of bowing to pay for one of their own abilities.
register_bow_waiver("shadowlands_ambassador")
