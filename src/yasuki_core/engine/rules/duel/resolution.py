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
from yasuki_core.engine.rules.effects import (
    ApplyEffects,
    Discard,
    Effect,
    Simultaneously,
    pile_for,
)
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
class AnnounceFocusEffectsResolved(DuelWork):
    """Announce that the Focus Effects have resolved, the step that follows them (CR, Duel: the
    effects resolve, then the duel is decided)."""

    def resume(self, game: GameState) -> None:
        duel = duel_in_progress(game)
        triggers.fire(game, FocusEffectsResolved(source_card_id=duel.source))


@dataclass(frozen=True, slots=True)
class DecideTheDuel(DuelWork):
    """Total both sides, record who won and announce it (CR, Duel 0.0.9-0.0.11).

    The duel's end and its consequences are steps of their own, so a question a card asks on
    :class:`~.DuelResolved` is answered before the duel ends.
    """

    def resume(self, game: GameState) -> None:
        duel = duel_in_progress(game)
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


@dataclass(frozen=True, slots=True)
class EndTheDuel(DuelWork):
    """End the duel once it is decided, before its consequences apply and before its focused cards
    are discarded (CR, Duel 0.0.12)."""

    def resume(self, game: GameState) -> None:
        duel = duel_in_progress(game)
        duel.step = DuelStep.ENDED
        # Lapsed before the end is announced, so nothing reacting to it reads a stat the duel was
        # still holding up, and so the board their expiry leaves is settled first.
        triggers.lapse_ongoing(game, DUEL_CONSEQUENCES)
        triggers.fire(game, DuelEnded(resolved=True, source_card_id=duel.source))


@dataclass(frozen=True, slots=True)
class ApplyDuelConsequences(DuelWork):
    """Resolve the consequences cards delayed until ``DUEL_CONSEQUENCES``, once the duel has
    ended."""

    def resume(self, game: GameState) -> None:
        triggers.resolve_delayed(game, DUEL_CONSEQUENCES)


@dataclass(frozen=True, slots=True)
class DropDuelConsequences:
    """Lapse the records lasting until the duel's end and discard the consequences held for it.

    A step rather than part of :func:`~.end_without_resolution`, because the Focus Effects that
    outlive an early exit resolve first and may hold consequences of their own. One left held would
    resolve off the next duel's end (CR, Duel). Not a step of the duel's own, so an early exit does
    not drop it.
    """

    def resume(self, game: GameState) -> None:
        triggers.lapse_ongoing(game, DUEL_CONSEQUENCES)
        triggers.discard_delayed(game, DUEL_CONSEQUENCES)


@dataclass(frozen=True, slots=True)
class DiscardFocusedCards(DuelWork):
    """Discard what the duel focused and take the focusing areas off the table, the last step of the
    CR's DUEL entry, after the duel has ended and its consequences have applied."""

    def resume(self, game: GameState) -> None:
        game.stack.append(RemoveFocusAreas(_decided_duel(game)))
        triggers.resolve_effects(game, duel_cleanup(game))


@dataclass(frozen=True, slots=True)
class RemoveFocusAreas:
    """Take ``duel``'s focusing areas off the table once its cleanup has resolved, cascade
    included. Not a step of the duel's own, so a duel ending early does not drop it.

    A temporary area ceases to exist once it has served its purpose (CR, Areas of the Game), so a
    card still in one, such as a focused card whose discard was negated, goes to its owner's
    discard pile. The move is not an effect, so no negation reaches it.
    """

    duel: DuelRecord

    def resume(self, game: GameState) -> None:
        for seat in (self.duel.challenger, self.duel.challenged):
            for card in focused_cards(game, seat):
                ops.move_card(game.table, card, pile_for(card))
            ops.remove_focus_area(game.table, seat)


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


def duel_cleanup(game: GameState) -> list[Effect]:
    """The effects that clear a duel away (CR, Duel): the focus procedure's own cleanup, then the
    discard of every focused card at once ("Discard all focused cards"). They resolve through the
    cascade like any rulebook procedure's, and :class:`RemoveFocusAreas` follows them.

    The record stays on the game with its outcome, so what resolves after a duel can still read how
    it went. The next duel declared replaces it.

    Raise ``RuntimeError`` where the duel has no outcome, which is a step that cleared up after a
    duel nothing ever decided.
    """
    duel = _decided_duel(game)
    # Built while the focused cards are still in their areas, since a procedure's cleanup may read
    # them, and listed ahead of the discards so it resolves while they are still there.
    discards = [
        Discard(card.id, Rulebook.DUEL_RESOLUTION)
        for seat in (duel.challenger, duel.challenged)
        for card in focused_cards(game, seat)
    ]
    return [*ruleset.ACTIVE.focus_procedure.cleanup(game, duel), Simultaneously(tuple(discards))]


