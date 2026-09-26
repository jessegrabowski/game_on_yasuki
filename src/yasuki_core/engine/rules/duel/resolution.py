from dataclasses import dataclass

from yasuki_core import ruleset
from yasuki_core.engine import ops
from yasuki_core.engine.players import PlayerId, Rulebook
from yasuki_core.engine.rules import triggers
from yasuki_core.engine.rules.duel.focus_effects import (
    ResolveFocusEffects,
    cards_with_focus_effects,
)
from yasuki_core.engine.rules.duel.focusing import focused_cards
from yasuki_core.engine.rules.duel.procedure import duel_in_progress, duel_stat
from yasuki_core.engine.rules.duel.records import DuelOutcome, DuelRecord, DuelWork
from yasuki_core.engine.rules.vocabulary.segments import DuelStep
from yasuki_core.engine.rules.effects import Discard
from yasuki_core.engine.rules.state import GameState
from yasuki_core.engine.rules.turn.structure import DUEL_CONSEQUENCES
from yasuki_core.engine.rules.stats.keyword_grants import effective_keywords
from yasuki_core.engine.rules.vocabulary import keywords
from yasuki_core.engine.rules.vocabulary.game_events import (
    DuelEnded,
    DuelResolved,
    FocusedCardsRevealed,
    FocusEffectsResolved,
    GameEvent,
)
from yasuki_core.game_pieces.cards import L5RCard


@dataclass(frozen=True, slots=True)
class RevealFocusedCards(DuelWork):
    """Turn both focus stacks face up, the step a strike opens (CR, Duel 0.0.7). A step of its own
    because the Focus Effects of the cards it reveals resolve between it and the outcome."""

    def resume(self, game: GameState) -> None:
        duel = duel_in_progress(game)
        reveal_focused_cards(game)
        # Queued before the announcement, so a card reacting to the reveal resolves before the first
        # Focus Effect is named.
        game.stack.append(ResolveFocusEffects(cards_with_focus_effects(game, duel)))
        revealed = frozenset(
            (seat, card.id)
            for seat in (duel.challenger, duel.challenged)
            for card in focused_cards(game, seat)
        )
        triggers.fire(game, FocusedCardsRevealed(revealed=revealed))


@dataclass(frozen=True, slots=True)
class DecideTheDuel(DuelWork):
    """Total both sides, record who won, and end the duel (CR, Duel 0.0.9-0.0.12).

    The duel ends when this step ends, which is before its consequences apply and before its focused
    cards are discarded (CR, Duel). Those consequences are effects their cards delayed until
    ``DUEL_CONSEQUENCES``, and they resolve here.
    """

    def resume(self, game: GameState) -> None:
        duel = duel_in_progress(game)
        # The Focus Effects have all resolved by the time this step runs, so the step that follows
        # them announces it (CR, Duel: the effects resolve, then the duel is decided).
        triggers.fire(game, FocusEffectsResolved(source_card_id=duel.source))
        duel.step = DuelStep.RESOLUTION
        outcome = _outcome_on_totals(game, duel)
        duel.outcome = outcome
        triggers.fire(
            game,
            DuelResolved(
                winners=frozenset(outcome.winners),
                losers=frozenset(outcome.losers),
                totals=frozenset(outcome.totals.items()),
                source_card_id=duel.source,
            ),
        )
        duel.step = DuelStep.ENDED
        triggers.fire(game, DuelEnded(resolved=True, source_card_id=duel.source))
        triggers.resolve_delayed(game, DUEL_CONSEQUENCES)


@dataclass(frozen=True, slots=True)
class DiscardFocusedCards(DuelWork):
    """Discard what the duel focused and take the focusing areas off the table, the last step of the
    CR's DUEL entry, after the duel has ended and its consequences have applied."""

    def resume(self, game: GameState) -> None:
        triggers.fire_all(game, end_duel(game))


def reveal_focused_cards(game: GameState) -> None:
    """Turn every focused card face up and drop the private reads of it: a strike reveals both
    stacks at once, so nothing in a duel stays hidden past this point (CR, Duel)."""
    duel = duel_in_progress(game)
    duel.step = DuelStep.REVEAL
    for seat in (duel.challenger, duel.challenged):
        for card in focused_cards(game, seat):
            card.turn_face_up()
            card.clear_peekers()


