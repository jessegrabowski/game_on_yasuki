from enum import Enum


class PlayerId(Enum):
    P1 = 1
    P2 = 2


# Not a PlayerId member: seats are iterated to build hands, decks, zones and policies, so a rulebook
# seat would be dealt a hand and given an AI.
class Rulebook(Enum):
    """A cause that is the rules rather than a player — the effects no one chose to take. One member
    per rulebook procedure that acts, so a card can react to the specific one as well as to "not a
    player at all". Battle and duel resolution join when battle exists."""

    CHI_DEATH = "chi_death"
    MAXIMUM_HAND_SIZE = "maximum_hand_size"
    ORPHANED_ATTACHMENT = "orphaned_attachment"


# Who or what caused an effect: a player taking an action, or the rulebook enforcing itself.
Cause = PlayerId | Rulebook
