from yasuki_core.engine.players import PlayerId
from yasuki_core.engine.rules.attachments import attachments_of
from yasuki_core.engine.rules.economy import effective_force, effective_keywords
from yasuki_core.engine.rules.state import GameState
from yasuki_core.engine.table import location_of
from yasuki_core.game_pieces.cards import L5RCard
from yasuki_core.game_pieces.constants import AttachmentType
from yasuki_core.game_pieces.prints import PersonalityPrint


def followers_of(game: GameState, personality: L5RCard) -> tuple[L5RCard, ...]:
    """The Followers in ``personality``'s unit, in the order they were attached.

    Followers alone, because the rules ask about them alone: they stand in the unit and carry a Force
    of their own, while an Item or Spell hands the Personality a modifier instead.
    """
    return tuple(
        card
        for card in attachments_of(game, personality)
        if card.attachment_type is AttachmentType.FOLLOWER
    )


def unit_force(game: GameState, personality: L5RCard, *, in_battle_resolution: bool = False) -> int:
    """The total Force of ``personality``'s unit (CR, Unit and Army Force).

    Outside battle resolution the total counts every card in the unit, bowed or not. Inside it, a
    bowed Personality and a bowed Follower contribute nothing, while a bowed Item still gives its
    Force modifier to the Personality — so an Item's Force survives its own bowing but not its
    Personality's, riding on him either way.

    Parameters
    ----------
    game : GameState
        The board to read.
    personality : L5RCard
        The Personality whose unit is totalled. A card with nothing attached is a unit of one.
    in_battle_resolution : bool, optional
        Whether the total is being taken during a battle's resolution, which is the only time bowing
        changes it. Default False.
    """
    followers = followers_of(game, personality)
    if not in_battle_resolution:
        return effective_force(game, personality) + sum(
            effective_force(game, follower) for follower in followers
        )
    # An Item's modifier is already inside the Personality's effective Force, so dropping him drops
    # what his Items lend him — which is what the rule says happens.
    total = 0 if personality.bowed else effective_force(game, personality)
    return total + sum(
        effective_force(game, follower) for follower in followers if not follower.bowed
    )


def unit_keywords(game: GameState, personality: L5RCard) -> frozenset[str]:
    """The keywords ``personality``'s unit has: the ones he and every Follower share (CR, Unit
    keywords). A Personality with no Followers gives the unit his own.

    Items and Spells take no part — the rule quantifies over the Personality and Followers alone.
    Infantry is never a member: it is the absence of Cavalry rather than a keyword of its own, so a
    unit is Infantry exactly when Cavalry is missing here.
    """
    shared = effective_keywords(game, personality)
    for follower in followers_of(game, personality):
        shared &= effective_keywords(game, follower)
    return shared


def units_at(game: GameState, battlefield: int, seat: PlayerId) -> list[L5RCard]:
    """The Personalities ``seat`` has standing at ``battlefield``, in play order. One side of the
    army there, since a seat's units at a battlefield are all on the same side of it."""
    return [
        card
        for card in game.table.battlefield.cards
        if card.owner is seat
        and isinstance(card.printed, PersonalityPrint)
        and location_of(game.table, card).battlefield == battlefield
    ]


def has_presence(game: GameState, seat: PlayerId) -> bool:
    """Whether ``seat`` controls a unit at the battle now being fought (CR, Rule of Presence).

    True outside a battle, where presence is not a question anyone asks.
    """
    attack = game.attack
    if attack is None or attack.current is None:
        return True
    return bool(units_at(game, attack.current, seat))


def in_a_unit(game: GameState, card: L5RCard) -> bool:
    """Whether ``card`` is part of a unit: a Personality, or a card attached to one (CR, Unit)."""
    return isinstance(card.printed, PersonalityPrint) or card.id in game.table.units


def location_permits(game: GameState, card: L5RCard) -> bool:
    """Whether the Rules of Location leave ``card`` free to be acted from and targeted.

    A card in a unit must stand at the battle now being fought. A card in no unit — a Holding, a
    Region, a Stronghold — stands nowhere those rules speak of, so they never exclude it, and
    neither rule applies outside a battle at all. A card in a unit stands where its Personality
    stands, so its own recorded location answers for it.
    """
    attack = game.attack
    if attack is None or attack.current is None:
        return True
    if not in_a_unit(game, card):
        return True
    return location_of(game.table, card).battlefield == attack.current
