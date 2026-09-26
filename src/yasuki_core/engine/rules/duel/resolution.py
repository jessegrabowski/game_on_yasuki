from dataclasses import dataclass

from yasuki_core import ruleset
from yasuki_core.engine import ops
from yasuki_core.engine.players import PlayerId, Rulebook
from yasuki_core.engine.rules import triggers
from yasuki_core.engine.rules.duel.focusing import focus_value, focused_cards
from yasuki_core.engine.rules.duel.procedure import duel_in_progress
from yasuki_core.engine.rules.duel.records import DuelOutcome, DuelRecord, DuelStep, DuelWork
from yasuki_core.engine.rules.effects import Discard
from yasuki_core.engine.rules.state import GameState
from yasuki_core.engine.rules.stats.calculation import effective_stat
from yasuki_core.engine.rules.stats.keyword_grants import effective_keywords
from yasuki_core.engine.rules.vocabulary import keywords
from yasuki_core.engine.rules.vocabulary.game_events import GameEvent
from yasuki_core.game_pieces.cards import L5RCard


@dataclass(frozen=True, slots=True)
class RevealFocusedCards(DuelWork):
    """Turn both focus stacks face up, the step a strike opens (CR, Duel 0.0.7). A step of its own
    because the Focus Effects of the cards it reveals resolve between it and the outcome."""

    def resume(self, game: GameState) -> None:
        reveal_focused_cards(game)


@dataclass(frozen=True, slots=True)
class DecideTheDuel(DuelWork):
    """Total both sides and record who won (CR, Duel 0.0.9-0.0.12). The consequences a card has
    given the duel apply to the outcome recorded here, before the duel ends."""

    def resume(self, game: GameState) -> None:
        duel = duel_in_progress(game)
        duel.step = DuelStep.RESOLUTION
        duel.outcome = _outcome_on_totals(game, duel)


@dataclass(frozen=True, slots=True)
class EndTheDuel(DuelWork):
    """End the duel the totals have decided, discarding what was focused (CR, Duel: "Discard all
    focused cards", the entry's last step)."""

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
    """What ``seat``'s Personality totals: its duel stat plus the Focus Values of the cards ``seat``
    focused (CR, Duel)."""
    duelist = game.table.cards_by_id[duel.duelist_of(seat)]
    return duel_stat(game, duelist) + sum(focus_value(card) for card in focused_cards(game, seat))


def duel_stat(game: GameState, card: L5RCard) -> int:
    """The stat this duel compares for ``card``, which is the ruleset's ``duel_stat_default`` until a
    card overrides it per duel or per Personality (CR, Duel Stat)."""
    return effective_stat(game, card, ruleset.ACTIVE.duel_stat_default)


def end_duel(game: GameState) -> list[GameEvent]:
    """End the duel on the outcome already recorded for it, discarding what was focused and taking
    the focusing areas off the table (CR, Duel: the focused cards are discarded as the duel ends).
    Return the events the discards raise, for the caller's cascade to drain.

    The record stays on the game with its outcome, so what resolves after a duel can still read how
    it went. The next duel declared replaces it.

    Raise ``RuntimeError`` where the duel has no outcome, which is a step that ended a duel it never
    decided.
    """
    duel = duel_in_progress(game)
    if duel.outcome is None:
        raise RuntimeError("the duel is ending with no outcome recorded")
    duel.option = None
    duel.step = DuelStep.ENDED
    events: list[GameEvent] = []
    owed = ruleset.ACTIVE.focus_procedure.cleanup(game, duel)
    if owed:
        triggers.resolve_effects(game, owed)
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
    finish. An outstanding focus-or-strike is not withdrawn here, because only the decision layer
    clears a pending request; answering one for a duel that has ended raises instead.
    """
    duel = duel_in_progress(game)
    game.stack[:] = [item for item in game.stack if not isinstance(item, DuelWork)]
    duel.outcome = DuelOutcome(winner=None, losers=(), totals={}, resolved=False)
    return end_duel(game)


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
        return DuelOutcome(winner, (duel.opponent_of(winner),), totals, resolved=True)
    duelists = {
        seat: _is_duelist(game, game.table.cards_by_id[duel.duelist_of(seat)])
        for seat in (challenger, challenged)
    }
    if duelists[challenger] != duelists[challenged]:
        winner = challenger if duelists[challenger] else challenged
        return DuelOutcome(winner, (duel.opponent_of(winner),), totals, resolved=True)
    return DuelOutcome(None, (challenger, challenged), totals, resolved=True)
