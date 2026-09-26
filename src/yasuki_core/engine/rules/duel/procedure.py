from dataclasses import dataclass

from yasuki_core import ruleset
from yasuki_core.engine import ops
from yasuki_core.engine.players import PlayerId
from yasuki_core.engine.rules.duel.records import DuelRecord, DuelStep, DuelWork
from yasuki_core.engine.rules.state import GameState
from yasuki_core.engine.rules.vocabulary.decisions import (
    DECK_TOP,
    STRIKE,
    DecisionResponse,
    FocusOrStrike,
    focus_source,
    focus_token,
)
from yasuki_core.engine.table import DeckKey, ZoneKey, ZoneRole
from yasuki_core.game_pieces.cards import L5RCard
from yasuki_core.game_pieces.constants import Side
from yasuki_core.game_pieces.prints import PersonalityPrint


def current_duel(game: GameState) -> DuelRecord | None:
    """The duel on the game, being fought or already ended, or None before the first one."""
    return game.duel


def duel_in_progress(game: GameState) -> DuelRecord:
    """The duel being fought. Raise ``RuntimeError`` where none is, since every caller here is part
    of a duel's own procedure and has no second thing to mean. A duel that has ended is not one
    being fought, however long its record stays on the game."""
    duel = game.duel
    if duel is None or duel.step is DuelStep.ENDED:
        raise RuntimeError("no duel is being fought")
    return duel


def challenge_is_legal(game: GameState, challenger_duelist: str, challenged_duelist: str) -> bool:
    """Whether a challenge between these two cards happens at all (CR, Challenge): it does not where
    one player controls both, nor where either card is not a Personality.

    A card that has left play since it was targeted names nothing here and is refused with them.
    """
    challenger = game.table.cards_by_id.get(challenger_duelist)
    challenged = game.table.cards_by_id.get(challenged_duelist)
    if challenger is None or challenged is None:
        return False
    if not isinstance(challenger.printed, PersonalityPrint):
        return False
    if not isinstance(challenged.printed, PersonalityPrint):
        return False
    return challenger.owner is not challenged.owner


def declare_duel(
    game: GameState,
    *,
    challenger: PlayerId,
    challenged: PlayerId,
    challenger_duelist: str,
    challenged_duelist: str,
    source: str,
) -> None:
    """Begin a duel between the two named Personalities and open the focusing, whose first option
    belongs to the challenged seat (CR, Duel).

    Do nothing where :func:`~.challenge_is_legal` refuses the challenge, which is the CR's own
    wording: such a challenge does not happen, rather than happening and failing.

    The focusing areas are created here and dropped when the duel ends, so a seat outside a duel has
    none.

    Raise ``RuntimeError`` where a duel is already being fought. One effect that creates several
    duels fights them one after another (CR, Duration), which nothing models: a duel is one of
    several procedures a single effect may have to run in sequence, each of which can pause, and
    that belongs to one mechanism rather than to a queue of this procedure's own. Nothing
    Shattered Empire-legal reaches it, since Wanton Destruction (Training Grounds) is the only card
    in the corpus that duels twice.
    """
    if not challenge_is_legal(game, challenger_duelist, challenged_duelist):
        return
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
    game.stack.append(OfferFocusOrStrike(challenged))


@dataclass(frozen=True, slots=True)
class OfferFocusOrStrike(DuelWork):
    """Put the focus-or-strike option to ``seat``.

    A work item, because the option is a question the procedure pauses for: the duel is declared
    inside an action's cascade, and the loop picks up again on each answer.
    """

    seat: PlayerId

    def resume(self, game: GameState) -> None:
        offer_focus_or_strike(game, self.seat)


def focus_sources(game: GameState, duel: DuelRecord, seat: PlayerId) -> tuple[str, ...]:
    """The tokens ``seat`` may focus with right now: one per card in its hand, and the top of its
    Fate deck where it has one. Empty for a seat that has focused as often as the ruleset's
    ``focus_limit`` allows, which leaves it nothing to do but strike."""
    limit = ruleset.ACTIVE.focus_limit
    if limit is not None and duel.focuses(seat) >= limit:
        return ()
    hand = game.table.zones[ZoneKey(seat, ZoneRole.HAND)]
    sources = [focus_token(card.id) for card in hand.cards]
    if game.table.decks[DeckKey(seat, Side.FATE)].cards:
        sources.append(DECK_TOP)
    return tuple(sources)


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
    focus(game, request.seat, token)
    game.stack.append(OfferFocusOrStrike(duel.opponent_of(request.seat)))


def focus(game: GameState, seat: PlayerId, token: str) -> None:
    """Focus the card ``token`` names into ``seat``'s focusing area, face down.

    The card is peeked back to the seat that focused it, whichever source it came from: a player
    may read every card in its own focusing area, and may not read another player's (CR, Focusing
    Area). One taken off the Fate deck is taken unseen and becomes readable once it has landed,
    which is what stops a seat choosing to focus it on what it turns out to be.

    Raise ``ValueError`` if ``token`` names no source this seat can focus with.
    """
    duel = duel_in_progress(game)
    card = _source_card(game, seat, token)
    ops.move_card(game.table, card, ZoneKey(seat, ZoneRole.FOCUS))
    card.turn_face_down()
    card.clear_peekers()
    card.add_peeker(seat)
    duel.focused[seat] = duel.focuses(seat) + 1


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


def focused_cards(game: GameState, seat: PlayerId) -> tuple[L5RCard, ...]:
    """What ``seat`` has focused, in the order it focused them. Empty for a seat with no focusing
    area, which is every seat outside a duel."""
    zone = game.table.zones.get(ZoneKey(seat, ZoneRole.FOCUS))
    return () if zone is None else tuple(zone.cards)


def _source_card(game: GameState, seat: PlayerId, token: str) -> L5RCard:
    """The card ``token`` names, as :func:`~.focus_sources` offered it."""
    if token == DECK_TOP:
        deck = game.table.decks[DeckKey(seat, Side.FATE)]
        if not deck.cards:
            raise ValueError(f"{seat.name} has no Fate card to focus off the deck")
        return deck.cards[-1]
    card_id = focus_source(token)
    hand = game.table.zones[ZoneKey(seat, ZoneRole.HAND)]
    for card in hand.cards:
        if card.id == card_id:
            return card
    raise ValueError(f"{card_id!r} is not in {seat.name}'s hand to focus")
