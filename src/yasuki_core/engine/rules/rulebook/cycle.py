from typing import TypeGuard

from yasuki_core.engine.players import PlayerId
from yasuki_core.engine.rules import triggers
from yasuki_core.engine.rules.abilities.model import Ability, CardLocation, itself
from yasuki_core.engine.rules.abilities.registry import register_ability
from yasuki_core.engine.rules.board.queries import province_cards, province_key_holding
from yasuki_core.engine.rules.effects import (
    Choose,
    Effect,
    MoveToDeck,
    RefillProvince,
    RevealProvinces,
    SpendSeatOncePerTurn,
    Then,
)
from yasuki_core.engine.rules.state import GameState, seat_once_key
from yasuki_core.engine.rules.vocabulary.actions import Action, ActionTiming, ActivateAbility
from yasuki_core.engine.table import DeckKey
from yasuki_core.game_pieces.cards import L5RCard
from yasuki_core.game_pieces.constants import CYCLE_PROXY_ID, Side
from yasuki_core.game_pieces.prints import RulebookPrint

CYCLE = "cycle"

# The print each seat's Cycle proxy presents. ``rulebook/proxies.py`` deals it.
CYCLE_PROXY = RulebookPrint(
    name="Cycle", side=Side.FATE, printed_id=CYCLE_PROXY_ID, card_type="Other"
)


def is_cycle(action: Action) -> TypeGuard[ActivateAbility]:
    """Whether ``action`` takes the Cycle ability on a seat's Cycle proxy."""
    return isinstance(action, ActivateAbility) and action.ability_key == CYCLE


def is_first_turn(game: GameState, seat: PlayerId) -> bool:
    """Whether the current turn is ``seat``'s first. The turn counter advances while the active seat
    alternates, so the second player's first turn is turn 2."""
    return game.turn == (1 if seat is game.first_player else 2)


def cycle_candidates(game: GameState, seat: PlayerId) -> list[L5RCard]:
    """The cards ``seat`` may put on the bottom of its deck with Cycle: the face-up ones in its
    Provinces. A face-down card is not eligible, so a Province nobody has revealed stays where it
    is."""
    return [card for card in province_cards(game, seat) if card.face_up]


def _cycle_cost(game: GameState, source: L5RCard) -> list[Effect]:
    return [SpendSeatOncePerTurn(seat=source.owner, tag=CYCLE)]


def _cycle_targets(game: GameState, source: L5RCard) -> list[str]:
    """The proxy itself on the seat's first turn, while Cycle is unspent and a face-up Province
    card is there to put back. The rule is "one or more", so with none there is no Cycle to take."""
    seat = source.owner
    if not is_first_turn(game, seat) or game.has_used(seat_once_key(seat, CYCLE, game.turn)):
        return []
    return itself(game, source) if cycle_candidates(game, seat) else []


def _cycle_effects(game: GameState, source: L5RCard, target: L5RCard) -> list[Effect]:
    seat = source.owner
    candidates = tuple(card.id for card in cycle_candidates(game, seat))
    return [
        Choose(
            seat=seat,
            candidates=candidates,
            minimum=1,
            maximum=len(candidates),
            resolver=CYCLE,
            source_id=source.id,
        )
    ]


register_ability(
    CYCLE_PROXY_ID,
    Ability(
        timings=(ActionTiming.LIMITED,),
        label=(
            "Limited: If it is your first turn, choose one or more face-up cards in your "
            "Provinces. Put them on the bottom of your deck in any order. Then (after refilling "
            "Provinces), turn all cards in your Provinces face-up."
        ),
        cost=_cycle_cost,
        targets=_cycle_targets,
        effects=_cycle_effects,
        hits_every_target=True,
        key=CYCLE,
        located_at=(CardLocation.RULEBOOK,),
        from_rulebook=True,
    ),
)


@triggers.choice_resolver(
    CYCLE,
    prompt="Put face-up Province cards on the bottom of your deck (your last pick ends up lowest)",
)
def _cycle_put_on_bottom(
    game: GameState, source_id: str | None, chosen: tuple[str, ...], seat: PlayerId
) -> list[Effect]:
    """Put each chosen card on the bottom in pick order, then refill the Provinces they left and
    reveal them all.

    Each card goes under the one before it, in the order the rule gives the player, so the last pick
    ends up at the very bottom. The refill and the reveal are deferred together because the rule
    reveals *after* refilling, and both wait on the reactions to the cards leaving.
    """
    seat = game.table.cards_by_id[chosen[0]].owner
    # Read the Provinces before anything moves; afterwards none of them holds the card to find.
    vacated = [province_key_holding(game, seat, card_id) for card_id in chosen]
    deck = DeckKey(seat, Side.DYNASTY)
    put_back = [MoveToDeck(card_id, deck, from_bottom=0) for card_id in chosen]
    refills = tuple(RefillProvince(key) for key in vacated if key is not None)
    return [*put_back, Then((*refills, RevealProvinces(seat)))]
