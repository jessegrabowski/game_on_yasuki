from collections.abc import Iterator
from dataclasses import dataclass

from yasuki_core.engine.players import PlayerId
from yasuki_core.engine.redaction import redact, ViewSnapshot
from yasuki_core.engine.rules.economy import effective_stat
from yasuki_core.engine.rules.modifiers import Stat
from yasuki_core.engine.rules.state import GameState, Phase
from yasuki_core.engine.rules.decisions import DecisionRequest
from yasuki_core.engine.rules.legality import legacy_candidates
from yasuki_core.engine.table import DeckKey
from yasuki_core.game_pieces.cards import L5RCard
from yasuki_core.game_pieces.constants import Side


@dataclass(frozen=True, slots=True)
class GameView:
    """A per-seat projection of a :class:`GameState` — everything one seat is entitled to see.

    The table is redacted for the viewer (the opponent's hand, face-down cards, and deck contents
    appear as backs); the turn-level rules fields are public to both seats; and a pending decision
    reaches only the seat that must answer it.

    Attributes
    ----------
    viewer : PlayerId
        The seat this view is built for.
    table : ViewSnapshot
        The viewer's redacted view of the board.
    turn : int
        The current turn number.
    active : PlayerId
        The seat whose turn it is.
    phase : Phase
        The current phase.
    first_player : PlayerId
        The seat that took the first turn.
    gold : dict mapping PlayerId to int
        Every seat's gold pool — public to both seats.
    favor_holder : PlayerId or None
        The seat holding the Imperial Favor, or None.
    pending : DecisionRequest or None
        The decision the viewer must answer, or None when nothing is awaited from this viewer —
        including when the engine is instead waiting on the other seat.
    legacy_pool : tuple of L5RCard
        The viewer's own Legacy cards a search would still find, sorted by card id rather than left
        in deck order. Empty means a Legacy search would whiff and lose the game. Never populated
        for the other seat.
    dynasty_deck : tuple of L5RCard
        The cards left in the viewer's own dynasty deck, sorted by card id rather than left in deck
        order. A seat built its deck and so knows what remains in it; where those cards sit in the
        shuffle is the part it must not learn, which is what the sort strips. Never populated for
        the other seat.
    stats : dict mapping str to dict
        Each modified card's effective stats by id, the inner dict keyed by :class:`Stat`. Read it
        through :meth:`stat` rather than directly — a card no modifier reaches is absent, and the
        method supplies its printed value.
    """

    viewer: PlayerId
    table: ViewSnapshot
    turn: int
    active: PlayerId
    phase: Phase
    first_player: PlayerId
    gold: dict[PlayerId, int]
    favor_holder: PlayerId | None
    pending: DecisionRequest | None
    legacy_pool: tuple[L5RCard, ...]
    dynasty_deck: tuple[L5RCard, ...]
    stats: dict[str, dict[Stat, int]]

    def stat(self, card: L5RCard, stat: Stat) -> int:
        """``card``'s effective ``stat`` — counters, granted modifiers and all. Reading the card's
        own attribute instead yields the printed number, since modifiers live on the game.
        """
        modified = self.stats.get(card.id)
        if modified is not None:
            return modified[stat]
        printed = getattr(card, stat.value, None)
        return 0 if printed is None else printed  # absent, or printed as a dash


def _identifiable_ids(table: ViewSnapshot) -> set[str]:
    """The ids ``table`` lets its viewer identify. A card redacted to a :class:`HiddenCard`, and one
    the snapshot omits, are both absent — the snapshot has already decided entitlement, and reading
    it back is what keeps that decision in one place."""
    ids = {
        card.id for zone in table.zones.values() for card in zone.cards if isinstance(card, L5RCard)
    }
    ids.update(entry.card.id for entry in table.battlefield if isinstance(entry.card, L5RCard))
    ids.update(deck.top.id for deck in table.decks.values() if deck.top is not None)
    return ids


def _modified_cards(game: GameState, identifiable: set[str]) -> Iterator[L5RCard]:
    """Every identifiable card a counter or a recorded modifier reaches.

    A card neither touches has only its printed stats, which :meth:`GameView.stat` reads straight
    off it. A card the viewer may not identify is skipped: its stats would say what it is, and a
    view carries only what its seat is entitled to.
    """
    seen: set[str] = set()
    for card in game.table.cards_by_id.values():
        if card.counters and card.id in identifiable:
            seen.add(card.id)
            yield card
    for modifier in game.modifiers:
        if modifier.target_id in seen or modifier.target_id not in identifiable:
            continue
        target = game.table.cards_by_id.get(modifier.target_id)
        if target is not None:
            seen.add(target.id)
            yield target


def project(game: GameState, viewer: PlayerId) -> GameView:
    """Project ``game`` into the view ``viewer`` is entitled to: the board redacted for the viewer,
    the public rules fields, the pending decision only if this viewer is the one to answer it, the
    viewer's own Legacy pool and remaining dynasty deck, and the effective stats of every card
    carrying a modifier."""
    pending = game.pending if game.pending is not None and game.pending.seat is viewer else None
    table = redact(game.table, viewer)
    return GameView(
        viewer=viewer,
        table=table,
        turn=game.turn,
        active=game.active,
        phase=game.phase,
        first_player=game.first_player,
        gold=dict(game.gold),
        favor_holder=game.favor_holder,
        pending=pending,
        legacy_pool=tuple(sorted(legacy_candidates(game, viewer), key=lambda card: card.id)),
        dynasty_deck=tuple(
            sorted(game.table.decks[DeckKey(viewer, Side.DYNASTY)].cards, key=lambda card: card.id)
        ),
        stats={
            card.id: {stat: effective_stat(game, card, stat) for stat in Stat}
            for card in _modified_cards(game, _identifiable_ids(table))
        },
    )
