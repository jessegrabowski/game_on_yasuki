from collections.abc import Iterator

from yasuki_core.engine.rules.effects import Effect, Negated
from yasuki_core.engine.rules.state import GameState
from yasuki_core.engine.rules.stats.ongoing_grants import grant_applies
from yasuki_core.engine.rules.vocabulary.modifiers import Negation
from yasuki_core.engine.rules.vocabulary.work import Provenance
from yasuki_core.game_pieces.cards import L5RCard
from yasuki_core.game_pieces.prints import RulebookPrint


def action_provenance(game: GameState, acting: str | None) -> Provenance:
    """The provenance of an action from the card ``acting`` names, as it hands its effects over.

    A ``once`` negation naming only a source is spent by the first action from a matching card
    (CR, Negate an Action: all of the action's effects), so it leaves ``game.ongoing`` here and
    travels with the action, negating every effect it produces and no other.

    Parameters
    ----------
    game : GameState
        The game the action is taken in.
    acting : str or None
        The card whose action this is, or None for an action from no card, as the rulebook's are.

    Returns
    -------
    provenance : Provenance
        The action's provenance, carrying the negations it spent.
    """
    if acting is None:
        return Provenance()
    source = game.table.cards_by_id[acting]
    spent = tuple(
        negation
        for negation in _negations(game)
        if negation.once and _negates_whole_actions(negation) and _matches_source(negation, source)
    )
    for negation in spent:
        game.ongoing.remove(negation)
    return Provenance(acting=acting, negations=spent)


def negate_committed(game: GameState, effect: Effect, provenance: Provenance) -> Effect:
    """``effect``, about to commit, as :class:`~.Negated` where a negation says so. A negation in
    force spent by its first use is spent here, by an effect that would happen.

    Parameters
    ----------
    game : GameState
        The game the effect commits in.
    effect : Effect
        The effect about to commit.
    provenance : Provenance
        Where the effect came from: the card whose action produced it, which a negation naming a
        source is matched against, and the negations that action spent.

    Returns
    -------
    committed : Effect
        ``effect`` itself, or ``effect`` wrapped in :class:`~.Negated`.
    """
    if not effect.is_negatable(game):
        return effect
    negation = next(_matching(game, effect, provenance), None)
    if negation is None:
        return effect
    _spend(game, negation, effect, provenance)
    return Negated(effect)


def would_negate(
    game: GameState, effect: Effect, provenance: Provenance, spent: list[Negation]
) -> bool:
    """Whether ``effect`` would be negated as it commits, once the effects before it have spent the
    ``once`` negations in ``spent``. One ``effect`` would spend joins ``spent``, and nothing leaves
    ``game.ongoing``."""
    if not effect.is_negatable(game):
        return False
    negation = next(
        (negation for negation in _matching(game, effect, provenance) if negation not in spent),
        None,
    )
    if negation is None:
        return False
    if _spends(game, negation, effect, provenance):
        spent.append(negation)
    return True


def continuously_negated(game: GameState, effect: Effect) -> bool:
    """Whether a negation in force that is not ``once`` would stop ``effect``, which comes from no
    action. Spends nothing. What a state-based action asks before demanding an effect, since only
    a continuous effect holds against one and a spent negation would only see it demanded again
    (CR, Chi Death Rule)."""
    if not effect.is_negatable(game):
        return False
    return any(not negation.once for negation in _matching(game, effect, Provenance()))


def strips_interrupt(game: GameState, replacement: Effect, provenance: Provenance) -> bool:
    """Whether a negation naming a source negates ``replacement``, the modification an Interrupt
    with ``provenance`` makes, spending a ``once`` negation that does. A stripped Interrupt binds
    nothing, so the effect it answers goes ahead. Whether ``replacement`` is itself negatable does
    not matter: what is negated is the Interrupt's modifying it, even into a negation."""
    negation = next(
        (
            negation
            for negation in _matching(game, replacement, provenance)
            if negation.names_a_source
        ),
        None,
    )
    if negation is None:
        return False
    _spend(game, negation, replacement, provenance)
    return True


def _matching(game: GameState, effect: Effect, provenance: Provenance) -> Iterator[Negation]:
    """Each negation that negates ``effect`` from ``provenance``'s action: first those the action
    spent, then those in force."""
    yield from (negation for negation in provenance.negations if _matches_effect(negation, effect))
    acting = provenance.acting
    source = game.table.cards_by_id.get(acting) if acting is not None else None
    for negation in _negations(game):
        if not _matches_effect(negation, effect):
            continue
        if negation.names_a_source and (source is None or not _matches_source(negation, source)):
            continue
        yield negation


def _spend(game: GameState, negation: Negation, effect: Effect, provenance: Provenance) -> None:
    if _spends(game, negation, effect, provenance):
        game.ongoing.remove(negation)


def _spends(game: GameState, negation: Negation, effect: Effect, provenance: Provenance) -> bool:
    """Whether negating ``effect`` spends ``negation``: a ``once`` negation still in force, on an
    effect that would happen. One the action already spent negates the rest of that action."""
    return negation.once and negation not in provenance.negations and effect.would_happen(game)


def _negates_whole_actions(negation: Negation) -> bool:
    """Whether ``negation`` names a source and nothing about the effects, so it negates actions."""
    return negation.names_a_source and negation.effect_kind is None and negation.subject_id is None


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
    return negation.subject_id is None or effect.subject_id == negation.subject_id


def _negations(game: GameState) -> list[Negation]:
    return [
        recorded
        for recorded in game.ongoing
        if isinstance(recorded, Negation) and grant_applies(game, recorded)
    ]
