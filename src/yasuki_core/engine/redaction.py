from dataclasses import dataclass
from typing import Final

from yasuki_core.engine.players import PlayerId
from yasuki_core.engine.table import (
    TableState,
    ZoneKey,
    ZoneRole,
    DeckKey,
    BoardPos,
)
from yasuki_core.game_pieces.cards import L5RCard
from yasuki_core.game_pieces.constants import Side


@dataclass(frozen=True, slots=True)
class HiddenCard:
    """A card the viewer may not identify, carrying only a stable id, its side (which back art to
    draw), and a constant ``face`` marker. The real name, text, and front image never reach this
    viewer's snapshot."""

    card_id: str
    side: Side
    face: str = "back"


CardView = L5RCard | HiddenCard


@dataclass(frozen=True, slots=True)
class SeatView:
    name: str
    honor: int
    ready: bool
    connected: bool


@dataclass(frozen=True, slots=True)
class ZoneView:
    cards: tuple[CardView, ...]


@dataclass(frozen=True, slots=True)
class DeckView:
    count: int
    top: L5RCard | None  # the real top card only when it has been flipped face up


@dataclass(frozen=True, slots=True)
class BattlefieldCardView:
    card: CardView
    pos: BoardPos


@dataclass(frozen=True, slots=True)
class ViewSnapshot:
    seq: int
    viewer: PlayerId
    seats: dict[PlayerId, SeatView]
    zones: dict[ZoneKey, ZoneView]
    decks: dict[DeckKey, DeckView]
    battlefield: tuple[BattlefieldCardView, ...]


# Zones whose contents are public to both seats.
_PUBLIC_ROLES: Final = frozenset(
    {
        ZoneRole.FATE_DISCARD,
        ZoneRole.FATE_BANISH,
        ZoneRole.DYNASTY_DISCARD,
        ZoneRole.DYNASTY_BANISH,
    }
)


def _hide(card: L5RCard) -> HiddenCard:
    return HiddenCard(card_id=card.id, side=card.side)


def _zone_card_visible(card: L5RCard, viewer: PlayerId, role: ZoneRole) -> bool:
    if role in _PUBLIC_ROLES:
        return True
    if role is ZoneRole.HAND:
        # The hand is private to its owner; face_up does not enter here.
        return card.owner == viewer or card.revealed
    # Provinces (and any other owned table zone): a face-down card is a back to everyone, owner
    # included, until it is flipped face up or explicitly revealed.
    return card.face_up or card.revealed


def _project(card: L5RCard, visible: bool) -> CardView:
    return card if visible else _hide(card)


def redact(state: TableState, viewer: PlayerId) -> ViewSnapshot:
    """Project the authoritative table into the per-viewer view, replacing every card the viewer is
    not entitled to identify with a :class:`HiddenCard` stub.

    Visibility:

    - hand: the owner sees it; others see a back unless the card is ``revealed``.
    - battlefield and provinces: a card is shown only when ``face_up`` or ``revealed`` — a face-down
      card is a back to everyone, its owner included.
    - discards and banishes: public to both seats.
    - decks: count only, plus the top card when it has been flipped ``face_up``.

    Card ids survive redaction so a client can animate a card it cannot yet identify (an opponent's
    draw is a back sliding from deck to hand).

    Parameters
    ----------
    state : TableState
        The authoritative table.
    viewer : PlayerId
        The seat the snapshot is built for.
    """
    seats = {
        seat: SeatView(info.name, info.honor, info.ready, info.connected)
        for seat, info in state.seats.items()
    }
    zones = {
        key: ZoneView(
            tuple(_project(card, _zone_card_visible(card, viewer, key.role)) for card in zone.cards)
        )
        for key, zone in state.zones.items()
    }
    decks = {}
    for key, deck in state.decks.items():
        top = deck.cards[-1] if deck.cards else None
        shown_top = top if top is not None and top.face_up else None
        decks[key] = DeckView(count=len(deck.cards), top=shown_top)
    battlefield = tuple(
        BattlefieldCardView(
            _project(card, card.face_up or card.revealed),
            state.positions.get(card.id, BoardPos(0.0, 0.0)),
        )
        for card in state.battlefield.cards
    )
    return ViewSnapshot(
        seq=state.seq,
        viewer=viewer,
        seats=seats,
        zones=zones,
        decks=decks,
        battlefield=battlefield,
    )
