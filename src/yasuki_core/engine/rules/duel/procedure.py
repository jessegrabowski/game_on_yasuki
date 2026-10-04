from dataclasses import dataclass

from yasuki_core import ruleset
from yasuki_core.engine import ops
from yasuki_core.engine.players import PlayerId
from yasuki_core.engine.rules import triggers
from yasuki_core.engine.rules.duel.focusing import focused_cards
from yasuki_core.engine.rules.duel.records import DuelOutcome, DuelRecord, DuelWork
from yasuki_core.engine.rules.vocabulary.segments import Boundary
from yasuki_core.engine.rules.state import GameState
from yasuki_core.engine.rules.stats.calculation import effective_stat
from yasuki_core.engine.rules.stats.ongoing_grants import named_duel_stat
from yasuki_core.engine.rules.vocabulary.game_events import (
    CardFocused,
    DuelDeclared,
    GameEvent,
    StrikeDeclared,
)
from yasuki_core.engine.rules.vocabulary.decisions import (
    STRIKE,
    DecisionResponse,
    FocusOrStrike,
)
from yasuki_core.game_pieces.cards import L5RCard
from yasuki_core.game_pieces.prints import PersonalityPrint


def duel_in_progress(game: GameState) -> DuelRecord:
    """``GameState.duel_being_fought``, raising ``RuntimeError`` where no duel is. Every caller here
    is part of a duel's own procedure and has no second thing to mean."""
    duel = game.duel_being_fought
    if duel is None:
        raise RuntimeError("no duel is being fought")
    return duel


def decided_duel(game: GameState) -> DuelRecord | None:
    """The duel on the game once it has an outcome, or None where there is none or it is still being
    fought. What anything reading how a duel went checks before it acts."""
    duel = game.duel
    return None if duel is None or duel.outcome is None else duel


def decided_outcome(game: GameState) -> DuelOutcome | None:
    """How the duel on the game went, or None where there is none or it is still being fought. What
    a card reading winners or losers wants, with no record to narrow."""
    duel = decided_duel(game)
    return None if duel is None else duel.outcome


def duel_decided_by(game: GameState, source_id: str) -> DuelRecord | None:
    """The decided duel ``source_id`` created, or None where there is none.

    What a consequence delayed to the duel's end reads before it acts. A challenge that did not
    happen leaves the consequence held, so matching the source is what keeps it off the next duel
    to end (CR, Challenge).
    """
    duel = decided_duel(game)
    return None if duel is None or duel.source != source_id else duel


def challenge_is_legal(game: GameState, challenger_duelist: str, challenged_duelist: str) -> bool:
    """Whether a challenge between these two cards happens at all (CR, Challenge): it does not where
    one player controls both, nor where either card is not a Personality.

    Both duelists are read off the battlefield, so a Personality that left play between being
    targeted and the duel being declared refuses the challenge, wherever it went and whether or not
    the table still holds the card.
    """
    in_play = {card.id: card for card in game.table.battlefield.cards}
    challenger = in_play.get(challenger_duelist)
    challenged = in_play.get(challenged_duelist)
    if challenger is None or challenged is None:
        return False
    if not all(isinstance(card.printed, PersonalityPrint) for card in (challenger, challenged)):
        return False
    return challenger.owner is not challenged.owner


def declare_duel(
    game: GameState,
    *,
    challenger_duelist: str,
    challenged_duelist: str,
    source: str,
) -> list[GameEvent]:
    """Begin a duel between the two named Personalities and open the focusing, whose first option
    belongs to the challenged seat (CR, Duel).

    The two seats are the duelists' own controllers, read from the cards, so they cannot disagree
    with the Personalities they belong to. Return the two declaration events, for the caller's
    cascade to drain.

    Do nothing where :func:`~.challenge_is_legal` refuses the challenge, which is the CR's own
    wording: such a challenge does not happen, rather than happening and failing.

    The focusing areas are created here and dropped when the duel ends, so a seat outside a duel has
    none.

    Raise ``RuntimeError`` where a duel is already being fought. One effect that creates several
    duels fights them one after another (CR, Duration), and running several sub-procedures in
    sequence from one effect is unbuilt.
    """
    if not challenge_is_legal(game, challenger_duelist, challenged_duelist):
        return []
    challenger = game.table.cards_by_id[challenger_duelist].owner
    challenged = game.table.cards_by_id[challenged_duelist].owner
    duel = DuelRecord(
        challenger=challenger,
        challenged=challenged,
        challenger_duelist=challenger_duelist,
        challenged_duelist=challenged_duelist,
        source=source,
    )
    game.begin_duel(duel)
    ops.create_focus_area(game.table, challenger)
    ops.create_focus_area(game.table, challenged)
    challenger_stat = duel_stat(game, game.table.cards_by_id[challenger_duelist])
    challenged_stat = duel_stat(game, game.table.cards_by_id[challenged_duelist])
    # Queued before the declaration is announced, so that work a card does in reaction to it sits
    # above the duel's own steps and resolves before the first seat is asked.
    queue_duel_steps(game, OfferFocusOrStrike(challenged))
    return [
        _declaration(duel, Boundary.BEGINNING, challenger_stat, challenged_stat),
        _declaration(duel, Boundary.END, challenger_stat, challenged_stat),
    ]


