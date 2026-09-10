from collections.abc import Iterator

from yasuki_core.engine.players import PlayerId
from yasuki_core.engine.rules.stats.keyword_grants import effective_keywords
from yasuki_core.engine.rules.state import GameState
from yasuki_core.engine.rules.units.composition import followers_of
from yasuki_core.engine.table import Zone, ZoneKey, ZoneRole, location_of, province_holding
from yasuki_core.engine.rules.vocabulary import keywords
from yasuki_core.game_pieces.cards import L5RCard
from yasuki_core.game_pieces.counters import SINCERITY
from yasuki_core.game_pieces.prints import HoldingPrint, PersonalityPrint


def province_zones(game: GameState, seat: PlayerId) -> Iterator[tuple[ZoneKey, Zone]]:
    """Each of ``seat``'s Province zones with its key, in table order."""
    for key, zone in game.table.zones.items():
        if key.owner is seat and key.role is ZoneRole.PROVINCE:
            yield key, zone


def province_cards(game: GameState, seat: PlayerId) -> Iterator[L5RCard]:
    """Every card in ``seat``'s Provinces, face-up or not, in Province order."""
    for _, zone in province_zones(game, seat):
        yield from zone.cards


def province_key_holding(game: GameState, seat: PlayerId, card_id: str) -> ZoneKey | None:
    """The Province of ``seat`` holding ``card_id``, or None when none does."""
    return province_holding(game.table, seat, card_id)


def province_key_of(game: GameState, seat: PlayerId, card_id: str) -> ZoneKey:
    """The Province of ``seat`` holding ``card_id``. Raise ValueError when none does -- for callers
    that already know the card is there and would otherwise carry an impossible None."""
    key = province_key_holding(game, seat, card_id)
    if key is None:
        raise ValueError(f"no province of {seat.name} holds card {card_id}")
    return key


def has_keyword(game: GameState, card: L5RCard, keyword: str) -> bool:
    """Whether ``card`` carries ``keyword``, printed or granted by its own ability, matched without
    regard to case."""
    wanted = keyword.lower()
    return any(carried.lower() == wanted for carried in effective_keywords(game, card))


def attack_targets(game: GameState, source: L5RCard) -> list[str]:
    """The ids an attack effect from ``source`` may be pointed at: the enemy army's Followers and
    its Personalities carrying none (CR, Ranged Attack). Empty outside a battle, which is what
    keeps an attack ability from being offered where it has nothing to hit.

    The rule reaches the *army* rather than the seat, so it holds only what stands at the battle
    being fought. A Personality is spared by a Follower alone — an Item or a Spell attached to him
    is not one, and does not protect him.
    """
    attack = game.attack
    if attack is None or attack.current is None:
        return []
    enemy = attack.defender if source.owner is attack.attacker else attack.attacker
    targets: list[str] = []
    for personality in units_at(game, attack.current, enemy):
        followers = followers_of(game, personality)
        if followers:
            targets.extend(follower.id for follower in followers)
        else:
            targets.append(personality.id)
    return targets


def owned_personalities(game: GameState, owner: PlayerId) -> tuple[L5RCard, ...]:
    """The Personalities ``owner`` has in play -- the pool almost every "your target Personality"
    starts from, before the card's own condition narrows it."""
    return tuple(
        card
        for card in game.table.battlefield.cards
        if isinstance(card.printed, PersonalityPrint) and card.owner is owner
    )


def personalities_in_play(game: GameState) -> tuple[L5RCard, ...]:
    """Every Personality on the battlefield, either seat's -- the pool a card means by "a target
    Personality" with no side attached to it."""
    return tuple(
        card for card in game.table.battlefield.cards if isinstance(card.printed, PersonalityPrint)
    )


def owned_holdings(game: GameState, owner: PlayerId, keyword: str | None = None) -> list[L5RCard]:
    """The Holdings ``owner`` has in play, narrowed to those carrying ``keyword`` when one is given.
    Default None, which takes them all."""
    return [
        held
        for held in game.table.battlefield.cards
        if held.owner is owner
        and isinstance(held.printed, HoldingPrint)
        and (keyword is None or keyword in effective_keywords(game, held))
    ]


def sincerity_seed_targets(game: GameState, seat: PlayerId) -> list[str]:
    """The seat's face-up Sincerity cards still in a Province with no Sincerity tokens -- the legal
    recipients of a seeded Sincerity token."""
    return [
        card.id
        for card in province_cards(game, seat)
        if card.face_up
        and keywords.SINCERITY in effective_keywords(game, card)
        and card.counters.get(SINCERITY.key, 0) == 0
    ]


def province_holdings(game: GameState, seat: PlayerId) -> list[str]:
    """The seat's face-up Holdings still in a Province -- the recruitable targets of a targeted
    recruit ability."""
    return [
        card.id
        for card in province_cards(game, seat)
        if card.face_up and isinstance(card.printed, HoldingPrint)
    ]


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
