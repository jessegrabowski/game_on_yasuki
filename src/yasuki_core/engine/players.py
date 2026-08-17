from enum import Enum


class PlayerId(Enum):
    P1 = 1
    P2 = 2


class Rulebook(Enum):
    """A cause that is the rules rather than a player, for the effects no one chose to take.

    One member per rule rather than a single "the rules did it", because cards ask which: four ask
    to react to a Personality destroyed *for having zero Chi* specifically. Battle and duel
    resolution join here when battle exists — both are the rulebook acting, not a player.

    Deliberately not a :class:`PlayerId` member. Seats are iterated to build hands, decks, zones and
    policies, so a rulebook seat would be dealt a hand and given an AI.
    """

    CHI_DEATH = "chi_death"
    ORPHANED_ATTACHMENT = "orphaned_attachment"


# Who or what caused an effect: a player taking an action, or the rulebook enforcing itself.
Cause = PlayerId | Rulebook
