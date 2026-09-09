from collections.abc import Callable

from yasuki_core.engine.players import PlayerId
from yasuki_core.engine.rules.attachments import attached_to, attachments_of
from yasuki_core.engine.rules.effects import AttackEffect
from yasuki_core.engine.rules.stats.keyword_grants import effective_keywords
from yasuki_core.engine.rules.registrar import HandlerRegistry
from yasuki_core.engine.rules.state import GameState
from yasuki_core.engine.rules.stats.card_values import effective_force
from yasuki_core.engine.table import location_of
from yasuki_core.game_pieces import keywords
from yasuki_core.game_pieces.cards import L5RCard
from yasuki_core.game_pieces.constants import AttachmentType
from yasuki_core.game_pieces.prints import AttachmentPrint, PersonalityPrint


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


def opposing_units_in_battle(game: GameState, seat: PlayerId) -> tuple[str, ...]:
    """The ids of the enemy Personalities ``seat`` faces at the battle now being fought.

    Empty outside a battle, which is what withholds a Battle ability when no battle is open.
    """
    attack = game.attack
    if attack is None or attack.current is None:
        return ()
    enemy = attack.attacker if seat is attack.defender else attack.defender
    return tuple(card.id for card in units_at(game, attack.current, enemy))


def attackable(game: GameState, seat: PlayerId) -> list[L5RCard]:
    """The cards ``seat``'s attack effects may target: the enemy army's Followers, and its
    Personalities carrying none (CR, Ranged Attack).

    The rule reaches the *army* rather than the seat, so it is empty outside a battle and holds only
    what stands at the one being fought. A Personality is spared by a Follower alone — an Item or a
    Spell attached to him is not one, and does not protect him.

    Parameters
    ----------
    game : GameState
        The board to read.
    seat : PlayerId
        The seat whose attack this is. The army returned is the other seat's.
    """
    attack = game.attack
    if attack is None or attack.current is None:
        return []
    enemy = attack.defender if seat is attack.attacker else attack.attacker
    targets: list[L5RCard] = []
    for personality in units_at(game, attack.current, enemy):
        followers = followers_of(game, personality)
        if followers:
            targets.extend(followers)
        else:
            targets.append(personality)
    return targets


# What a card's text does to an attack's strength. Every card in play is asked, because the scopes
# the corpus prints do not nest: a Follower speaks about itself, another about its unit, a Ring
# about every attack its controller makes. One walk and a handler that scopes itself is the only
# shape that holds all three.
AttackStrengthHandler = Callable[[GameState, L5RCard, L5RCard, AttackEffect], int]
ATTACK_STRENGTH_AGAINST: HandlerRegistry[AttackStrengthHandler] = HandlerRegistry(
    "attack strength", "already adjusts the attacks against it"
)
attack_strength_against = ATTACK_STRENGTH_AGAINST.make_decorator()


def effective_strength(game: GameState, attack: AttackEffect) -> int:
    """``attack``'s strength once every card in play has had its say.

    Not floored: a card that takes more strength off an attack than it had leaves it reaching
    nothing, which is what "have -2 strength" buys. The zero floor the CR puts on a stat
    (Calculating Stats) is about stats, and an attack's strength is not one.
    """
    target = game.table.cards_by_id.get(attack.target_id)
    if target is None:
        return attack.strength
    total = attack.strength
    for holder in game.table.battlefield.cards:
        handler = ATTACK_STRENGTH_AGAINST.get(holder.printed_id)
        if handler is not None:
            total += handler(game, holder, target, attack)
    return total


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


def is_spell(card: L5RCard) -> bool:
    """Whether ``card`` is a Spell. Only attachments carry a type, so the print answers first."""
    return (
        isinstance(card.printed, AttachmentPrint) and card.attachment_type is AttachmentType.SPELL
    )


def may_cast_spells(game: GameState, personality: L5RCard) -> bool:
    """Whether ``personality`` may hold and cast a Spell, which only a Shugenja may (CR, Spell)."""
    return keywords.SHUGENJA in effective_keywords(game, personality)


def has_caster(game: GameState, spell: L5RCard) -> bool:
    """Whether ``spell`` hangs on a Personality who may cast it."""
    caster = attached_to(game, spell)
    return caster is not None and may_cast_spells(game, caster)
