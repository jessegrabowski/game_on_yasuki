from dataclasses import dataclass

from yasuki_core.engine.rules import triggers
from yasuki_core.engine.rules.abilities.activation import defer_ability
from yasuki_core.engine.rules.abilities.registry import ability_for
from yasuki_core.engine.rules.battle.presence import record_terrain_played
from yasuki_core.engine.rules.effects import ApplyEffects, Banish, Discard, Effect
from yasuki_core.engine.rules.gold.discounts import card_purchase, discounted_gold_cost
from yasuki_core.engine.rules.gold.payment import RequestPayment, payment_request
from yasuki_core.engine.rules.rulebook.discipline import in_discard_pile, under_discipline
from yasuki_core.engine.rules.state import GameState
from yasuki_core.engine.rules.stats.keyword_grants import effective_keywords
from yasuki_core.engine.rules.vocabulary.work import Provenance
from yasuki_core.engine.rules.vocabulary import keywords
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
    disciplined : bool, optional
        Whether the card was played out of its owner's discard pile under Discipline. Default
        False.
    """

    card_id: str
    ability_key: str | None = None
    disciplined: bool = False

    def resume(self, game: GameState) -> None:
        resolve_strategy(game, self.card_id, self.ability_key, disciplined=self.disciplined)


def play_strategy(
    game: GameState, card_id: str, ability_key: str | None = None, *, disciplined: bool = False
) -> None:
    """Announce a Strategy: take it out of the hand, or out of the discard pile when it is played
    under Discipline, into its resolution area, settle the board that leaves, then ask for its Gold
    Cost with its resolution queued behind (CR, Resolution Area; CR, Discipline).

    The card stays in the zone it was played from until it resolves, so backing out of the payment
    leaves it there. The unwind truncates the tape to before the announcement and replays, and a
    card that never moved needs nothing put back.
    """
    card = game.table.cards_by_id[card_id]
    cost = strategy_cost(game, card, ability_key, disciplined=disciplined)
    game.announced_cards |= {card_id}
    game.stack.append(ResolveStrategy(card_id, ability_key, disciplined))
    game.stack.append(RequestPayment(card.owner, cost, card.name, card_id))
    triggers.enforce_state_based_actions(game)


def strategy_cost(
    game: GameState, card: L5RCard, ability_key: str | None = None, *, disciplined: bool = False
) -> int:
    """The Gold a seat pays to play ``card`` for the ability ``ability_key`` names: its Gold Cost,
    with its Discipline added when ``disciplined``, less the discounts its controller has on that
    action."""
    ability = ability_for(game, card, ability_key)
    if ability is None:
        purchase = card_purchase(game, card, plays_card=True)
    else:
        purchase = ability.purchase(game, card, plays_card=True)
    if disciplined:
        purchase = under_discipline(game, purchase)
    return discounted_gold_cost(game, purchase)


def play_strategy_with(
    game: GameState,
    card: L5RCard,
    effects: tuple[Effect, ...],
    provenance: Provenance,
    *,
    disciplined: bool = False,
) -> None:
    """Announce ``card`` for ``effects`` in place of its printed ability's: pause for its Gold
    Cost, unless it costs nothing, with its discard and those effects queued behind. How an
    Interrupt plays a Strategy, since what it does is decided against the effect it interrupts
    rather than against a target. ``provenance`` says whose action the effects are, and
    ``disciplined`` whether the card is played out of its discard pile under Discipline.
    """
    purchase = card_purchase(game, card, plays_card=True)
    if disciplined:
        purchase = under_discipline(game, purchase)
    cost = discounted_gold_cost(game, purchase)
    game.announced_cards |= {card.id}
    game.stack.append(DiscardPlayed(card.id, disciplined))
    game.stack.append(ApplyEffects(effects, provenance))
    if cost:
        game.pending = payment_request(game, card.owner, cost, card.name, target=card)


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
    disciplined : bool, optional
        Whether the card was played out of its owner's discard pile under Discipline, and so is
        removed from the game rather than discarded. Default False.
    """

    card_id: str
    disciplined: bool = False

    def resume(self, game: GameState) -> None:
        discard_played(game, self.card_id, disciplined=self.disciplined)


def resolve_strategy(
    game: GameState, card_id: str, ability_key: str | None = None, *, disciplined: bool = False
) -> None:
    """Resolve a paid-for Strategy: its ability against its target, and then its discard.

    The discard is stacked *under* the ability's own work so it runs after it, whether the ability
    hits every target at once or pauses to be pointed at one. A Terrain played during a battle is
    recorded as played before its ability resolves, so one whose entry is negated still counts
    (CR, Play).
    """
    card = game.table.cards_by_id[card_id]
    ability = ability_for(game, card, ability_key)
    if ability is None:
        raise ValueError(f"{card_id} has no ability to resolve")
    attack = game.attack
    if (
        attack is not None
        and attack.current is not None
        and keywords.TERRAIN in effective_keywords(game, card)
    ):
        record_terrain_played(game, card, battlefield=attack.current)
    game.stack.append(DiscardPlayed(card_id, disciplined))
    defer_ability(game, card, ability, plays_card=True)


def discard_played(game: GameState, card_id: str, *, disciplined: bool = False) -> None:
    """Discard a card whose play has finished, unless it has already left the hand.

    Step F discards the played card "unless it is now in play" (CR, Action Sequence). A Terrain, a
    Kata or an Edict reaches the board as the thing its own text does. A card that banished itself
    has left by another road, and discarding it would drag it back out of the pile it chose, so the
    test is whether it is still in hand rather than whether it reached the board.

    A card played under Discipline is removed from the game instead once its action ends, while it
    is still in the discard pile it was played from. One that put itself into play is removed the
    next time it leaves play (CR, Discipline).
    """
    game.announced_cards -= {card_id}
    card = game.table.cards_by_id[card_id]
    if disciplined:
        if any(held is card for held in game.table.battlefield.cards):
            game.banished_on_leaving_play |= {card_id}
        elif in_discard_pile(game, card):
            triggers.resolve_effects(game, [Banish(card_id)])
        return
    if card not in game.table.zones[ZoneKey(card.owner, ZoneRole.HAND)].cards:
        return
    triggers.resolve_effects(game, [Discard(card_id, card.owner)])
