from dataclasses import dataclass, field, fields as dataclass_fields
from yasuki_core.engine.players import PlayerId
from yasuki_core.game_pieces.prints import CardPrint


@dataclass(frozen=True, slots=True)
class L5RCard:
    """One physical copy of a card in a game: its identity, its state, and the print it presents.

    Characteristics — name, keywords, printed stats — belong to the :class:`CardPrint` in
    ``printed``, which every copy of that card shares and none of them mutates. Reads forward, so
    ``card.gold_production`` answers from the print, but ``isinstance`` does not: ask
    ``isinstance(card.printed, HoldingPrint)`` for the card's type.

    A double-faced card carries both prints and flips by choosing between them, so its two faces
    are one card with one identity rather than a card nested inside another.
    """

    id: str
    printed: CardPrint
    owner: PlayerId | None = None
    bowed: bool = False
    face_up: bool = True
    inverted: bool = False
    # Named counters on the card (e.g. "wealth" → +1GP each): scalar host state, never cards
    # (docs/engine/counters-vs-cards.md). In equality — replay checks must see counter drift — but
    # out of the generated hash, which a dict cannot join.
    counters: dict[str, int] = field(default_factory=dict, hash=False)
    # Two distinct disclosures, both narrower than turning the card face up. ``shown`` marks a card the
    # owner has revealed to their opponent: a face-down card the opponent may then identify while its
    # owner still sees a back, or a hand card made public to all. ``peekers`` holds the seats privately
    # peeking at the card — each may identify it, nobody else learns what they saw.
    shown: bool = False
    peekers: frozenset[PlayerId] = frozenset()
    # The other face of a double-faced card, when its print could be resolved; ``showing_back``
    # selects which face this copy presents. Distinct from face_up, which conceals a card behind
    # its generic deck back.
    back_printed: CardPrint | None = None
    showing_back: bool = False
    # A sandbox piece spawned onto the table (SpawnCard), not a card drawn from a deck. Only tokens
    # may be removed from the table; a real card is never destroyed outright.
    is_token: bool = False
    # A free-text annotation a player wrote on the face-up card (e.g. "dead"), shown over its art. It
    # rides along while the card stays public — including into a discard — and clears on entering a deck.
    note: str | None = field(default=None, compare=False)

    @classmethod
    def of(cls, print_cls: type[CardPrint], **fields) -> "L5RCard":
        """Build a copy of the card ``print_cls`` describes, from one flat set of keyword arguments.

        Parameters
        ----------
        print_cls : type of CardPrint
            The print class describing the card, which picks the print built.
        **fields
            The card's printed characteristics and its per-copy state, in one namespace. Each name
            goes to whichever half declares it.
        """
        printed_names = {f.name for f in dataclass_fields(print_cls)}
        printed = {name: fields.pop(name) for name in list(fields) if name in printed_names}
        return cls(printed=print_cls(**printed), **fields)

    def __getattr__(self, name: str):
        """Answer a printed characteristic off the print this copy presents."""
        # printed lives in a slot, so it is missing until __init__ sets it; without this guard a
        # read during construction would recurse here forever.
        try:
            printed = object.__getattribute__(self, "printed")
        except AttributeError:
            raise AttributeError(name) from None
        try:
            return getattr(printed, name)
        except AttributeError:
            # Reported against the card, not the print: whoever hit this was reading a card.
            raise AttributeError(
                f"{type(self).__name__!r} object has no attribute {name!r}"
            ) from None

    def __post_init__(self):
        if not isinstance(self.peekers, frozenset):
            object.__setattr__(self, "peekers", frozenset(self.peekers))
        # Always copy: replace()-built cards (e.g. synthetic back faces) must not share the mutable
        # tally with their source.
        object.__setattr__(self, "counters", dict(self.counters))

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
        if self.printed.back_card_id is not None:
            object.__setattr__(self, "showing_back", not self.showing_back)

    @property
    def active_face(self) -> CardPrint:
        """The print currently presented: the back one when flipped to it, otherwise this copy's."""
        if self.showing_back and self.back_printed is not None:
            return self.back_printed
        return self.printed
