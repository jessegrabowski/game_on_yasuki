from yasuki_core.engine.rules.stats.card_values import effective_force
from yasuki_core.engine.rules.stats.keyword_grants import effective_keywords
from yasuki_core.engine.rules.state import GameState
from yasuki_core.engine.rules.units.membership import attachments_of
from yasuki_core.game_pieces.cards import L5RCard
from yasuki_core.game_pieces.constants import AttachmentType
from yasuki_core.game_pieces.prints import PersonalityPrint


def followers_of(game: GameState, personality: L5RCard) -> tuple[L5RCard, ...]:
    """The Followers in ``personality``'s unit, in the order they were attached.

    Followers alone, because the rules ask about them alone: they stand in the unit and carry a
    Force of their own, while an Item or Spell hands the Personality a modifier instead.
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
    Force modifier to the Personality, so an Item's Force survives its own bowing but not its
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
    # what his Items lend him, which is what the rule says happens.
    total = 0 if personality.bowed else effective_force(game, personality)
    return total + sum(
        effective_force(game, follower) for follower in followers if not follower.bowed
    )


def unit_keywords(game: GameState, personality: L5RCard) -> frozenset[str]:
    """The keywords ``personality``'s unit has: the ones he and every Follower share (CR, Unit
    keywords). A Personality with no Followers gives the unit his own.

    Items and Spells take no part. Only the Personality and Followers count. Infantry is never a
    member, since a unit is Infantry exactly when Cavalry is missing here.
    """
    shared = effective_keywords(game, personality)
    for follower in followers_of(game, personality):
        shared &= effective_keywords(game, follower)
    return shared


def in_a_unit(game: GameState, card: L5RCard) -> bool:
    """Whether ``card`` is part of a unit: a Personality, or a card attached to one (CR, Unit)."""
    return isinstance(card.printed, PersonalityPrint) or card.id in game.table.units
