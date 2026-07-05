from dataclasses import dataclass, field
from pathlib import Path
from yasuki_core.game_pieces.constants import Side
from yasuki_core.engine.players import PlayerId


@dataclass(frozen=True, slots=True)
class L5RCard:
    id: str
    name: str
    side: Side
    # The card's stable printed identity — the database card slug (e.g. "ancestral_estate"), shared
    # by every copy and printing, distinct from the per-instance ``id``. Per-card effect handlers key
    # off it; None for fabricated demo cards and spawned tokens, which fall back to plain behavior.
    printed_id: str | None = None
    clan: str | None = None
    keywords: tuple[str, ...] = ()
    traits: tuple[str, ...] = ()
    text: str = ""
    is_unique: bool = False
    bowed: bool = False
    face_up: bool = True
    inverted: bool = False
    # Named counters on the card (e.g. "wealth" → +1GP each): scalar host state, never cards
    # (docs/engine/counters-vs-cards.md). In equality — replay checks must see counter drift — but
    # out of the generated hash, which a dict cannot join.
    counters: dict[str, int] = field(default_factory=dict, hash=False)
    image_front: Path | None = None
    image_back: Path | None = None
    owner: PlayerId | None = None
    # Two distinct disclosures, both narrower than turning the card face up. ``shown`` marks a card the
    # owner has revealed to their opponent: a face-down card the opponent may then identify while its
    # owner still sees a back, or a hand card made public to all. ``peekers`` holds the seats privately
    # peeking at the card — each may identify it, nobody else learns what they saw.
    shown: bool = False
    peekers: frozenset[PlayerId] = frozenset()
    # Double-faced cards (e.g. flip strongholds): back_card_id links the other face, back holds it as
    # a resolved card when available, and showing_back selects which face is presented. Distinct from
    # face_up, which conceals a card behind its generic deck back.
    back_card_id: str | None = None
    back: "L5RCard | None" = None
    showing_back: bool = False
    # A sandbox piece spawned onto the table (SpawnCard), not a card drawn from a deck. Only tokens
    # may be removed from the table; a real card is never destroyed outright.
    is_token: bool = False
    # An art-swap payload when the deck entry borrows another printing's art for the front: the donor
    # image and both frames' (era, layout) plus the recipient keywords, all the browser canvas needs to
    # recomposite it. Pure client-render metadata, so it stays out of card identity (compare=False).
    art_swap: dict | None = field(default=None, compare=False)
    # A free-text annotation a player wrote on the face-up card (e.g. "dead"), shown over its art. It
    # rides along while the card stays public — including into a discard — and clears on entering a deck.
    note: str | None = field(default=None, compare=False)

    def __post_init__(self):
        # Normalize collections to tuples for consistent immutability
        if not isinstance(self.keywords, tuple):
            object.__setattr__(self, "keywords", tuple(self.keywords))
        if not isinstance(self.traits, tuple):
            object.__setattr__(self, "traits", tuple(self.traits))
        if not isinstance(self.peekers, frozenset):
            object.__setattr__(self, "peekers", frozenset(self.peekers))

    # State transitions
    def bow(self) -> None:
        if not self.bowed:
            object.__setattr__(self, "bowed", True)

    def unbow(self) -> None:
        if self.bowed:
            object.__setattr__(self, "bowed", False)

    def adjust_counter(self, name: str, delta: int) -> None:
        """Add ``delta`` to the named counter, flooring at zero. A zeroed counter is removed, so
        cards with the same effective state compare and serialize identically."""
        count = max(0, self.counters.get(name, 0) + delta)
        if count:
            self.counters[name] = count
        else:
            self.counters.pop(name, None)

    def set_note(self, text: str | None) -> None:
        object.__setattr__(self, "note", text or None)

    def set_owner(self, owner: PlayerId | None) -> None:
        object.__setattr__(self, "owner", owner)

    def turn_face_up(self) -> None:
        if not self.face_up:
            object.__setattr__(self, "face_up", True)

    def turn_face_down(self) -> None:
        if self.face_up:
            object.__setattr__(self, "face_up", False)

    def flip(self) -> None:
        object.__setattr__(self, "face_up", not self.face_up)

    def invert(self) -> None:
        if not self.inverted:
            object.__setattr__(self, "inverted", True)

    def uninvert(self) -> None:
        if self.inverted:
            object.__setattr__(self, "inverted", False)

    def show(self) -> None:
        if not self.shown:
            object.__setattr__(self, "shown", True)

    def unshow(self) -> None:
        if self.shown:
            object.__setattr__(self, "shown", False)

    def add_peeker(self, seat: PlayerId) -> None:
        if seat not in self.peekers:
            object.__setattr__(self, "peekers", self.peekers | {seat})

    def remove_peeker(self, seat: PlayerId) -> None:
        if seat in self.peekers:
            object.__setattr__(self, "peekers", self.peekers - {seat})

    def clear_peekers(self) -> None:
        if self.peekers:
            object.__setattr__(self, "peekers", frozenset())

    def flip_face(self) -> None:
        if self.back_card_id is not None:
            object.__setattr__(self, "showing_back", not self.showing_back)

    @property
    def active_face(self) -> "L5RCard":
        """The face currently presented: the back card when flipped to it, otherwise this card."""
        if self.showing_back and self.back is not None:
            return self.back
        return self
