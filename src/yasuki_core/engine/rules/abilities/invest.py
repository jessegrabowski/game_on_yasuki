from yasuki_core.engine.rules.abilities.registry import fixed_invest_amount, invest_for
from yasuki_core.engine.rules.effects import Effect
from yasuki_core.engine.rules.triggers import TriggerContext, action_did, rulebook_trigger
from yasuki_core.engine.rules.vocabulary.game_events import EnteredPlay, Invested
from yasuki_core.engine.rules.state import GameState
from yasuki_core.game_pieces.cards import L5RCard


@rulebook_trigger(EnteredPlay)
def resolve_invest(ctx: TriggerContext) -> list[Effect]:
    """After a card enters play, the Invest the action bringing it in paid for resolves, for the
    Gold Invested. The effects are the Invest trait's, not the action's (CR, Invest)."""
    ability = invest_for(ctx.card)
    if ability is None:
        return []
    invested = [
        event.amount for event in action_did(ctx.game, Invested) if event.card_id == ctx.card.id
    ]
    if not invested:
        return []
    return ability.effect(ctx.game, ctx.card, invested[-1])


def equip_invest_amount(game: GameState, card: L5RCard) -> int:
    """The Invest cost ``card`` charges to Equip with."""
    amount = fixed_invest_amount(game, card)
    if amount is None:
        raise ValueError(f"{card.id} prints no fixed Invest for Equip to charge")
    return amount
