from collections.abc import Iterable

from yasuki_core.engine.rules.effects import Effect, Negated
from yasuki_core.engine.rules.state import GameState
from yasuki_core.engine.rules.stats.ongoing_grants import grant_applies
from yasuki_core.engine.rules.vocabulary.modifiers import Negation
from yasuki_core.game_pieces.cards import L5RCard
from yasuki_core.game_pieces.prints import RulebookPrint


def negate_from(game: GameState, source: L5RCard, effects: Iterable[Effect]) -> list[Effect]:
    """``effects``, as an action from ``source`` hands them over, each :class:`~.Negated` where a
    negation naming a source says so."""
    return [Negated(effect) if negates_from(game, source, effect) else effect for effect in effects]


def negates_from(game: GameState, source: L5RCard, effect: Effect) -> bool:
    """Whether a negation naming a source negates ``effect`` from an action of ``source``."""
    return any(
        negation.names_a_source
        and _matches_source(negation, source)
        and _matches_effect(negation, effect)
        for negation in _negations(game)
    )


def negate_committed(game: GameState, effect: Effect) -> Effect:
    """``effect``, about to commit, as :class:`~.Negated` where a negation naming no source says
    so. A negation spent by its first use is spent here, by an effect that would happen."""
    negation = next(
        (
            negation
            for negation in _negations(game)
            if not negation.names_a_source and _matches_effect(negation, effect)
        ),
        None,
    )
    if negation is None:
        return effect
    if negation.once and effect.would_happen(game):
        game.ongoing.remove(negation)
    return Negated(effect)


def _matches_source(negation: Negation, source: L5RCard) -> bool:
    """Whether ``source`` is a card whose actions ``negation`` negates. A rulebook proxy is the
    rulebook, never a card (CR, From)."""
    if isinstance(source.printed, RulebookPrint):
        return False
    if negation.source_kind is not None and not isinstance(source.printed, negation.source_kind):
        return False
    return negation.source_title is None or source.name == negation.source_title


def _matches_effect(negation: Negation, effect: Effect) -> bool:
    """Whether ``effect`` is of the kind, and acts on the card, ``negation`` negates."""
    if negation.effect_kind is not None and not isinstance(effect, negation.effect_kind):
        return False
    return negation.subject_id is None or getattr(effect, "card_id", None) == negation.subject_id


def _negations(game: GameState) -> list[Negation]:
    return [
        recorded
        for recorded in game.ongoing
        if isinstance(recorded, Negation) and grant_applies(game, recorded)
    ]
