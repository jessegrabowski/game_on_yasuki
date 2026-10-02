from yasuki_core.engine.rules.effects import Effect, Negated
from yasuki_core.engine.rules.state import GameState
from yasuki_core.engine.rules.stats.ongoing_grants import grant_applies
from yasuki_core.engine.rules.vocabulary.modifiers import Negation
from yasuki_core.engine.rules.vocabulary.work import Provenance
from yasuki_core.game_pieces.cards import L5RCard
from yasuki_core.game_pieces.prints import RulebookPrint


def negate_committed(game: GameState, effect: Effect, provenance: Provenance) -> Effect:
    """``effect``, about to commit, as :class:`~.Negated` where a negation in force says so. A
    negation spent by its first use is spent here, by an effect that would happen.

    Parameters
    ----------
    game : GameState
        The game the effect commits in.
    effect : Effect
        The effect about to commit.
    provenance : Provenance
        Where the effect came from. Its ``acting`` is the card whose action produced it, which a
        negation naming a source is matched against.

    Returns
    -------
    committed : Effect
        ``effect`` itself, or ``effect`` wrapped in :class:`~.Negated`.
    """
    negation = _negating(game, effect, provenance.acting)
    if negation is None:
        return effect
    if negation.once and effect.would_happen(game):
        game.ongoing.remove(negation)
    return Negated(effect)


def would_negate(game: GameState, effect: Effect, acting: str | None) -> bool:
    """Whether a negation in force would negate ``effect`` from an action of the card ``acting``
    names, or from no action where it is None. Spends nothing."""
    return _negating(game, effect, acting) is not None


def negates_interrupt(game: GameState, card: L5RCard, replacement: Effect) -> bool:
    """Whether a negation naming a source negates ``replacement``, the modification an Interrupt
    from ``card`` makes. One that does binds nothing, so the effect it answers goes ahead."""
    return any(
        negation.names_a_source
        and _matches_source(negation, card)
        and _matches_effect(negation, replacement)
        for negation in _negations(game)
    )


def _negating(game: GameState, effect: Effect, acting: str | None) -> Negation | None:
    """The first negation in force that negates ``effect`` from an action of ``acting``."""
    source = game.table.cards_by_id.get(acting) if acting is not None else None
    for negation in _negations(game):
        if not _matches_effect(negation, effect):
            continue
        if negation.names_a_source and (source is None or not _matches_source(negation, source)):
            continue
        return negation
    return None


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
