from dataclasses import dataclass, field
from collections.abc import Iterable
import math

from app.game_pieces.cards import L5RCard
from app.game_pieces.constants import Side


@dataclass(slots=True)
class Zone:
    name: str
    allowed_side: Side | None = None  # None = any
    cards: list[L5RCard] = field(default_factory=list)
    max_capacity: float = math.inf

    def __len__(self) -> int:
        return len(self.cards)

    def has_capacity(self) -> bool:
        return len(self.cards) < self.max_capacity

    def add(self, card: L5RCard) -> bool:
        if self.allowed_side is not None and card.side is not self.allowed_side:
            return False
        if not self.has_capacity():
            return False
        self.cards.append(card)
        return True

    def add_many(self, cards: Iterable[L5RCard]) -> int:
        added = 0
        for c in cards:
            if self.add(c):
                added += 1
        return added

    def remove(self, card: L5RCard) -> bool:
        try:
            self.cards.remove(card)
            return True
        except ValueError:
            return False

    def clear(self) -> None:
        self.cards.clear()


# Specific zones
@dataclass(slots=True)
class HandZone(Zone):
    name: str = "Hand"
    allowed_side: Side | None = Side.FATE
    max_capacity: float = math.inf


@dataclass(slots=True)
class BattlefieldZone(Zone):
    name: str = "Battlefield"
    allowed_side: Side | None = None
    max_capacity: float = math.inf


@dataclass(slots=True)
class ProvinceZone(Zone):
    name: str = "Province"
    allowed_side: Side | None = Side.DYNASTY
    max_capacity: float = 1


@dataclass(slots=True)
class FateDiscardZone(Zone):
    name: str = "Fate Discard"
    allowed_side: Side | None = Side.FATE
    max_capacity: float = math.inf


@dataclass(slots=True)
class FateBanishZone(Zone):
    name: str = "Fate Banish"
    allowed_side: Side | None = Side.FATE
    max_capacity: float = math.inf


@dataclass(slots=True)
class DynastyDiscardZone(Zone):
    name: str = "Dynasty Discard"
    allowed_side: Side | None = Side.DYNASTY
    max_capacity: float = math.inf


@dataclass(slots=True)
class DynastyBanishZone(Zone):
    name: str = "Dynasty Banish"
    allowed_side: Side | None = Side.DYNASTY
    max_capacity: float = math.inf
