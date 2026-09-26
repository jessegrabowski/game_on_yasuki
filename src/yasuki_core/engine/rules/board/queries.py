from collections.abc import Iterator

from yasuki_core.engine.players import PlayerId
from yasuki_core.engine.rules.stats.keyword_grants import effective_keywords
from yasuki_core.engine.rules.state import GameState
from yasuki_core.engine.rules.vocabulary.game_events import ActionResolved, GameEvent, PhaseStarted
from yasuki_core.engine.rules.units.composition import followers_of
from yasuki_core.engine.table import DeckKey, Zone, ZoneKey, ZoneRole, location_of, province_holding
from yasuki_core.engine.rules.vocabulary import keywords
from yasuki_core.game_pieces.cards import L5RCard
from yasuki_core.game_pieces.constants import AttachmentType
from yasuki_core.game_pieces.counters import SINCERITY
from yasuki_core.game_pieces.prints import (
    AttachmentPrint,
    HoldingPrint,
    PersonalityPrint,
    RingPrint,
)


def province_zones(game: GameState, seat: PlayerId) -> Iterator[tuple[ZoneKey, Zone]]:
    """Each of ``seat``'s Province zones with its key, in table order."""
    for key, zone in game.table.zones.items():
        if key.owner is seat and key.role is ZoneRole.PROVINCE:
            yield key, zone


def rulebook_proxy_id(seat: PlayerId, printed_id: str) -> str:
    """The card id of ``seat``'s proxy of ``printed_id``, fixed by seat and print."""
    return f"{seat.name}-{printed_id}"


def rulebook_proxy(game: GameState, seat: PlayerId, printed_id: str) -> L5RCard | None:
    """The proxy ``seat`` activates the rulebook abilities of ``printed_id`` from, or None before
    one is dealt."""
    zone = game.table.zones[ZoneKey(seat, ZoneRole.RULEBOOK)]
    return next((card for card in zone.cards if card.printed_id == printed_id), None)


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


def top_of_deck(game: GameState, deck: DeckKey, count: int) -> tuple[str, ...]:
    """The ids of the top ``count`` cards of ``deck``, top first, or fewer when the deck is
    shorter."""
    return tuple(card.id for card in reversed(game.table.decks[deck].peek(count)))


def remaining_look(game: GameState) -> tuple[str, ...]:
    """The cards of the open look still where they were looked at, top first. Empty when no look is
    open. A resolver asking the next question about a look reads its pool here, so a card an earlier
    answer moved out has already dropped from view.

    A card is still in view while it is in the deck and the seat is still among its peekers.
    Entering a deck scrubs the peekers, so a card put back on top or on the bottom leaves the pool
    as surely as one taken into hand, while one nothing has touched keeps the peek the look gave
    it.
    """
    look = game.look
    if look is None:
        return ()
    in_deck = {card.id: card for card in game.table.decks[look.deck].cards}
    return tuple(
        card_id
        for card_id in look.card_ids
        if card_id in in_deck and look.seat in in_deck[card_id].peekers
    )


def has_keyword(game: GameState, card: L5RCard, keyword: str) -> bool:
    """Whether ``card`` carries ``keyword``, printed or granted by its own ability, matched without
    regard to case."""
    wanted = keyword.lower()
    return any(carried.lower() == wanted for carried in effective_keywords(game, card))


# What an attack effect targets, worded for the target prompt of every ability that reaches
# through attack_targets.
ATTACK_TARGET = "an enemy Follower or Personality without Followers"


def attack_targets(game: GameState, source: L5RCard) -> list[str]:
    """The ids an attack effect from ``source`` may be pointed at: the enemy army's Followers and
    its Personalities carrying none (CR, Ranged Attack). Empty outside a battle.

    Reaches only what stands at the battle being fought. A Personality is spared by a Follower
    alone. An Item or a Spell attached to him does not protect him.
    """
    attack = game.attack
    if attack is None or attack.current is None:
        return []
    enemy = attack.defender if source.owner is attack.attacker else attack.attacker
    return attack_targets_at(game, attack.current, enemy)


def attack_targets_at(game: GameState, battlefield: int, seat: PlayerId) -> list[str]:
    """The ids an attack effect may be pointed at among ``seat``'s units at ``battlefield``: each
    unit's Followers, or its Personality when he carries none (CR, Ranged Attack)."""
    targets: list[str] = []
    for personality in units_at(game, battlefield, seat):
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


def favor_actions_this_turn(game: GameState, seat: PlayerId) -> int:
    """How many Favor actions ``seat`` has resolved this turn, folded over the turn's events."""
    return sum(
        1
        for event in game.turn_events
        if isinstance(event, ActionResolved) and event.seat is seat and event.favor
    )


def phase_history(game: GameState) -> tuple[GameEvent, ...]:
    """The ``GameEvent`` records of what has happened since the current phase began, which is
    what a card reading "this phase" counts. The whole turn so far before its first phase has
    begun."""
    events = game.turn_events
    starts = [index for index, event in enumerate(events) if isinstance(event, PhaseStarted)]
    return events[starts[-1] + 1 :] if starts else events


def rings_in_play(game: GameState, seat: PlayerId) -> tuple[L5RCard, ...]:
    """The Rings ``seat`` has in play."""
    return tuple(
        card
        for card in game.table.battlefield.cards
        if isinstance(card.printed, RingPrint) and card.owner is seat
    )


def followers_in_play(game: GameState) -> tuple[L5RCard, ...]:
    """Every Follower on the battlefield, either seat's -- the pool a card means by "a target
    Follower" with no side attached to it. The Follower counterpart of
    :func:`~.personalities_in_play`."""
    return tuple(
        card
        for card in game.table.battlefield.cards
        if isinstance(card.printed, AttachmentPrint)
        and card.printed.attachment_type is AttachmentType.FOLLOWER
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


def terrains_at(game: GameState, battlefield: int) -> list[L5RCard]:
    """The Terrains in play at ``battlefield``, in play order. They stand there in neither side or
    army (CR, Side), so :func:`~.units_at` never counts one."""
    return [
        card
        for card in game.table.battlefield.cards
        if location_of(game.table, card).battlefield == battlefield
        and keywords.TERRAIN in effective_keywords(game, card)
    ]


def controls_terrain_at(game: GameState, seat: PlayerId, battlefield: int) -> bool:
    """Whether ``seat`` controls a Terrain at ``battlefield``. Control is ownership until the engine
    models the two apart."""
    return any(card.owner is seat for card in terrains_at(game, battlefield))


def opposing_units_in_battle(game: GameState, seat: PlayerId) -> tuple[str, ...]:
    """The ids of the enemy Personalities ``seat`` faces at the battle now being fought.

    Empty outside a battle, which is what withholds a Battle ability when no battle is open.
    """
    attack = game.attack
    if attack is None or attack.current is None:
        return ()
    enemy = attack.attacker if seat is attack.defender else attack.defender
    return tuple(card.id for card in units_at(game, attack.current, enemy))


def opposed_units_in_battle(game: GameState, seat: PlayerId) -> tuple[str, ...]:
    """The ids of ``seat``'s Personalities opposed at the battle now being fought: those at its
    battlefield while an enemy unit is also there (CR, Opposed). Empty otherwise."""
    if not opposing_units_in_battle(game, seat):
        return ()
    return tuple(card.id for card in units_at(game, game.attack.current, seat))
