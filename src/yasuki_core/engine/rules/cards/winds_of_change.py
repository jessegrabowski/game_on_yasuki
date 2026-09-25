from yasuki_core.engine.players import PlayerId
from yasuki_core.engine.rules.abilities.costs import no_cost
from yasuki_core.engine.rules.abilities.model import Ability, CardLocation
from yasuki_core.engine.rules.abilities.registry import register_ability
from yasuki_core.engine.rules.board.queries import controls_terrain_at
from yasuki_core.engine.rules.units.composition import in_a_unit
from yasuki_core.engine.rules.rulebook.favor_payment import favor_payer
from yasuki_core.engine.rules.rulebook.lobby import lobby_bar
from yasuki_core.engine.rules.abilities.idioms import register_event_entry
from yasuki_core.engine.rules.vocabulary.actions import ActionTiming
from yasuki_core.engine.rules.effects import Bow, Discard, Effect, Straighten
from yasuki_core.engine.rules.state import GameState
from yasuki_core.game_pieces.cards import L5RCard


# --- Commanding Favor ---


@favor_payer("commanding_favor")
def _commanding_favor_favor_payer(game: GameState, card: L5RCard) -> list[Effect] | None:
    """ "Interrupt: Discard this Event from play to pay the action's :favor: cost."

    Implemented as a payer priced at discarding itself rather than as the printed Interrupt. The
    printed timing cannot be honored: costs are paid at step B of the Action Sequence and Interrupts
    are played at D. It pays the cost outright rather than substituting for a discard, so it is
    offered to a seat that holds no Favor at all.
    """
    return [Discard(card.id, card.owner)]


register_event_entry("commanding_favor", timing=ActionTiming.DYNASTY)


# --- Miya Shoin ---


@lobby_bar("miya_shoin")
def _miya_shoin_lobby_bar(game: GameState, card: L5RCard, seat: PlayerId) -> bool:
    """ "Other players may not Lobby": everyone but his controller. The ability he grants them to
    take control of him has no handler yet."""
    return seat is not card.owner


# --- Well Prepared ---


def _well_prepared_targets(game: GameState, source: L5RCard) -> list[str]:
    """ "If you control a Terrain, target a card in a unit": any card in one, at any battlefield."""
    attack = game.attack
    if attack is None:
        return []
    controls_one = any(
        controls_terrain_at(game, source.owner, battlefield=index)
        for index in range(len(attack.battlefields))
    )
    if not controls_one:
        return []
    return [card.id for card in game.table.battlefield.cards if in_a_unit(game, card)]


def _well_prepared_effects(game: GameState, source: L5RCard, target: L5RCard) -> list[Effect]:
    """ "Bow or straighten the target." Only one of the two can change it, since a bowed card
    cannot bow and a standing one cannot straighten."""
    return [Straighten(target.id) if target.bowed else Bow(target.id)]


register_ability(
    "well_prepared",
    Ability(
        timings=(ActionTiming.BATTLE,),
        cost=no_cost,
        targets=_well_prepared_targets,
        targeting_message="a card in a unit",
        effects=_well_prepared_effects,
        located_at=(CardLocation.HAND,),
    ),
)
