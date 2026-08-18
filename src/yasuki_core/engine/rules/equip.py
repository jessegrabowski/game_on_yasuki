from yasuki_core.engine.rules.attachments import attachments_of
from yasuki_core.engine.rules.economy import effective_keywords, effective_weapon_limit
from yasuki_core.engine.rules.state import GameState
from yasuki_core.game_pieces.cards import L5RCard
from yasuki_core.game_pieces.prints import PersonalityPrint

WEAPON_KEYWORD = "Weapon"
TWO_HANDED_KEYWORD = "Two-Handed"


def weapons_on(game: GameState, personality: L5RCard) -> tuple[L5RCard, ...]:
    """The Weapon Items attached to ``personality``."""
    return tuple(
        card
        for card in attachments_of(game, personality)
        if WEAPON_KEYWORD in effective_keywords(game, card)
    )


def may_attach_weapon(game: GameState, personality: L5RCard, weapon: L5RCard) -> bool:
    """Whether ``weapon`` may join ``personality`` under the Weapon rules.

    Two rules, independent of each other. How many Weapons fit is a characteristic — one by default,
    two for a Kensai — so raising it is a modifier rather than an exemption from a rule. Two-Handed
    is exclusive on top of that: a Personality, "even a Kensai", cannot hold a Two-Handed Weapon
    beside any other Weapon, in either order (CR, Weapon; Kensai; Two-Handed).
    """
    held = weapons_on(game, personality)
    if len(held) >= effective_weapon_limit(game, personality):
        return False
    if TWO_HANDED_KEYWORD in effective_keywords(game, weapon):
        return not held
    return not any(TWO_HANDED_KEYWORD in effective_keywords(game, card) for card in held)


def may_attach(game: GameState, personality: L5RCard, card: L5RCard) -> bool:
    """Whether ``card`` may attach to ``personality``. Only Weapons answer to the Weapon rules —
    a Follower or a plain Item is limited by neither the count nor Two-Handed exclusivity."""
    if WEAPON_KEYWORD not in effective_keywords(game, card):
        return True
    return may_attach_weapon(game, personality, card)


def equip_targets(game: GameState, card: L5RCard) -> tuple[L5RCard, ...]:
    """The Personalities ``card`` may be Equipped to: the ones its own owner has in play, that the
    attachment rules still admit. A player may only attach to their own (CR, Attachments)."""
    return tuple(
        personality
        for personality in game.table.battlefield.cards
        if isinstance(personality.printed, PersonalityPrint)
        and personality.owner is card.owner
        and may_attach(game, personality, card)
    )
