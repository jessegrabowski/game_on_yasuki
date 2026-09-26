from yasuki_core.engine.players import PlayerId
from yasuki_core.engine.rules import triggers
from yasuki_core.engine.rules.board.queries import province_key_holding, province_key_of
from yasuki_core.engine.rules.effects import (
    Banish,
    Choose,
    Discard,
    Effect,
    LoseGame,
    PlaceInProvince,
    RefillProvince,
    ShuffleDeck,
    Then,
)
from yasuki_core.engine.rules.legality import legacy_candidates, legacy_key, legacy_search_pool
from yasuki_core.engine.rules.state import GameState
from yasuki_core.engine.table import DeckKey, ZoneKey, ZoneRole
from yasuki_core.game_pieces.constants import Side

BANISH_RESOLVER = "legacy_banish"
FIND_RESOLVER = "legacy_find"
PLACE_RESOLVER = "legacy_place"


def legacy(game: GameState) -> None:
    """Announce the Legacy ability: claim its once-per-turn use and pause for the banish cost. The
    search and placement follow once the banished card is chosen."""
    seat = game.active
    game.use_once(legacy_key(seat, game.turn))
    hand = game.table.zones[ZoneKey(seat, ZoneRole.HAND)]
    candidates = tuple(card.id for card in hand.cards)
    triggers.resolve_action_effects(
        game,
        [Choose(seat=seat, candidates=candidates, minimum=1, maximum=1, resolver=BANISH_RESOLVER)],
    )


def _reveal_search_pool(game: GameState, seat: PlayerId) -> None:
    """Let ``seat`` identify every card its Legacy search looked through. A face-down Province card
    is searched, so the seat has seen it by the time it chooses which Province to displace."""
    for card in legacy_search_pool(game, seat):
        card.add_peeker(seat)


@triggers.choice_resolver(
    BANISH_RESOLVER,
    prompt="Banish a card from hand to search for a Legacy card",
)
def _banish_and_search(
    game: GameState, source_id: str | None, chosen: tuple[str, ...], seat: PlayerId
) -> list[Effect]:
    """Banish the chosen hand card, then search. Finding nothing loses the game."""
    _reveal_search_pool(game, seat)
    found = tuple(card.id for card in legacy_candidates(game, seat))
    if not found:
        return [
            Banish(card_id=chosen[0]),
            LoseGame(seat=seat, reason="failed Legacy", victory="opponent failed Legacy"),
        ]
    return [
        Banish(card_id=chosen[0]),
        Choose(seat=seat, candidates=found, minimum=1, maximum=1, resolver=FIND_RESOLVER),
    ]


@triggers.choice_resolver(FIND_RESOLVER, prompt="Search your deck for a Legacy card")
def _choose_province(
    game: GameState, source_id: str | None, chosen: tuple[str, ...], seat: PlayerId
) -> list[Effect]:
    """Ask which Province the found card displaces, naming the found card as that pick's
    ``source_id``."""
    found_id = chosen[0]
    provinces = _displaceable_provinces(game, seat, keep=found_id)
    if not provinces:
        # No province to sacrifice, a state only reachable at zero provinces (a military loss the
        # engine does not model yet). Reveal the found card where it sits rather than placing it.
        game.table.cards_by_id[found_id].turn_face_up()
        return []
    return [
        Choose(
            seat=seat,
            candidates=provinces,
            minimum=1,
            maximum=1,
            resolver=PLACE_RESOLVER,
            source_id=found_id,
        )
    ]


@triggers.choice_resolver(
    PLACE_RESOLVER,
    prompt="Choose a province to place the Legacy card, discarding the card there",
)
def _place_found_card(
    game: GameState, source_id: str | None, chosen: tuple[str, ...], seat: PlayerId
) -> list[Effect]:
    """Discard the chosen province card, then put the found card (``source_id``) in its place."""
    assert source_id is not None
    target_key = province_key_of(game, seat, chosen[0])
    source_key = province_key_holding(game, seat, source_id)  # None when it came from the deck
    # One effect per occurrence, so each announces itself where it happens. The placement is
    # deferred because the rules resolve what the displaced card leaving triggered before anything
    # fills the Province behind it. The refill of the Province the found card left waits likewise
    # on the reactions to the placement.
    after_the_discard: list[Effect] = [PlaceInProvince(card_id=source_id, zone=target_key)]
    if source_key is None:
        # The found card came out of the deck, so the deck the search read is no longer secret. It
        # shuffles behind the placement, which is what takes the card out of it.
        after_the_discard.append(ShuffleDeck(deck=DeckKey(seat, Side.DYNASTY)))
    else:
        after_the_discard.append(Then((RefillProvince(zone=source_key),)))
    return [Discard(card_id=chosen[0], cause=seat), Then(tuple(after_the_discard))]


def _displaceable_provinces(game: GameState, seat: PlayerId, *, keep: str) -> tuple[str, ...]:
    """The face card in each province ``seat`` may discard to make room for a placed Legacy card,
    skipping the province that already holds the found card (id ``keep``), which cannot be its own
    sacrifice."""
    displaceable: list[str] = []
    for key, zone in game.table.zones.items():
        if key.owner is not seat or key.role is not ZoneRole.PROVINCE or not zone.cards:
            continue
        if any(card.id == keep for card in zone.cards):
            continue
        displaceable.append(zone.cards[-1].id)
    return tuple(displaceable)
