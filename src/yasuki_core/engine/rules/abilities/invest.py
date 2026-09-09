from yasuki_core.engine.rules import triggers
from yasuki_core.engine.rules.abilities.registry import fixed_invest_amount, invest_for
from yasuki_core.engine.rules.effects import GrantModifier
from yasuki_core.engine.rules.vocabulary.modifiers import Duration, Stat
from yasuki_core.engine.rules.state import GameState
from yasuki_core.game_pieces.cards import L5RCard


def finish_invest(game: GameState, card: L5RCard, invest_amount: int | None) -> None:
    """Charge ``card``'s Invest against itself and run what it bought. None is a card recruited
    without the option, which a free Invest is not — a card whose own text drops its Invest to zero
    still buys what the Invest buys.

    Invest belongs to a card entering play rather than to the action that brought it (CR, Invest),
    so Recruit and Equip reach this by the same road.
    """
    if invest_amount is None:
        return
    triggers.resolve_effects(
        game,
        [
            GrantModifier(card.id, card.id, Stat.GOLD_COST, invest_amount, Duration.PERMANENT),
            *invest_for(card).effect(game, card, invest_amount),
        ],
    )


def equip_invest_amount(game: GameState, card: L5RCard) -> int:
    """The Invest cost ``card`` charges to Equip with."""
    amount = fixed_invest_amount(game, card)
    if amount is None:
        raise ValueError(f"{card.id} prints no fixed Invest for Equip to charge")
    return amount