def _declaration(
    duel: DuelRecord, boundary: Boundary, challenger_stat: int, challenged_stat: int
) -> DuelDeclared:
    """The declaration at one of its edges, built from ``duel`` and the duel stats it begins on."""
    return DuelDeclared(
        boundary=boundary,
        challenger=duel.challenger,
        challenged=duel.challenged,
        challenger_duelist=duel.challenger_duelist,
        challenged_duelist=duel.challenged_duelist,
        source_card_id=duel.source,
        challenger_stat=challenger_stat,
        challenged_stat=challenged_stat,
    )


@dataclass(frozen=True, slots=True)
class OpenDuelWindow(DuelWork):
    """Offer every seat the Responses the duel's last step announced, before its next step runs.

    A step of the duel's own, so a duel that ends early drops the windows it had queued along with
    the steps they stood in front of. Does nothing where no seat holds a Response, which is a window
    nobody needs to be asked to pass.
    """

    def resume(self, game: GameState) -> None:
        # The window is a round, and rounds belong to the turn sequence, which already imports this
        # module for the duel's work items and for whether a duel is being fought.
        from yasuki_core.engine.rules.turn.sequence import open_duel_window

        open_duel_window(game)


def queue_duel_steps(game: GameState, *steps: DuelWork) -> None:
    """Queue ``steps`` to run in the order given, each behind a window for the Responses the step
    before it announced.

    Every time point a duel names is a point a card may react at, so queueing a step is what puts
    the window in front of it (CR, Duel: the sequence of steps; the window at each is an inference).
    """
    for step in reversed(steps):
        game.stack.append(step)
        game.stack.append(OpenDuelWindow())


@dataclass(frozen=True, slots=True)
class OfferFocusOrStrike(DuelWork):
    """Put the focus-or-strike option to ``seat``.

    A work item, because the option is a question the procedure pauses for: the duel is declared
    inside an action's cascade, and the loop picks up again on each answer.
    """

    seat: PlayerId

    def resume(self, game: GameState) -> None:
        offer_focus_or_strike(game, self.seat)


def duel_stat(game: GameState, card: L5RCard) -> int:
    """The stat this duel compares for ``card``: the ruleset's ``duel_stat_default`` unless a card
    has named another for this Personality (CR, Duel Stat)."""
    stat = named_duel_stat(game, card.id) or ruleset.ACTIVE.duel_stat_default
    return effective_stat(game, card, stat)


def offer_focus_or_strike(game: GameState, seat: PlayerId) -> None:
    """Ask ``seat`` to focus a card or to strike, or strike for it where it has nothing to focus
    with. A seat that cannot focus is not asked: the CR gives it no other option, and a question
    with one answer is not a decision."""
    duel = duel_in_progress(game)
    sources = ruleset.ACTIVE.focus_procedure.sources(game, duel, seat)
    if not sources:
        strike(game, seat)
        return
    game.pending = FocusOrStrike(seat=seat, candidates=sources + (STRIKE,))


def apply_focus_or_strike(
    game: GameState, request: FocusOrStrike, response: DecisionResponse
) -> None:
    """Carry out the answer to ``request``: a strike ends the focusing, and a focus hands the option
    to the other duelist."""
    duel = duel_in_progress(game)
    token = response.choices[0]
    if token == STRIKE:
        strike(game, request.seat)
        return
    # Queued before the focus, so that what a card does in reaction to the focus resolves before
    # the other duelist is asked.
    queue_duel_steps(game, OfferFocusOrStrike(duel.opponent_of(request.seat)))
    focus(game, request.seat, token)


def focus(game: GameState, seat: PlayerId, token: str) -> None:
    """Focus the card ``token`` names for ``seat``, counting it against the seat's own limit.

    What a focus does belongs to the arc's focus procedure, which may return effects of its own for
    the duel to resolve. Raise ``ValueError`` if ``token`` names no source this seat can focus
    with.
    """
    duel = duel_in_progress(game)
    effects = ruleset.ACTIVE.focus_procedure.focus(game, duel, seat, token)
    duel.focused[seat] = duel.focuses(seat) + 1
    if effects:
        triggers.resolve_effects(game, effects)
    # The card the procedure just moved, read off the area rather than off the token, since a token
    # is the procedure's own vocabulary. One focus moves one card today.
    focused = focused_cards(game, seat)
    if not focused:
        raise RuntimeError(f"{seat.name} focused {token!r} and its focusing area is empty")
    triggers.fire(game, CardFocused(seat=seat, card_id=focused[-1].id, focused=duel.focuses(seat)))


def strike(game: GameState, seat: PlayerId) -> None:
    """Strike for ``seat``, ending the focusing and queueing the steps the CR puts between the
    strike and the end of the duel."""
    # The steps import this module for the loop they follow, so importing them at the top would
    # close that cycle.
    from yasuki_core.engine.rules.duel.resolution import (
        AnnounceFocusEffectsResolved,
        ApplyDuelConsequences,
        DecideTheDuel,
        DiscardFocusedCards,
        EndTheDuel,
        RevealFocusedCards,
    )

    duel_in_progress(game)
    # The CR's order: the reveal, the Focus Effects it queues, the outcome, the duel's end, the
    # consequences that wait for it, then the discard. One step per announcement, so a question
    # asked on one is answered before the next is made.
    queue_duel_steps(
        game,
        RevealFocusedCards(),
        AnnounceFocusEffectsResolved(),
        DecideTheDuel(),
        EndTheDuel(),
        ApplyDuelConsequences(),
        DiscardFocusedCards(),
    )
    triggers.fire(game, StrikeDeclared(seat=seat))
