from dataclasses import dataclass

from yasuki_core import ruleset
from yasuki_core.engine import ops
from yasuki_core.engine.players import PlayerId
from yasuki_core.engine.rules import triggers
from yasuki_core.engine.rules.duel.focusing import focused_cards
from yasuki_core.engine.rules.duel.records import DuelRecord, DuelStep, DuelWork
from yasuki_core.engine.rules.state import GameState
from yasuki_core.engine.rules.stats.calculation import effective_stat
from yasuki_core.engine.rules.vocabulary.game_events import (
    CardFocused,
    DeclaringDuel,
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


def duel_being_fought(game: GameState) -> DuelRecord | None:
    """The duel being fought, or None where none is. A duel that has ended is not one being fought,
    though its record stays on the game for whatever resolves afterwards to read."""
    duel = game.duel
    return None if duel is None or duel.step is DuelStep.ENDED else duel


def duel_in_progress(game: GameState) -> DuelRecord:
    """The duel being fought. Raise ``RuntimeError`` where none is, since every caller here is part
    of a duel's own procedure and has no second thing to mean."""
    duel = duel_being_fought(game)
    if duel is None:
        raise RuntimeError("no duel is being fought")
    return duel


def challenge_is_legal(game: GameState, challenger_duelist: str, challenged_duelist: str) -> bool:
    """Whether a challenge between these two cards happens at all (CR, Challenge): it does not where
    one player controls both, nor where either card is not a Personality.

    An id naming no card on the table is refused too, which is what a Personality that left play
    between being targeted and the duel being declared amounts to.
    """
    challenger = game.table.cards_by_id.get(challenger_duelist)
    challenged = game.table.cards_by_id.get(challenged_duelist)
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
    with the Personalities they belong to. Return the events the focus procedure's setup raises, for
    the caller's cascade to drain.

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
    duel.step = DuelStep.FOCUSING
    challenger_stat = duel_stat(game, game.table.cards_by_id[challenger_duelist])
    challenged_stat = duel_stat(game, game.table.cards_by_id[challenged_duelist])
    # The option is queued before the setup runs and before the window is announced, so that work
    # either of them pushes sits above it and resolves before the first seat is asked.
    game.stack.append(OfferFocusOrStrike(challenged))
    events: list[GameEvent] = []
    for effect in ruleset.ACTIVE.focus_procedure.begin(game, duel):
        events.extend(triggers.apply_effect(game, effect))
    return [
        *events,
        _declaration(duel, DeclaringDuel, challenger_stat, challenged_stat),
        _declaration(duel, DuelDeclared, challenger_stat, challenged_stat),
    ]


def _declaration[EventT: DeclaringDuel | DuelDeclared](
    duel: DuelRecord, kind: type[EventT], challenger_stat: int, challenged_stat: int
) -> EventT:
    """``kind`` built from ``duel`` and the duel stats it begins on. The two declaration events carry
    the same fields, since one opens the window the other closes."""
    return kind(
        challenger=duel.challenger,
        challenged=duel.challenged,
        challenger_duelist=duel.challenger_duelist,
        challenged_duelist=duel.challenged_duelist,
        source_card_id=duel.source,
        challenger_stat=challenger_stat,
        challenged_stat=challenged_stat,
    )


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
    """The stat this duel compares for ``card``, which is the ruleset's ``duel_stat_default`` until a
    card overrides it per duel or per Personality (CR, Duel Stat)."""
    return effective_stat(game, card, ruleset.ACTIVE.duel_stat_default)


def focus_sources(game: GameState, duel: DuelRecord, seat: PlayerId) -> tuple[str, ...]:
    """What ``seat`` may focus with right now, as this arc's focus procedure offers it. Empty for a
    seat the procedure permits no focus, which leaves it nothing to do but strike."""
    return ruleset.ACTIVE.focus_procedure.sources(game, duel, seat)


def offer_focus_or_strike(game: GameState, seat: PlayerId) -> None:
    """Ask ``seat`` to focus a card or to strike, or strike for it where it has nothing to focus
    with. A seat that cannot focus is not asked: the CR gives it no other option, and a question
    with one answer is not a decision."""
    duel = duel_in_progress(game)
    sources = focus_sources(game, duel, seat)
    if not sources:
        strike(game, seat)
        return
    duel.option = seat
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
    game.stack.append(OfferFocusOrStrike(duel.opponent_of(request.seat)))
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
        DecideTheDuel,
        EndTheDuel,
        RevealFocusedCards,
    )

    duel = duel_in_progress(game)
    duel.struck = seat
    duel.option = None
    # Pushed in reverse, so they run in the CR's order: reveal, then the outcome, then the end.
    game.stack.extend((EndTheDuel(), DecideTheDuel(), RevealFocusedCards()))
    triggers.fire(game, StrikeDeclared(seat=seat))
