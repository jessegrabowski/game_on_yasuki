from yasuki_core.engine.rules.abilities.model import CardLocation, Interrupt, Interruption
from yasuki_core.engine.rules.abilities.registry import register_interrupt
from yasuki_core.engine.rules.effects import Destroy, Dishonor, Effect, GainHonor, Negated
from yasuki_core.engine.rules.state import GameState
from yasuki_core.engine.rules.triggers import TriggerContext, on
from yasuki_core.engine.rules.units.membership import attached_to
from yasuki_core.engine.rules.vocabulary.game_events import EnteredPlay
from yasuki_core.game_pieces.cards import L5RCard


# --- Blessed Sword ---


@on(EnteredPlay, "blessed_sword")
def _blessed_sword_entered_play(ctx: TriggerContext) -> list[Effect]:
    """After you Equip this Item, gain 1 Honor. The +1F/+1C is printed on the card. Attaching to a
    dishonorable Personality rehonors him in place of the gain (CR, Rehonoring 0.2)."""
    if ctx.event.card_id != ctx.card.id or not ctx.event.from_hand:
        return []
    bearer = attached_to(ctx.game, ctx.card)
    bearers = () if bearer is None else (bearer.id,)
    return [GainHonor(ctx.card.owner, 1, personalities=bearers)]


def _blessed_sword_applies(game: GameState, source: L5RCard, effect: Dishonor) -> bool:
    bearer = attached_to(game, source)
    return bearer is not None and bearer.id == effect.card_id


def _blessed_sword_cost(game: GameState, source: L5RCard) -> list[Effect]:
    """Destroy this Item: what the card gives up to negate, so it is the cost of taking it."""
    return [Destroy(source.id, source.owner)]


def _blessed_sword_interrupt(game: GameState, source: L5RCard, effect: Dishonor) -> Interruption:
    """Before this Personality is dishonored, destroy this Item and negate the dishonoring."""
    return Interruption(Negated(effect))


register_interrupt(
    "blessed_sword",
    Interrupt(
        label="Before this Personality is dishonored, destroy this Item and negate the dishonoring.",
        answers=Dishonor,
        interrupt=_blessed_sword_interrupt,
        applies=_blessed_sword_applies,
        located_at=(CardLocation.BATTLEFIELD,),
        cost=_blessed_sword_cost,
    ),
)
