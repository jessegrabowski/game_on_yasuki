from yasuki_core.engine.rules.abilities.model import Ability
from yasuki_core.engine.rules.abilities.registry import (
    ability_for,
    is_printed_ability,
    recruit_timing_of,
)
from yasuki_core.engine.rules.state import GameState
from yasuki_core.engine.rules.turn.structure import ActionRound, RoundKind
from yasuki_core.engine.rules.vocabulary.actions import (
    ACTION_TIMINGS,
    Action,
    ActivateAbility,
    PlayInterrupt,
    PlayStrategy,
    Recruit,
)
from yasuki_core.game_pieces.prints import RulebookPrint


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


def is_printed_action(game: GameState, action: Action) -> bool:
    """Whether ``action`` is a printed action from a card: an ability the card's own text carries,
    or an Interrupt played from a card rather than from the rulebook (CR, Printed; CR, From)."""
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
        case PlayInterrupt(card_id=card_id):
            card = game.table.cards_by_id.get(card_id)
            return card is not None and not isinstance(card.printed, RulebookPrint)
        case _:
            return False


def action_is_unstoppable(game: GameState) -> bool:
    """Whether the action now resolving is Unstoppable: from an ability printing the modifier
    (ShE datasheet, Unstoppable). A rulebook action never is."""
    ability = resolving_ability(game)
    return ability is not None and ability.unstoppable


def action_keywords(game: GameState) -> frozenset[str]:
    """The ability keywords of the action now resolving, such as Political, or none outside one.

    A card's ability carries the keywords its registration declares, and so does a rulebook ability
    on a proxy, so Lobby is Political. A rulebook action carries what the arc's ruleset says it is
    designated.
    """
    match game.action:
        case ActivateAbility() | PlayStrategy():
            ability = resolving_ability(game)
            return frozenset() if ability is None else ability.keywords
        case Recruit(card_id=card_id):
            added = recruit_timing_of(game, card_id)
            as_rulebook = ACTION_TIMINGS[Recruit] in game.round.timings.active
            return frozenset() if added is None or as_rulebook else added.keywords
        case _:
            return frozenset()
