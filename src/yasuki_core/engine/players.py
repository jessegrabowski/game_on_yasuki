from dataclasses import dataclass
from enum import Enum


class PlayerId(Enum):
    P1 = 1
    P2 = 2


# Not a PlayerId member: seats are iterated to build hands, decks, zones and policies, so a rulebook
# seat would be dealt a hand and given an AI.
class Rulebook(Enum):
    """A cause that is the rules, not a player: stands in for the effects no one chose to take. One
    member per rulebook procedure that acts, so a card can react to the specific one and not just to
    "not a player at all". Duel resolution joins when duels exist."""

    BATTLE_RESOLUTION = "battle_resolution"
    CHI_DEATH = "chi_death"
    MAXIMUM_HAND_SIZE = "maximum_hand_size"
    ORPHANED_ATTACHMENT = "orphaned_attachment"


@dataclass(frozen=True, slots=True)
class Trait:
    """A cause that is a card's own trait: "before Gonshiro enters play, dishonor him" is Gonshiro's
    doing, not his controller's action and not the rulebook's. A trait is not an action (CR,
    Traits), so a reaction guarded on "your action" correctly ignores it.

    Attributes
    ----------
    card_id : str
        The card whose trait acted.
    """

    card_id: str

    @property
    def name(self) -> str:
        return f"{self.card_id}'s trait"


# Who or what caused an effect: a player taking an action, the rulebook enforcing itself, or a
# card's own trait.
Cause = PlayerId | Rulebook | Trait
