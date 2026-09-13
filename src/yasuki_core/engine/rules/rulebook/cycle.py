from yasuki_core.engine.players import PlayerId
from yasuki_core.engine.rules import triggers
from yasuki_core.engine.rules.board.queries import province_key_holding
from yasuki_core.engine.rules.effects import (
    Choose,
    Effect,
    MoveToDeck,
    RefillProvince,
    RevealProvinces,
    Then,
)
from yasuki_core.engine.rules.legality import cycle_candidates, cycle_key
from yasuki_core.engine.rules.state import GameState
from yasuki_core.engine.table import DeckKey
from yasuki_core.game_pieces.constants import Side


def cycle(game: GameState) -> None:
    """Announce the Cycle ability: claim its once-per-turn use and pause for the seat to pick which
    face-up Province cards go back. The move, refill and reveal follow once the picks are in."""
    seat = game.active
    game.use_once(cycle_key(seat, game.turn))
    candidates = tuple(card.id for card in cycle_candidates(game, seat))
    triggers.resolve_effects(game, [Choose(seat, candidates, 1, len(candidates), "cycle")])


@triggers.choice_resolver(
    "cycle",
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