def end_without_resolution(game: GameState) -> list[GameEvent]:
    """End the duel where it stands, with no winner and no totals: what a duelist leaving play does
    to a duel (CR, Duel). Return the event ending it. Its cleanup is queued to resolve once the
    cascade it ended in has settled, since this runs inside an effect.

    The duel's queued work goes with it, so no step of a duel that has ended runs, except one that
    outlives an early exit: the Focus Effects of the cards the strike revealed still resolve, while
    their cards are still in their focusing areas and before what waited for the duel's end is torn
    down. Effects delayed until the duel's end are dropped rather than resolved, since the duel
    reached no outcome for a consequence to act on. Work queued by whatever created the duel is left
    alone, since the action that declared it still has its own steps to finish. An outstanding
    focus-or-strike is not withdrawn here, because only the decision layer clears a pending request;
    answering one for a duel that has ended raises instead.
    """
    duel = duel_in_progress(game)
    duel.step = DuelStep.ENDED
    standing = [
        item for item in game.stack if isinstance(item, DuelWork) and item.survives_early_exit
    ]
    game.stack[:] = [item for item in game.stack if not isinstance(item, DuelWork)]
    # The duel reached no outcome, so what waited for its end does not happen: the records lasting
    # until it lapse, and the consequences held for it are dropped rather than resolved. One left
    # held would resolve off the next duel's end (CR, Duel).
    duel.outcome = DuelOutcome(winners=(), losers=(), totals={})
    # Pushed in reverse of the order they run, since the stack pops the last item first: the Focus
    # Effects that outlived the exit, then the teardown of what waited for the duel's end, then the
    # cleanup that discards the cards those Focus Effects read.
    game.stack.append(RemoveFocusAreas(duel))
    game.stack.append(ApplyEffects(tuple(duel_cleanup(game))))
    game.stack.append(DropDuelConsequences())
    game.stack.extend(standing)
    return [DuelEnded(resolved=False, source_card_id=duel.source)]


def _decided_duel(game: GameState) -> DuelRecord:
    """The duel on the game, read off it directly because :func:`~.duel_in_progress` refuses one
    that has ended. Raise ``RuntimeError`` where there is no duel or it has no outcome."""
    duel = game.duel
    if duel is None or duel.outcome is None:
        raise RuntimeError("the duel's focused cards are being discarded before it was decided")
    return duel


def _is_duelist(game: GameState, card: L5RCard) -> bool:
    """Whether ``card`` is a Duelist, read through its granted keywords so a Personality given the
    keyword counts as one (CR, Duelist)."""
    return keywords.DUELIST in effective_keywords(game, card)


def _outcome_on_totals(game: GameState, duel: DuelRecord) -> DuelOutcome:
    """Who won, on the totals and then on the Duelist tiebreak: the higher total wins, an equal one
    is won by a Duelist against a non-Duelist, and any other tie is lost by both (CR, Duel).

    A duel a card has made both Personalities lose skips the comparison and is lost by both, with
    the totals it reached still recorded, since cards and clients read them either way.
    """
    challenger, challenged = duel.challenger, duel.challenged
    totals = {seat: duel_total(game, duel, seat) for seat in (challenger, challenged)}
    # Read while the cards are still in their areas, since the duel's last step discards them.
    focused = {
        seat: tuple(card.id for card in focused_cards(game, seat))
        for seat in (challenger, challenged)
    }
    if duel.lost_by_both:
        return DuelOutcome((), (challenger, challenged), totals, focused)
    if totals[challenger] != totals[challenged]:
        winner = max(totals, key=lambda seat: totals[seat])
        return DuelOutcome((winner,), (duel.opponent_of(winner),), totals, focused)
    duelists = {
        seat: _is_duelist(game, game.table.cards_by_id[duel.duelist_of(seat)])
        for seat in (challenger, challenged)
    }
    if duelists[challenger] != duelists[challenged]:
        winner = challenger if duelists[challenger] else challenged
        return DuelOutcome((winner,), (duel.opponent_of(winner),), totals, focused)
    return DuelOutcome((), (challenger, challenged), totals, focused)
