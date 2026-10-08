from collections.abc import Callable, Iterator, Sequence

from yasuki_core.engine.players import PlayerId
from yasuki_core.engine.registrar import HandlerRegistry
from yasuki_core.engine.rules.board.counts_as import Asking, counts_as
from yasuki_core.engine.rules.stats.keyword_grants import effective_keywords
from yasuki_core.engine.rules.state import GameState
from yasuki_core.engine.rules.vocabulary.game_events import (
    ActionResolved,
    EnteredPlay,
    GameEvent,
    PhaseStarted,
)
from yasuki_core.engine.rules.units.composition import followers_of, is_follower
from yasuki_core.engine.rules.units.membership import unit_of
from yasuki_core.engine.table import (
    controller_of,
    DeckKey,
    Zone,
    ZoneKey,
    ZoneRole,
    location_of,
    province_holding,
    province_keys,
)
from yasuki_core.engine.rules.vocabulary import keywords
from yasuki_core.game_pieces.cards import L5RCard
from yasuki_core.game_pieces.constants import Element
from yasuki_core.game_pieces.counters import SINCERITY
from yasuki_core.game_pieces.prints import (
    HoldingPrint,
    PersonalityPrint,
    RingPrint,
)


def province_zones(game: GameState, seat: PlayerId) -> Iterator[tuple[ZoneKey, Zone]]:
    """Each of ``seat``'s Province zones with its key, left to right."""
    for key in province_keys(game.table, seat):
        yield key, game.table.zones[key]


def rightmost_province(game: GameState, seat: PlayerId) -> ZoneKey | None:
    """``seat``'s rightmost Province, the one an effect destroying a Province without saying which
    destroys (ShE datasheet), or None once it has none."""
    keys = province_keys(game.table, seat)
    return keys[-1] if keys else None


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

# Cards letting their controller's attack effects of some kinds target Personalities with
# Followers as well, by printed id, each with those kinds: "Your :fear: may target Personalities
# with Followers".
ATTACKS_PAST_FOLLOWERS: HandlerRegistry[frozenset[type]] = HandlerRegistry(
    "attacks past followers", "already lets attacks target Personalities with Followers"
)
register_attacks_past_followers = ATTACKS_PAST_FOLLOWERS.make_register()


def attack_targets(game: GameState, source: L5RCard, kind: type) -> list[str]:
    """The ids an attack effect of ``kind`` from ``source`` may be pointed at: the enemy army's
    Followers and its Personalities carrying none (CR, Ranged Attack), and its Personalities
    carrying Followers too while a card ``source``'s controller has in play lets its attacks of
    ``kind`` target them. Empty outside a battle.

    Reaches only what stands at the battle being fought. A Personality is spared by a Follower
    alone. An Item or a Spell attached to him does not protect him.
    """
    attack = game.attack
    if attack is None or attack.current is None:
        return []
    seat = controller_of(game.table, source)
    past_followers = any(
        kind in ATTACKS_PAST_FOLLOWERS.get(card.printed_id, frozenset())
        and controller_of(game.table, card) is seat
        for card in game.table.battlefield.cards
    )
    return attack_targets_at(
        game, attack.current, attack.enemy_of(seat), past_followers=past_followers
    )


def attack_targeting(kind: type) -> Callable[[GameState, L5RCard], list[str]]:
    """The targets of an ability whose effect is an attack effect of ``kind``, as
    :func:`attack_targets` reads them."""

    def targets(game: GameState, source: L5RCard) -> list[str]:
        return attack_targets(game, source, kind)

    return targets


def attack_targets_at(
    game: GameState, battlefield: int | None, seat: PlayerId, *, past_followers: bool = False
) -> list[str]:
    """The ids an attack effect may be pointed at among ``seat``'s units at ``battlefield``: each
    unit's Followers, and its Personality when he carries none or ``past_followers`` lets the
    attack reach him anyway (CR, Ranged Attack). ``None`` asks it of ``seat``'s home, for an
    attack that reaches a card standing out of the battle."""
    targets: list[str] = []
    for personality in units_at(game, battlefield, seat):
        followers = followers_of(game, personality)
        targets.extend(follower.id for follower in followers)
        if not followers or past_followers:
            targets.append(personality.id)
    return targets


