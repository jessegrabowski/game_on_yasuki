from yasuki_core.engine.players import PlayerId
from yasuki_core.engine.rules.duel.focus_effects import focus_effect
from yasuki_core.engine.rules.duel.focusing import focused_cards
from yasuki_core.engine.rules.effects import Choose, Effect, GrantModifier
from yasuki_core.engine.rules.state import GameState
from yasuki_core.engine.rules.triggers import choice_resolver
from yasuki_core.engine.rules.vocabulary.modifiers import Duration, Stat
from yasuki_core.game_pieces.cards import L5RCard


# --- Weigh the Cost ---

WEIGH_THE_COST_FOCUS_BONUS = 1


def _weigh_the_cost_bonus(source_id: str, target_id: str) -> Effect:
    """A point of Focus Value on one card. The text gives it no duration, so it lasts until the end
    of the turn (CR, Ongoing), which outlives the duel that reads it."""
    return GrantModifier(
        source_id=source_id,
        target_id=target_id,
        stat=Stat.FOCUS,
        amount=WEIGH_THE_COST_FOCUS_BONUS,
        duration=Duration.UNTIL_END_OF_TURN,
    )


@focus_effect("weigh_the_cost")
def _weigh_the_cost_focus_effect(game: GameState, card: L5RCard) -> list[Effect]:
    """ "Add 1 to the Focus Values of this card and one other of your focused cards."

    A seat that focused nothing else takes its own point alone, rather than being asked to pick
    from none.
    """
    others = tuple(other.id for other in focused_cards(game, card.owner) if other.id != card.id)
    bonus: list[Effect] = [_weigh_the_cost_bonus(card.id, card.id)]
    if not others:
        return bonus
    return [
        *bonus,
        Choose(
            seat=card.owner,
            candidates=others,
            minimum=1,
            maximum=1,
            resolver="weigh_the_cost_other",
            source_id=card.id,
        ),
    ]


@choice_resolver("weigh_the_cost_other", prompt="Add 1 to another focused card's Focus Value")
def _resolve_weigh_the_cost_other(
    game: GameState, source_id: str, chosen: tuple[str, ...], seat: PlayerId
) -> list[Effect]:
    return [_weigh_the_cost_bonus(source_id, chosen[0])]
