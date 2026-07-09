from collections.abc import Callable
from dataclasses import dataclass

from yasuki_core.engine.players import PlayerId
from yasuki_core.engine.rules.modifiers import Duration, Stat
from yasuki_core.engine.rules.state import GameState, Phase
from yasuki_core.engine.rules.triggers import Effect, GrantModifier
from yasuki_core.game_pieces.cards import L5RCard
from yasuki_core.game_pieces.dynasty import DynastyHolding


@dataclass(frozen=True, slots=True)
class Ability:
    """An activated ability on an in-play card, paid for by bowing that card.

    Attributes
    ----------
    phase : Phase
        The phase the ability may be used in.
    label : str
        A short human description for the activation menu.
    targets : callable
        Maps ``(game, source_card)`` to the ids of the cards the ability may target — empty when
        none are legal, which also means the ability can't be offered.
    effects : callable
        Maps ``(source_card, target_card)`` to the effects the ability emits once its target is
        chosen.
    """

    phase: Phase
    label: str
    targets: Callable[[GameState, L5RCard], list[str]]
    effects: Callable[[L5RCard, L5RCard], list[Effect]]


def ability_for(card: L5RCard) -> Ability | None:
    """The activated ability registered for ``card``'s printed id, or None."""
    return _ABILITIES.get(card.printed_id)


def activatable(game: GameState, seat: PlayerId, phase: Phase) -> list[L5RCard]:
    """The in-play cards ``seat`` may activate an ability on right now: controlled, unbowed, their
    ability legal in ``phase``, and with at least one legal target."""
    ready: list[L5RCard] = []
    for card in game.table.battlefield.cards:
        if card.owner is not seat or card.bowed:
            continue
        ability = _ABILITIES.get(card.printed_id)
        if ability is None or ability.phase is not phase:
            continue
        if ability.targets(game, card):
            ready.append(card)
    return ready


def _owned_farms(game: GameState, card: L5RCard) -> list[str]:
    return [
        held.id
        for held in game.table.battlefield.cards
        if held.owner is card.owner and isinstance(held, DynastyHolding) and "Farm" in held.keywords
    ]


def _millet_farm_effects(source: L5RCard, target: L5RCard) -> list[Effect]:
    return [
        GrantModifier(source.id, target.id, Stat.GOLD_PRODUCTION, 2, Duration.UNTIL_END_OF_TURN)
    ]


# Per-card activated abilities, registered on import.
_ABILITIES: dict[str, Ability] = {
    "millet_farm": Ability(
        phase=Phase.ACTION,
        label="Bow: give a Farm +2 Gold Production",
        targets=_owned_farms,
        effects=_millet_farm_effects,
    ),
}
