from yasuki_core.engine.players import PlayerId
from yasuki_core.engine.rules.abilities import (
    Ability,
    CardLocation,
    InvestAbility,
    no_cost,
    one_wealth,
    register_ability,
    register_invest,
)
from yasuki_core.engine.rules.actions import ActionTiming
from yasuki_core.engine.rules.effects import (
    AdjustCounter,
    Ask,
    Discard,
    DrawCard,
    Effect,
    GainHonor,
    MoveToDeck,
    ShuffleDeck,
    Then,
)
from yasuki_core.engine.rules.state import GameState
from yasuki_core.engine.rules.triggers import choice_resolver
from yasuki_core.engine.table import DeckKey
from yasuki_core.game_pieces.cards import L5RCard
from yasuki_core.game_pieces.constants import Side
from yasuki_core.game_pieces.counters import WEALTH


# --- Blessings of the Red Panda Spirit ---


@choice_resolver("red_panda_spirit_keep")
def _red_panda_spirit_keep(
    game: GameState, source_id: str, chosen: tuple[str, ...], seat: PlayerId
) -> list[Effect]:
    """Reshuffle the Event into its owner's Dynasty deck, or discard it. Declining is not doing
    nothing — the Event leaves its Province either way, and only where it goes is the seat's."""
    if not chosen:
        return [Discard(source_id, seat)]
    deck = DeckKey(seat, Side.DYNASTY)
    return [MoveToDeck(source_id, deck, from_top=0), ShuffleDeck(deck)]


def _red_panda_spirit_targets(game: GameState, card: L5RCard) -> list[str]:
    """The Event itself. The ability names no card at all, but an ability whose candidates are empty
    is never offered, so it stands as its own — paired with ``all_targets`` so the seat is not asked
    to pick the only thing there is."""
    return [card.id]


def _red_panda_spirit_effects(game: GameState, source: L5RCard, target: L5RCard) -> list[Effect]:
    """A gift to the table, then a question. Every seat gains and draws in seat order; the reshuffle
    is deferred so it follows the draws, which is the order the card states."""
    gifts: list[Effect] = []
    for seat in game.table.seats:
        gifts.append(GainHonor(seat, 1))
        gifts.append(DrawCard(seat))
    question = f"Shuffle {source.name} into your Dynasty deck instead of discarding it?"
    return [
        *gifts,
        Then(
            (
                Ask(
                    source.owner,
                    question,
                    "red_panda_spirit_keep",
                    subjects=(source.id,),
                    source_id=source.id,
                ),
            )
        ),
    ]


register_ability(
    "blessings_of_the_red_panda_spirit",
    Ability(
        timing=ActionTiming.OPEN,
        label="Each player gains 1 Honor and draws a card",
        cost=no_cost,
        targets=_red_panda_spirit_targets,
        effects=_red_panda_spirit_effects,
        all_targets=True,
        located_at=(CardLocation.PROVINCE,),
    ),
)


# --- Courts of Otosan Uchi ---

register_invest("courts_of_otosan_uchi", InvestAbility(minimum=2, maximum=2, effect=one_wealth))


# --- Rebuilt Harbor ---


def _invest_wealth(game: GameState, source: L5RCard, amount: int) -> list[Effect]:
    """One +1GP Wealth token per gold invested — Rebuilt Harbor's variable payoff."""
    return [AdjustCounter(source.id, WEALTH, amount)]


register_invest("rebuilt_harbor", InvestAbility(minimum=1, maximum=3, effect=_invest_wealth))
