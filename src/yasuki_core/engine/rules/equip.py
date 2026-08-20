from collections.abc import Callable

from yasuki_core.engine.players import PlayerId
from yasuki_core.engine.rules.abilities import owned_personalities
from yasuki_core.engine.rules.attachments import attachments_of
from yasuki_core.engine.rules.economy import effective_keywords, effective_weapon_limit
from yasuki_core.engine.rules.state import GameState
from yasuki_core.game_pieces import keywords
from yasuki_core.game_pieces.cards import L5RCard
from yasuki_core.game_pieces.prints import CardPrint


def weapons_on(game: GameState, personality: L5RCard) -> tuple[L5RCard, ...]:
    """The Weapon Items attached to ``personality``."""
    return tuple(
        card
        for card in attachments_of(game, personality)
        if keywords.WEAPON in effective_keywords(game, card)
    )


def may_hold_weapon(game: GameState, personality: L5RCard, weapon_keywords: frozenset[str]) -> bool:
    """Whether ``personality`` has room for a Weapon carrying ``weapon_keywords`` under the Weapon
    rules.

    Two rules, independent of each other. How many Weapons fit is a characteristic — one by default,
    two for a Kensai — so raising it is a modifier rather than an exemption from a rule. Two-Handed
    is exclusive on top of that: a Personality, "even a Kensai", cannot hold a Two-Handed Weapon
    beside any other Weapon, in either order (CR, Weapon; Kensai; Two-Handed).

    Takes the keywords rather than the Weapon so a card about to be created can be judged before it
    exists.
    """
    held = weapons_on(game, personality)
    if len(held) >= effective_weapon_limit(game, personality):
        return False
    if keywords.TWO_HANDED in weapon_keywords:
        return not held
    return not any(keywords.TWO_HANDED in effective_keywords(game, card) for card in held)


def may_attach_weapon(game: GameState, personality: L5RCard, weapon: L5RCard) -> bool:
    """Whether ``weapon`` may join ``personality`` under the Weapon rules."""
    return may_hold_weapon(game, personality, effective_keywords(game, weapon))


# What a card's own text says it will hang on — "Can only attach to a Samurai" and its kin. Keyed by
# printed id like the other per-card registries. The rulebook's restrictions live in this module as
# code; a restriction only one card states lives with that card.
AttachRestriction = Callable[[GameState, L5RCard, L5RCard], bool]
ATTACH_RESTRICTIONS: dict[str, AttachRestriction] = {}


def attach_restriction(printed_id: str) -> Callable[[AttachRestriction], AttachRestriction]:
    """Register the decorated predicate as ``printed_id``'s limit on what it will attach to."""

    def register(restriction: AttachRestriction) -> AttachRestriction:
        if printed_id in ATTACH_RESTRICTIONS:
            raise ValueError(f"{printed_id} already has an attach restriction")
        ATTACH_RESTRICTIONS[printed_id] = restriction
        return restriction

    return register


def may_attach(game: GameState, personality: L5RCard, card: L5RCard) -> bool:
    """Whether ``card`` may attach to ``personality``, by its own text and by the Weapon rules.

    Only Weapons answer to the Weapon rules — a Follower or a plain Item is limited by neither the
    count nor Two-Handed exclusivity.
    """
    restriction = ATTACH_RESTRICTIONS.get(card.printed_id)
    if restriction is not None and not restriction(game, personality, card):
        return False
    if keywords.WEAPON not in effective_keywords(game, card):
        return True
    return may_attach_weapon(game, personality, card)


def may_attach_created(game: GameState, personality: L5RCard, printed: CardPrint) -> bool:
    """Whether a card created from ``printed`` may attach to ``personality``.

    The card does not exist yet, so its keywords come off the print rather than through the grants a
    card in play reads. Only the rulebook's rules apply: an attach restriction is a card's own text,
    and a created card carries the plain proxy print of what it is.
    """
    printed_keywords = frozenset(printed.keywords)
    if keywords.WEAPON not in printed_keywords:
        return True
    return may_hold_weapon(game, personality, printed_keywords)


def creation_targets(game: GameState, seat: PlayerId, printed: CardPrint) -> tuple[L5RCard, ...]:
    """The Personalities ``seat`` may create a card from ``printed`` onto — its own, that the
    attachment rules still admit. A player creates onto their own, as they attach (CR,
    Attachments)."""
    return tuple(
        personality
        for personality in owned_personalities(game, seat)
        if may_attach_created(game, personality, printed)
    )


def equip_targets(game: GameState, card: L5RCard) -> tuple[L5RCard, ...]:
    """The Personalities ``card`` may be Equipped to: the ones its own owner has in play, that the
    attachment rules still admit. A player may only attach to their own (CR, Attachments)."""
    return tuple(
        personality
        for personality in owned_personalities(game, card.owner)
        if may_attach(game, personality, card)
    )
