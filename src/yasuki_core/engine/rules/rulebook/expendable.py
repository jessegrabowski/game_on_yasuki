from yasuki_core.engine.rules.effects import DrawCard, Effect
from yasuki_core.engine.rules.state import GameState
from yasuki_core.engine.rules.stats.keyword_grants import effective_keywords
from yasuki_core.engine.rules.triggers import TriggerContext, rulebook_trigger
from yasuki_core.engine.rules.vocabulary import keywords
from yasuki_core.engine.rules.vocabulary.game_events import Destroyed
from yasuki_core.game_pieces.cards import L5RCard


def _draw_a_card_label(game: GameState, card: L5RCard) -> str:
    return f"Draw a card for {card.name}'s destruction"


@rulebook_trigger(Destroyed, label=_draw_a_card_label)
def draw_for_an_expendable_death(ctx: TriggerContext) -> list[Effect]:
    """After an Expendable card is destroyed, its owner draws a card (ShE datasheet, Expendable).

    A Personality takes his unit with him and each member announces its own destruction, so an
    Expendable Follower on a dying Personality draws for itself.
    """
    card = ctx.card
    # Read off the board, so a keyword another card's text confers counts as a printed one
    # does. A keyword an effect granted is revoked as the card leaves play and does not.
    if keywords.EXPENDABLE not in effective_keywords(ctx.game, card):
        return []
    return [DrawCard(card.owner)]
