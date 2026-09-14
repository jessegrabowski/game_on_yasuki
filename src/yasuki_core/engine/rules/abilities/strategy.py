from dataclasses import dataclass

from yasuki_core.engine.rules import triggers
from yasuki_core.engine.rules.abilities.activation import defer_ability
from yasuki_core.engine.rules.abilities.registry import ability_for
from yasuki_core.engine.rules.effects import ApplyEffects, Discard, Effect
from yasuki_core.engine.rules.gold.cost import effective_gold_cost
from yasuki_core.engine.rules.gold.payment import payment_request
from yasuki_core.engine.rules.state import GameState
from yasuki_core.engine.table import ZoneKey, ZoneRole
from yasuki_core.game_pieces.cards import L5RCard


@dataclass(frozen=True, slots=True)
class ResolveStrategy:
    """Resolve a played Strategy once its Gold Cost is paid: its ability, then its discard.

    Deferred behind the payment the way a Recruit is, so a payment that pauses for a decision or is
    backed out of settles before the card does anything.

    Attributes
    ----------
    card_id : str
        The Strategy being played, still in hand until it resolves.
    ability_key : str, optional
        Names the ability among the several the card prints, so the one announced is the one
        that resolves. Default None, the card's only ability.
    """

    card_id: str
    ability_key: str | None = None

    def resume(self, game: GameState) -> None:
        resolve_strategy(game, self.card_id, self.ability_key)


def play_strategy(game: GameState, card_id: str, ability_key: str | None = None) -> None:
    """Announce a Strategy: defer its resolution, then pause for its Gold Cost.

    The card stays in hand until the payment is answered, so backing out of the payment leaves it
    there. The unwind truncates the tape to before the announcement and replays, and a card that
    never moved needs nothing put back.
    """
    card = game.table.cards_by_id[card_id]
    seat = card.owner
    game.stack.append(ResolveStrategy(card_id, ability_key))
    game.pending = payment_request(
        game, seat, effective_gold_cost(game, card), card.name, target=card
    )


def play_strategy_with(game: GameState, card: L5RCard, effects: tuple[Effect, ...]) -> None:
    """Announce ``card`` for ``effects`` in place of its printed ability's: pause for its Gold
    Cost with its discard and those effects queued behind. How an Interrupt plays a Strategy,
    since what it does is decided against the effect it interrupts rather than against a target.
    """
    game.stack.append(DiscardPlayed(card.id))
    game.stack.append(ApplyEffects(effects))
    game.pending = payment_request(
        game, card.owner, effective_gold_cost(game, card), card.name, target=card
    )


@dataclass(frozen=True, slots=True)
class DiscardPlayed:
    """Discard a card that has finished resolving, unless it is now in play.

    A Strategy goes to its owner's Fate discard once its ability is done (CR, Action Sequence step
    F), so this is stacked under the ability's own work and runs after it. The exception is the
    card that put *itself* into play (a Terrain, a Kata, an Edict), which stays where its own text
    left it.

    Attributes
    ----------
    card_id : str
        The card to discard. Its owner is the cause, since playing a card is its owner's doing.
    """

    card_id: str

    def resume(self, game: GameState) -> None:
        discard_played(game, self.card_id)


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

    Step F discards the played card "unless it is now in play" (CR, Action Sequence). A Terrain, a
    Kata or an Edict reaches the board as the thing its own text does. A card that banished itself
    has left by another road, and discarding it would drag it back out of the pile it chose, so the
    test is whether it is still in hand rather than whether it reached the board.
    """
    card = game.table.cards_by_id[card_id]
    if card not in game.table.zones[ZoneKey(card.owner, ZoneRole.HAND)].cards:
        return
    triggers.resolve_effects(game, [Discard(card_id, card.owner)])
