from typing import TypeVar, Generic
from collections.abc import Iterable, Callable

from app.game_pieces.cards import L5RCard
from dataclasses import dataclass
import random

from app.game_pieces.dynasty import DynastyCard
from app.game_pieces.fate import FateCard

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

    def shuffle(self, seed: int | None = None) -> None:
        rng = random.Random(seed)
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
class FateDeck(Deck[FateCard]):
    @classmethod
    def build(cls, cards: Iterable[FateCard]) -> "FateDeck":
        cards = list(cards)
        if not all(isinstance(c, FateCard) for c in cards):
            raise ValueError("All cards must be FateCard instances")
        return cls(cards)


@dataclass
class DynastyDeck(Deck[DynastyCard]):
    @classmethod
    def build(cls, cards: Iterable[DynastyCard]) -> "DynastyDeck":
        cards = list(cards)
        if not all(isinstance(c, DynastyCard) for c in cards):
            raise ValueError("All cards must be DynastyCard instances")
        return cls(cards)
