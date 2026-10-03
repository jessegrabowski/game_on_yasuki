from yasuki_core.engine.rules.abilities.model import Ability
from yasuki_core.engine.rules.abilities.registry import (
    ability_for,
    interrupt_for,
    is_printed_ability,
)
from yasuki_core.engine.rules.state import GameState
from yasuki_core.engine.rules.turn.structure import STEP_ROUNDS, ActionRound
from yasuki_core.engine.rules.vocabulary.actions import (
    Action,
    ActivateAbility,
    PlayInterrupt,
    PlayStrategy,
)
from yasuki_core.game_pieces.prints import RulebookPrint


def action_round(game: GameState) -> ActionRound:
    """The round the action now resolving was taken in: the one beneath an open Interrupt step or
    Response Step, else the round that is open."""
    if game.round.kind in STEP_ROUNDS and game.round_stack:
        return game.round_stack[-1]
    return game.round


def resolving_ability(game: GameState) -> Ability | None:
    """The ability the action now resolving was taken from, or None for an action taken from none:
    a rulebook action, or no action at all."""
    match game.action:
        case (
            ActivateAbility(card_id=card_id, ability_key=key)
            | PlayStrategy(card_id=card_id, ability_key=key)
        ):
            card = game.table.cards_by_id.get(card_id)
            return None if card is None else ability_for(game, card, key)
        case _:
            return None


def is_printed_action(game: GameState, action: Action) -> bool:
    """Whether ``action`` is a printed action from a card: an ability or an Interrupt the card's
    own text carries, as against a rulebook one such as a keyword's (CR, Printed; CR, From)."""
    match action:
        case (
            ActivateAbility(card_id=card_id, ability_key=key)
            | PlayStrategy(card_id=card_id, ability_key=key)
        ):
            card = game.table.cards_by_id.get(card_id)
            if card is None:
                return False
            ability = ability_for(game, card, key)
            return ability is not None and is_printed_ability(card, ability)
        case PlayInterrupt(card_id=card_id, interrupt_key=key):
            card = game.table.cards_by_id.get(card_id)
            if card is None or isinstance(card.printed, RulebookPrint):
                return False
            interrupt = interrupt_for(card, key)
            return interrupt is not None and interrupt.acts_from_its_card
        case _:
            return False


def action_is_unstoppable(game: GameState) -> bool:
    """Whether the action now resolving is Unstoppable: from an ability printing the modifier
    (ShE datasheet, Unstoppable). A rulebook action never is."""
    ability = resolving_ability(game)
    return ability is not None and ability.unstoppable


def action_keywords(game: GameState) -> frozenset[str]:
    """The ability keywords of the action now resolving, such as Political, or none outside one.

    A card's ability carries the keywords its registration declares, and so does a rulebook ability,
    so Lobby is Political.
    """
    match game.action:
        case ActivateAbility() | PlayStrategy():
            ability = resolving_ability(game)
            return frozenset() if ability is None else ability.keywords
        case _:
            return frozenset()
