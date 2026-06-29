from dataclasses import dataclass
from typing import Final

from yasuki_core.engine.players import PlayerId
from yasuki_core.engine.table import TableState, ZoneKey, ZoneRole, DeckKey, BoardPos
from yasuki_core.game_pieces.cards import L5RCard
from yasuki_core.game_pieces.constants import Side


@dataclass(frozen=True, slots=True)
class HiddenCard:
    """A card the viewer may not identify, carrying only a stable id, its side (which back art to
    draw), its owner (whose card it is — public; only the face is secret), and a constant ``face``
    marker. The real name, text, and front image never reach this viewer's snapshot."""

    card_id: str
    side: Side
    owner: PlayerId | None = None
    face: str = "back"


CardView = L5RCard | HiddenCard


@dataclass(frozen=True, slots=True)
class SeatView:
    name: str
    honor: int
    ready: bool
    connected: bool
    avatar: dict | None = None


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
    # Ids of cards this viewer sees solely because they are peeking them — visible to the viewer alone,
    # so the client renders them with the reduced-opacity peek cue. Empty when nothing is being peeked.
    peeked_ids: frozenset[str] = frozenset()


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
    return HiddenCard(card_id=card.id, side=card.side, owner=card.owner)


def _opponent(seat: PlayerId) -> PlayerId:
    """The other seat at a two-seat table."""
    return PlayerId.P2 if seat is PlayerId.P1 else PlayerId.P1


def _shown_to(card: L5RCard, viewer: PlayerId) -> bool:
    """Whether ``card`` is shown to ``viewer`` as the owner's opponent — the disclosure a face-down
    card's owner makes to the other seat without turning the card face up."""
    return card.shown and card.owner is not None and viewer == _opponent(card.owner)


def _default_visible(card: L5RCard, viewer: PlayerId, role: ZoneRole | None) -> bool:
    """The baseline visibility before any show/peek disclosure: public discard/banish to all, the hand
    to its owner, and a face-up card on the battlefield (``role`` None) or in a province."""
    if role in _PUBLIC_ROLES:
        return True
    if role is ZoneRole.HAND:
        return card.owner == viewer
    return card.face_up


def _zone_card_visible(card: L5RCard, viewer: PlayerId, role: ZoneRole | None) -> bool:
    """Whether ``viewer`` may identify ``card`` sitting in ``role`` (None for the battlefield): by the
    baseline rule, because the owner shows it to this opponent, or because this viewer is peeking it."""
    return _default_visible(card, viewer, role) or _shown_to(card, viewer) or viewer in card.peekers


def _peeked_only(card: L5RCard, viewer: PlayerId, role: ZoneRole | None) -> bool:
    """Whether ``viewer`` sees ``card`` solely through their own peek — visible, but neither by the
    baseline rule nor through a show. These are the ids the snapshot flags for the peek cue."""
    return (
        viewer in card.peekers
        and not _default_visible(card, viewer, role)
        and not _shown_to(card, viewer)
    )


def card_identity_public(state: TableState, card_id: str) -> bool:
    """Return whether every seat may currently identify this card, given where it sits, its face, and
    any show. True for a battlefield or province card that is face up, for any card in a public discard
    or banish, and for a hand card its owner has shown (now public to all); False for a card in a deck,
    one lying face down to its owner, or one only an opponent or a peeker can see."""
    card = state.cards_by_id.get(card_id)
    if card is None:
        return False
    if any(held is card for held in state.battlefield.cards):
        return all(_zone_card_visible(card, seat, None) for seat in state.seats)
    for key, zone in state.zones.items():
        if any(held is card for held in zone.cards):
            return all(_zone_card_visible(card, seat, key.role) for seat in state.seats)
    return False  # in a deck or otherwise unlocated — hidden


def _project(card: L5RCard, visible: bool) -> CardView:
    return card if visible else _hide(card)


def redact(state: TableState, viewer: PlayerId) -> ViewSnapshot:
    """Project the authoritative table into the per-viewer view, replacing every card the viewer is
    not entitled to identify with a :class:`HiddenCard` stub.

    Visibility:

    - hand: the owner sees it; others see a back unless the owner has ``shown`` it (then public).
    - battlefield and provinces: a card is shown only when ``face_up`` — a face-down card is a back to
      everyone, its owner included, unless the owner has ``shown`` it to the other seat.
    - discards and banishes: public to both seats.
    - decks: count only, plus the top card when it has been flipped ``face_up``.

    A peeker sees any card it is peeking, whoever owns it; the returned snapshot records those ids in
    ``peeked_ids`` so the client marks them as a private peek.

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
        seat: SeatView(info.name, info.honor, info.ready, info.connected, info.avatar)
        for seat, info in state.seats.items()
    }
    peeked_ids: set[str] = set()
    zones = {}
    for key, zone in state.zones.items():
        views = []
        for card in zone.cards:
            views.append(_project(card, _zone_card_visible(card, viewer, key.role)))
            if _peeked_only(card, viewer, key.role):
                peeked_ids.add(card.id)
        zones[key] = ZoneView(tuple(views))
    decks = {}
    for key, deck in state.decks.items():
        top = deck.cards[-1] if deck.cards else None
        shown_top = top if top is not None and top.face_up else None
        decks[key] = DeckView(count=len(deck.cards), top=shown_top)
    battlefield_views = []
    for card in state.battlefield.cards:
        battlefield_views.append(
            BattlefieldCardView(
                _project(card, _zone_card_visible(card, viewer, None)),
                state.positions.get(card.id, BoardPos(0.0, 0.0)),
            )
        )
        if _peeked_only(card, viewer, None):
            peeked_ids.add(card.id)
    return ViewSnapshot(
        seq=state.seq,
        viewer=viewer,
        seats=seats,
        zones=zones,
        decks=decks,
        battlefield=tuple(battlefield_views),
        peeked_ids=frozenset(peeked_ids),
    )
