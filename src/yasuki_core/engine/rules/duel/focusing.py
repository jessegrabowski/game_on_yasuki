from dataclasses import dataclass
from typing import Protocol

from yasuki_core.engine import ops
from yasuki_core.engine.players import PlayerId
from yasuki_core.engine.rules.duel.records import DuelRecord
from yasuki_core.engine.rules.effects import Effect
from yasuki_core.engine.rules.state import GameState
from yasuki_core.engine.rules.vocabulary.decisions import DECK_TOP, focus_source, focus_token
from yasuki_core.engine.table import DeckKey, ZoneKey, ZoneRole
from yasuki_core.game_pieces.cards import L5RCard
from yasuki_core.game_pieces.constants import Side


def focused_cards(game: GameState, seat: PlayerId) -> tuple[L5RCard, ...]:
    """What ``seat`` has focused, in the order it focused them. Empty for a seat with no focusing
    area, which is every seat outside a duel."""
    zone = game.table.zones.get(ZoneKey(seat, ZoneRole.FOCUS))
    return () if zone is None else tuple(zone.cards)


def focus_value(card: L5RCard) -> int:
    """The Focus Value printed on ``card``, or zero where it prints none. A card with no printed
    Focus Value contributes nothing rather than refusing to be focused: what may be focused is the
    focus procedure's business, and this only reads what was."""
    printed = getattr(card.printed, "focus", None)
    return printed if isinstance(printed, int) else 0


class FocusProcedure(Protocol):
    """How one arc's duels are focused, which is the part of dueling that changed between arcs while
    the skeleton around it did not.

    A procedure owns what may be focused, how many times, and what focusing one card does. It does
    not own the challenge, the alternation, the strike, the reveal, the totals or the consequences:
    those are the same in every era and belong to the duel itself.

    Every method that acts returns the effects the duel resolves, so a procedure can grant an
    ongoing modifier as a card is focused rather than only move it. An implementation is a stateless
    frozen singleton, since :class:`~yasuki_core.ruleset.Ruleset` is swappable data and per-duel
    state kept on a procedure would be state replay cannot see.
    """

    @property
    def focus_limit(self) -> int | None:
        """How many times one seat may focus in a duel, or None where the arc caps it only by what
        the seat has to focus with."""
        ...

    def begin(self, game: GameState, duel: DuelRecord) -> list[Effect]:
        """Set the duel's focusing up, before the first seat is asked to focus or strike."""
        ...

    def sources(self, game: GameState, duel: DuelRecord, seat: PlayerId) -> tuple[str, ...]:
        """The tokens ``seat`` may focus with right now, which is what :class:`~.FocusOrStrike`
        offers it. Empty for a seat that may not focus at all, which leaves it only the strike."""
        ...

    def focus(self, game: GameState, duel: DuelRecord, seat: PlayerId, token: str) -> list[Effect]:
        """Focus the card ``token`` names for ``seat``, and return the effects that follow."""
        ...

    def focus_total(self, game: GameState, duel: DuelRecord, seat: PlayerId) -> int:
        """What ``seat``'s focused cards add to its duel stat at the reveal. Zero for a procedure
        that applied each Focus Value as its card was focused rather than totaling at the end."""
        ...

    def cleanup(self, game: GameState, duel: DuelRecord) -> list[Effect]:
        """The effects the duel's ending owes this procedure, read once the outcome is recorded."""
        ...


@dataclass(frozen=True, slots=True)
class TwentyFestivalsFocusing:
    """Focusing as the Twenty Festivals CR states it: from hand or unseen off the Fate deck, four
    times per seat, with nothing to set up and nothing owed at the end (CR, Duel)."""

    focus_limit: int | None = 4

    def begin(self, game: GameState, duel: DuelRecord) -> list[Effect]:
        return []

    def sources(self, game: GameState, duel: DuelRecord, seat: PlayerId) -> tuple[str, ...]:
        if self.focus_limit is not None and duel.focuses(seat) >= self.focus_limit:
            return ()
        hand = game.table.zones[ZoneKey(seat, ZoneRole.HAND)]
        sources = [focus_token(card.id) for card in hand.cards]
        if game.table.decks[DeckKey(seat, Side.FATE)].cards:
            sources.append(DECK_TOP)
        return tuple(sources)

    def focus(self, game: GameState, duel: DuelRecord, seat: PlayerId, token: str) -> list[Effect]:
        """Move the card into ``seat``'s focusing area face down and peek it back to that seat.

        A player may read every card in its own focusing area and may not read another player's (CR,
        Focusing Area). One taken off the Fate deck is chosen unseen and read once it has landed, so
        the seat commits to it before learning what it is.

        Raise ``ValueError`` if ``token`` names no source this seat can focus with.
        """
        card = self._source_card(game, seat, token)
        ops.move_card(game.table, card, ZoneKey(seat, ZoneRole.FOCUS))
        card.turn_face_down()
        card.clear_peekers()
        card.add_peeker(seat)
        return []

    def focus_total(self, game: GameState, duel: DuelRecord, seat: PlayerId) -> int:
        return sum(focus_value(card) for card in focused_cards(game, seat))

    def cleanup(self, game: GameState, duel: DuelRecord) -> list[Effect]:
        return []

    def _source_card(self, game: GameState, seat: PlayerId, token: str) -> L5RCard:
        """The card ``token`` names, as :meth:`sources` offered it."""
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


TWENTY_FESTIVALS_FOCUSING = TwentyFestivalsFocusing()