def duel_total(game: GameState, duel: DuelRecord, seat: PlayerId) -> int:
    """What ``seat``'s Personality totals: its duel stat plus whatever its focused cards add (CR,
    Duel). How much they add belongs to the focus procedure, since an arc may have applied each
    Focus Value as its card was focused."""
    duelist = game.table.cards_by_id[duel.duelist_of(seat)]
    return duel_stat(game, duelist) + ruleset.ACTIVE.focus_procedure.focus_total(game, duel, seat)


def end_duel(game: GameState) -> list[GameEvent]:
    """Discard the duel's focused cards and take its focusing areas off the table (CR, Duel), running
    the focus procedure's own cleanup first. Return the events that raises, for the caller's cascade
    to drain.

    The record stays on the game with its outcome, so what resolves after a duel can still read how
    it went. The next duel declared replaces it.

    Raise ``RuntimeError`` where the duel has no outcome, which is a step that cleared up after a
    duel nothing ever decided.
    """
    # Read straight off the game rather than through `duel_in_progress`, since the duel has ended
    # by the time its focused cards are discarded.
    duel = game.duel
    if duel is None or duel.outcome is None:
        raise RuntimeError("the duel's focused cards are being discarded before it was decided")
    events: list[GameEvent] = []
    # While the focused cards are still in their areas, since a procedure's cleanup may read them.
    for effect in ruleset.ACTIVE.focus_procedure.cleanup(game, duel):
        events.extend(triggers.apply_effect(game, effect))
    for seat in (duel.challenger, duel.challenged):
        for card in focused_cards(game, seat):
            events.extend(triggers.apply_effect(game, Discard(card.id, Rulebook.DUEL_RESOLUTION)))
        left = ops.remove_focus_area(game.table, seat)
        if left:
            raise RuntimeError(
                f"{seat.name}'s focusing area still held {[card.id for card in left]}"
            )
    return events


def end_without_resolution(game: GameState) -> list[GameEvent]:
    """End the duel where it stands, with no winner and no totals: what a duelist leaving play does
    to a duel (CR, Duel). Return the events ending it raises.

    The duel's queued work goes with it, so no step of a duel that has ended runs. Work queued by
    whatever created the duel is left alone: the action that declared it still has its own steps to
    finish. Effects delayed until the duel's end are dropped rather than resolved, since the duel
    reached no outcome for a consequence to act on. An outstanding focus-or-strike is not withdrawn
    here, because only the decision layer clears a pending request; answering one for a duel that has
    ended raises instead.
    """
    duel = duel_in_progress(game)
    duel.step = DuelStep.ENDED
    game.stack[:] = [item for item in game.stack if not isinstance(item, DuelWork)]
    # The duel reached no outcome, so the consequences that waited for its end have nothing to
    # apply to, and one left held would resolve off the next duel's end (CR, Duel).
    triggers.discard_delayed(game, DUEL_CONSEQUENCES)
    duel.outcome = DuelOutcome(winners=(), losers=(), totals={})
    return [DuelEnded(resolved=False, source_card_id=duel.source), *end_duel(game)]


def _is_duelist(game: GameState, card: L5RCard) -> bool:
    """Whether ``card`` is a Duelist, read through its granted keywords so a Personality given the
    keyword counts as one (CR, Duelist)."""
    return keywords.DUELIST in effective_keywords(game, card)


def _outcome_on_totals(game: GameState, duel: DuelRecord) -> DuelOutcome:
    """Who won, on the totals and then on the Duelist tiebreak: the higher total wins, an equal one
    is won by a Duelist against a non-Duelist, and any other tie is lost by both (CR, Duel)."""
    challenger, challenged = duel.challenger, duel.challenged
    totals = {seat: duel_total(game, duel, seat) for seat in (challenger, challenged)}
    if totals[challenger] != totals[challenged]:
        winner = max(totals, key=lambda seat: totals[seat])
        return DuelOutcome((winner,), (duel.opponent_of(winner),), totals)
    duelists = {
        seat: _is_duelist(game, game.table.cards_by_id[duel.duelist_of(seat)])
        for seat in (challenger, challenged)
    }
    if duelists[challenger] != duelists[challenged]:
        winner = challenger if duelists[challenger] else challenged
        return DuelOutcome((winner,), (duel.opponent_of(winner),), totals)
    return DuelOutcome((), (challenger, challenged), totals)
