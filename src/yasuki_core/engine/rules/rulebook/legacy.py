from yasuki_core.engine import ops
from yasuki_core.engine.players import PlayerId
from yasuki_core.engine.rules import triggers
from yasuki_core.engine.rules.board.queries import province_key_holding, province_key_of
from yasuki_core.engine.rules.decisions import (
    BanishForLegacy,
    ChooseLegacyCard,
    DecisionResponse,
    PlaceLegacy,
)
from yasuki_core.engine.rules.effects import Discard, Effect, PlaceInProvince, ShuffleDeck, Then
from yasuki_core.engine.rules.legality import legacy_candidates, legacy_key, legacy_search_pool
from yasuki_core.engine.rules.turn.provinces import defer_refill
from yasuki_core.engine.rules.state import GameState
from yasuki_core.engine.table import DeckKey, ZoneKey, ZoneRole
from yasuki_core.game_pieces.constants import Side


def legacy(game: GameState) -> None:
    """Announce the Legacy ability: claim its once-per-turn use and pause for the banish cost. The
    search and placement follow once the banished card is chosen."""
    seat = game.active
    game.use_once(legacy_key(seat, game.turn))
    hand = game.table.zones[ZoneKey(seat, ZoneRole.HAND)]
    game.pending = BanishForLegacy(seat=seat, candidates=tuple(card.id for card in hand.cards))


def _reveal_search_pool(game: GameState, seat: PlayerId) -> None:
    """Let ``seat`` identify every card its Legacy search looked through. A face-down Province card
    is searched, so the seat has seen it by the time it chooses which Province to displace."""
    for card in legacy_search_pool(game, seat):
        card.add_peeker(seat)


def apply_legacy_banish(
    game: GameState, request: BanishForLegacy, response: DecisionResponse
) -> None:
    seat = request.seat
    banished = game.table.cards_by_id[response.choices[0]]
    ops.move_card(game.table, banished, ZoneKey(seat, ZoneRole.FATE_BANISH))
    game.pending = None
    _reveal_search_pool(game, seat)
    found = legacy_candidates(game, seat)
    if not found:
        # The whiff: failing to find a Legacy card loses the game.
        game.lose(seat, "failed Legacy", "opponent failed Legacy")
        return
    game.pending = ChooseLegacyCard(seat=seat, candidates=tuple(card.id for card in found))


def apply_legacy_choice(
    game: GameState, request: ChooseLegacyCard, response: DecisionResponse
) -> None:
    seat = request.seat
    legacy_card = game.table.cards_by_id[response.choices[0]]
    game.pending = None
    provinces = _displaceable_provinces(game, seat, keep=legacy_card.id)
    if not provinces:
        # No province to sacrifice — only reachable at zero provinces (a military loss the engine
        # does not model yet). Reveal the found card where it sits rather than placing it.
        legacy_card.turn_face_up()
        return
    game.pending = PlaceLegacy(seat=seat, candidates=provinces, legacy_card_id=legacy_card.id)


def apply_legacy_placement(
    game: GameState, request: PlaceLegacy, response: DecisionResponse
) -> None:
    seat = request.seat
    displaced = game.table.cards_by_id[response.choices[0]]
    legacy_card = game.table.cards_by_id[request.legacy_card_id]
    target_key = province_key_of(game, seat, displaced.id)
    source_key = province_key_holding(game, seat, legacy_card.id)  # None when it came from the deck
    game.pending = None
    if source_key is not None:
        defer_refill(game, source_key)
    # One effect per occurrence, so each announces itself where it happens. The placement is
    # deferred because the rules resolve what the displaced card leaving triggered before anything
    # fills the Province behind it.
    after_the_discard: list[Effect] = [PlaceInProvince(legacy_card.id, target_key)]
    if source_key is None:
        # The found card came out of the deck, so the deck the search read is no longer secret. It
        # shuffles behind the placement, which is what takes the card out of it.
        after_the_discard.append(ShuffleDeck(DeckKey(seat, Side.DYNASTY)))
    triggers.resolve_effects(game, [Discard(displaced.id, seat), Then(tuple(after_the_discard))])


def _displaceable_provinces(game: GameState, seat: PlayerId, *, keep: str) -> tuple[str, ...]:
    """The province cards ``seat`` may discard to make room for a placed Legacy card — its face card
    in each province, skipping the province that already holds the found card (id ``keep``), which
    cannot be its own sacrifice."""
    displaceable: list[str] = []
    for key, zone in game.table.zones.items():
        if key.owner is not seat or key.role is not ZoneRole.PROVINCE or not zone.cards:
            continue
        if any(card.id == keep for card in zone.cards):
            continue
        displaceable.append(zone.cards[-1].id)
    return tuple(displaceable)