def owned_personalities(game: GameState, owner: PlayerId) -> tuple[L5RCard, ...]:
    """The Personalities ``owner`` has in play -- the pool almost every "your target Personality"
    starts from, before the card's own condition narrows it."""
    return tuple(
        card
        for card in game.table.battlefield.cards
        if isinstance(card.printed, PersonalityPrint) and controller_of(game.table, card) is owner
    )


def personalities_in_play(game: GameState) -> tuple[L5RCard, ...]:
    """Every Personality on the battlefield, either seat's -- the pool a card means by "a target
    Personality" with no side attached to it."""
    return tuple(
        card for card in game.table.battlefield.cards if isinstance(card.printed, PersonalityPrint)
    )


def owned_carrying(game: GameState, owner: PlayerId, *carried: str) -> tuple[L5RCard, ...]:
    """The cards ``owner`` has in play carrying any of ``carried``: the pool a card means by "your
    target Monk or Shugenja", which names no card type, so a Follower carrying one is among them."""
    return tuple(
        card
        for card in game.table.battlefield.cards
        if controller_of(game.table, card) is owner
        and any(has_keyword(game, card, keyword) for keyword in carried)
    )


def favor_actions_this_turn(game: GameState, seat: PlayerId) -> int:
    """How many Favor actions ``seat`` has resolved this turn, folded over the turn's events."""
    return sum(
        1
        for event in game.turn_events
        if isinstance(event, ActionResolved) and event.seat is seat and event.favor
    )


def equipped_from_hand_since_last_turn(game: GameState, seat: PlayerId) -> tuple[L5RCard, ...]:
    """The cards ``seat`` has Equipped from its hand since its last turn ended, as "if he Equipped
    any Followers from his hand since his last turn ended" reads at the end of its own turn. An
    Equip counts and a card put into play from hand does not (CR, Equip)."""
    by_id = game.table.cards_by_id
    return tuple(
        by_id[event.card_id]
        for event in (*game.previous_turn_events, *game.turn_events)
        if isinstance(event, EnteredPlay)
        and event.equipped
        and event.from_hand
        and by_id[event.card_id].owner is seat
    )


def phase_history(game: GameState) -> tuple[GameEvent, ...]:
    """The ``GameEvent`` records of what has happened since the current phase began, which is
    what a card reading "this phase" counts. The whole turn so far before its first phase has
    begun."""
    events = game.turn_events
    starts = [index for index, event in enumerate(events) if isinstance(event, PhaseStarted)]
    return events[starts[-1] + 1 :] if starts else events


def honorably_dead(game: GameState, card: L5RCard) -> bool:
    """Whether ``card`` lies dead in a pile without disgrace, which is what "if X is honorably
    dead" asks.

    Three cards in a discard pile look alike and are not: one destroyed while honorable is
    honorably dead, one destroyed while dishonorable is dishonorably dead, and one discarded out
    of a Province never died at all. Only the first answers True, and a card back in play is not
    dead whatever it last left play by.
    """
    departure = game.last_known.get(card.id)
    if departure is None or not departure.destroyed or card.dishonorable:
        return False
    return not any(held is card for held in game.table.battlefield.cards)


def rings_in_play(game: GameState, seat: PlayerId, asking: Asking) -> tuple[L5RCard, ...]:
    """The Rings ``seat`` has in play, as ``asking`` counts them."""
    return tuple(
        card
        for card in game.table.battlefield.cards
        if controller_of(game.table, card) is seat and counts_as(game, card, RingPrint, asking)
    )


def ring_elements(game: GameState, ring: L5RCard) -> frozenset[Element]:
    """The elements ``ring``'s keywords name as they stand, granted ones included."""
    carried = {keyword.lower() for keyword in effective_keywords(game, ring)}
    return frozenset(element for element in Element if element.value.lower() in carried)


