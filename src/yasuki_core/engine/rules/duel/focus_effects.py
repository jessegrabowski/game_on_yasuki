from collections.abc import Callable
from dataclasses import dataclass

from yasuki_core.engine.registrar import HandlerRegistry
from yasuki_core.engine.rules import triggers
from yasuki_core.engine.rules.duel.focusing import focused_cards
from yasuki_core.engine.rules.duel.procedure import duel_in_progress
from yasuki_core.engine.rules.duel.records import DuelRecord, DuelWork
from yasuki_core.engine.rules.effects import Effect
from yasuki_core.engine.rules.state import GameState
from yasuki_core.engine.rules.vocabulary.decisions import ChooseFocusEffect, DecisionResponse
from yasuki_core.game_pieces.cards import L5RCard

# What a card's "As a Focus Effect" text does once a duel has revealed it, returning effects for the
# duel to resolve. A registry rather than a trigger because the CR resolves these only for revealed
# focused cards, in an order the active player chooses, and ignores every other line of text on them
# (CR, Duel). A card whose Focus Effect is optional asks that question itself, with an ``Ask``.
FocusEffect = Callable[[GameState, L5RCard], list[Effect]]

FOCUS_EFFECTS: HandlerRegistry[FocusEffect] = HandlerRegistry(
    "focus effect", "already has a focus effect"
)
focus_effect = FOCUS_EFFECTS.make_decorator()


def cards_with_focus_effects(game: GameState, duel: DuelRecord) -> tuple[str, ...]:
    """The ids of the revealed focused cards carrying a Focus Effect, each seat's in the order it
    focused them, the challenger's first."""
    return tuple(
        card.id
        for seat in (duel.challenger, duel.challenged)
        for card in focused_cards(game, seat)
        if card.printed_id in FOCUS_EFFECTS
    )


@dataclass(frozen=True, slots=True)
class ResolveFocusEffects(DuelWork):
    """Resolve the Focus Effects the strike revealed, one card at a time (CR, Duel).

    The active player names the next one while more than one is left, and the step queues itself
    again with the rest, so an effect that pauses for a decision resumes into the next card and a
    duel that ends early drops the Focus Effects that have not resolved.

    Attributes
    ----------
    remaining : tuple of str
        The ids of the focused cards whose Focus Effects have still to resolve.
    """

    remaining: tuple[str, ...]

    def resume(self, game: GameState) -> None:
        duel_in_progress(game)
        if not self.remaining:
            return
        if len(self.remaining) == 1:
            resolve_focus_effect(game, self.remaining[0], ())
            return
        game.pending = ChooseFocusEffect(seat=game.active, candidates=self.remaining)


def apply_focus_effect_choice(
    game: GameState, request: ChooseFocusEffect, response: DecisionResponse
) -> None:
    """Resolve the Focus Effect the active player named, and ask again for what is left."""
    chosen = response.choices[0]
    remaining = tuple(card_id for card_id in request.candidates if card_id != chosen)
    resolve_focus_effect(game, chosen, remaining)


def resolve_focus_effect(game: GameState, card_id: str, remaining: tuple[str, ...]) -> None:
    """Resolve ``card_id``'s Focus Effect, with ``remaining`` left to resolve after it.

    The rest are queued first, so that what this Focus Effect pushes resolves before the next card
    is named. A card that has left the table since the reveal resolves nothing.
    """
    if remaining:
        game.stack.append(ResolveFocusEffects(remaining))
    card = game.table.cards_by_id.get(card_id)
    if card is None:
        return
    handler = FOCUS_EFFECTS.get(card.printed_id)
    if handler is None:
        return
    effects = handler(game, card)
    if effects:
        triggers.resolve_effects(game, effects)
