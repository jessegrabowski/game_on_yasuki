from collections.abc import Callable, Iterable
from dataclasses import dataclass
from typing import Generic, TypeVar

from numpy.random import Generator

from yasuki_core.game_pieces.cards import L5RCard
from yasuki_core.game_pieces.prints import DynastyPrint, FatePrint


CardT = TypeVar("CardT", bound=L5RCard)


@dataclass
class Deck(Generic[CardT]):
    """A simple LIFO deck abstraction where the "top" is the end of the list."""

    cards: list[CardT]

    def __len__(self) -> int:
        return len(self.cards)

    @classmethod
    def build(cls, cards: Iterable[CardT]) -> "Deck[CardT]":
        return cls(list(cards))

    def shuffle(self, rng: Generator) -> None:
        """Shuffle in place, drawing from ``rng`` so the caller owns the stream."""
        rng.shuffle(self.cards)

    def draw_one(self) -> CardT | None:
        if not self.cards:
            return None
        return self.cards.pop()

    def draw(self, n: int) -> list[CardT]:
        drawn_cards = []
        for _ in range(n):
            card = self.draw_one()
            if card is None:
                break
            drawn_cards.append(card)
        return drawn_cards

    def peek(self, n: int) -> list[CardT]:
        if n <= 0:
            return []
        return self.cards[-n:] if n <= len(self.cards) else self.cards[:]

    def search(self, predicate: Callable[[CardT], bool]) -> list[CardT]:
        return [card for card in self.cards if predicate(card)]

    def add_to_top(self, cards: Iterable[CardT]) -> None:
        self.cards.extend(cards)

    def add_to_bottom(self, cards: Iterable[CardT]) -> None:
        self.cards = [*cards, *self.cards]


@dataclass
class FateDeck(Deck[L5RCard]):
    @classmethod
    def build(cls, cards: Iterable[L5RCard]) -> "FateDeck":
        cards = list(cards)
        if not all(isinstance(c.printed, FatePrint) for c in cards):
            raise ValueError("Every card must present a Fate print")
        return cls(cards)


@dataclass
class DynastyDeck(Deck[L5RCard]):
    @classmethod
    def build(cls, cards: Iterable[L5RCard]) -> "DynastyDeck":
        cards = list(cards)
        if not all(isinstance(c.printed, DynastyPrint) for c in cards):
            raise ValueError("Every card must present a Dynasty print")
        return cls(cards)
