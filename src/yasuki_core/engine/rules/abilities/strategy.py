from yasuki_core.engine.rules import triggers
from yasuki_core.engine.rules.abilities.activation import defer_ability
from yasuki_core.engine.rules.abilities.registry import ability_for
from yasuki_core.engine.rules.effects import Discard
from yasuki_core.engine.rules.gold.cost import effective_gold_cost
from yasuki_core.engine.rules.gold.payment import payment_request
from yasuki_core.engine.rules.state import GameState
from yasuki_core.engine.rules.work import DiscardPlayed, ResolveStrategy
from yasuki_core.engine.table import ZoneKey, ZoneRole


def play_strategy(game: GameState, card_id: str, ability_key: str | None = None) -> None:
    """Announce a Strategy: defer its resolution, then pause for its Gold Cost.

    The card stays in hand until the payment is answered, so backing out of the payment leaves it
    there — the unwind truncates the tape to before the announcement and replays, and a card that
    never moved needs nothing put back.
    """
    card = game.table.cards_by_id[card_id]
    seat = card.owner
    game.stack.append(ResolveStrategy(card_id, ability_key))
    game.pending = payment_request(
        game, seat, effective_gold_cost(game, card), card.name, target=card
    )


def resolve_strategy(game: GameState, card_id: str, ability_key: str | None = None) -> None:
    """Resolve a paid-for Strategy: its ability against its target, and then its discard.

    The discard is stacked *under* the ability's own work so it runs after it, whether the ability
    hits every target at once or pauses to be pointed at one.
    """
    card = game.table.cards_by_id[card_id]
    ability = ability_for(card, ability_key)
    if ability is None:
        raise ValueError(f"{card_id} has no ability to resolve")
    game.stack.append(DiscardPlayed(card_id))
    defer_ability(game, card, ability)


def discard_played(game: GameState, card_id: str) -> None:
    """Discard a card whose play has finished, unless it has already left the hand.

    Step F discards the played card "unless it is now in play" (CR, Action Sequence) — a Terrain, a
    Kata or an Edict reaches the board as the thing its own text does. A card that banished itself has
    left by another road, and discarding it would drag it back out of the pile it chose, so the
    test is whether it is still in hand rather than whether it reached the board.
    """
    card = game.table.cards_by_id[card_id]
    if card not in game.table.zones[ZoneKey(card.owner, ZoneRole.HAND)].cards:
        return
    triggers.resolve_effects(game, [Discard(card_id, card.owner)])