def different_elements(rings: Sequence[frozenset[Element]]) -> int:
    """How many of ``rings``, each given as the elements it carries, can stand for a different
    element at once. A Ring with two element keywords stands for only one of them, so this is the
    largest matching of Rings to elements."""
    matched: dict[Element, int] = {}

    def claim(index: int, tried: set[Element]) -> bool:
        for element in rings[index]:
            if element in tried:
                continue
            tried.add(element)
            if element not in matched or claim(matched[element], tried):
                matched[element] = index
                return True
        return False

    for index in range(len(rings)):
        claim(index, set())
    return len(matched)


def followers_in_play(game: GameState) -> tuple[L5RCard, ...]:
    """Every Follower on the battlefield, either seat's -- the pool a card means by "a target
    Follower" with no side attached to it. The Follower counterpart of
    :func:`~.personalities_in_play`."""
    return tuple(card for card in game.table.battlefield.cards if is_follower(card))


def owned_holdings(game: GameState, owner: PlayerId, keyword: str | None = None) -> list[L5RCard]:
    """The Holdings ``owner`` has in play, narrowed to those carrying ``keyword`` when one is given.
    Default None, which takes them all."""
    return [
        held
        for held in game.table.battlefield.cards
        if isinstance(held.printed, HoldingPrint)
        and controller_of(game.table, held) is owner
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


def units_at(game: GameState, battlefield: int | None, seat: PlayerId) -> list[L5RCard]:
    """The Personalities ``seat`` has standing at ``battlefield``, in play order. One side of the
    army there, since a seat's units at a battlefield are all on the same side of it. ``None``
    names the seat's home, where a Personality in no battle stands."""
    return [
        card
        for card in game.table.battlefield.cards
        if isinstance(card.printed, PersonalityPrint)
        and controller_of(game.table, card) is seat
        and location_of(game.table, card).battlefield == battlefield
    ]


def army_at(game: GameState, battlefield: int, seat: PlayerId) -> list[L5RCard]:
    """The cards of ``seat``'s units at ``battlefield``: each Personality followed by the cards
    attached to him (CR, Army). What a card means by "your cards in this army", before its own
    condition narrows them."""
    return [
        card
        for personality in units_at(game, battlefield, seat)
        for card in unit_of(game, personality)
    ]


def outnumbered_at(game: GameState, battlefield: int, seat: PlayerId) -> bool:
    """Whether ``seat``'s army at ``battlefield`` is outnumbered: the opposing side there has more
    units than it (ShE datasheet, Outnumbered). A side with no units is not an army, so a seat with
    none there is never outnumbered, and outside an attack no armies oppose each other at all."""
    attack = game.attack
    if attack is None:
        return False
    own = units_at(game, battlefield, seat)
    enemy = units_at(game, battlefield, attack.enemy_of(seat))
    return bool(own) and len(own) < len(enemy)


def in_army_with(game: GameState, source: L5RCard, card: L5RCard) -> bool:
    """Whether ``card`` is in the army of ``source``'s controller at ``source``'s battlefield, as
    "your cards at this battlefield" reads. False while ``source`` is at home."""
    here = location_of(game.table, source).battlefield
    seat = controller_of(game.table, source)
    if here is None or controller_of(game.table, card) is not seat:
        return False
    return any(member is card for member in army_at(game, here, seat))


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
    """Whether ``seat`` controls a Terrain at ``battlefield``."""
    return any(controller_of(game.table, card) is seat for card in terrains_at(game, battlefield))


def opposing_units_in_battle(game: GameState, seat: PlayerId) -> tuple[str, ...]:
    """The ids of the enemy Personalities ``seat`` faces at the battle now being fought.

    Empty outside a battle, which is what withholds a Battle ability when no battle is open.
    """
    attack = game.attack
    if attack is None or attack.current is None:
        return ()
    return tuple(card.id for card in units_at(game, attack.current, attack.enemy_of(seat)))


def opposed_units_in_battle(game: GameState, seat: PlayerId) -> tuple[str, ...]:
    """The ids of ``seat``'s Personalities opposed at the battle now being fought: those at its
    battlefield while an enemy unit is also there (CR, Opposed). Empty otherwise."""
    if not opposing_units_in_battle(game, seat):
        return ()
    return tuple(card.id for card in units_at(game, game.attack.current, seat))
