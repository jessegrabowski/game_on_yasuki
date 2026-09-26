from typing import TypeGuard

from yasuki_core.engine.players import PlayerId
from yasuki_core.engine.rules import triggers
from yasuki_core.engine.rules.abilities.model import Ability, CardLocation, itself
from yasuki_core.engine.rules.abilities.registry import register_ability
from yasuki_core.engine.rules.board.queries import province_key_holding, province_key_of
from yasuki_core.engine.rules.board.seats import cards_in_hand
from yasuki_core.engine.rules.effects import (
    Banish,
    Choose,
    Discard,
    Effect,
    Evaluate,
    LoseGame,
    PlaceInProvince,
    RefillProvince,
    ShuffleDeck,
    SpendSeatOncePerTurn,
    Then,
)
from yasuki_core.engine.rules.legality import legacy_candidates, legacy_search_pool
from yasuki_core.engine.rules.state import GameState, seat_once_key
from yasuki_core.engine.rules.vocabulary.actions import Action, ActionTiming, ActivateAbility
from yasuki_core.engine.table import DeckKey, ZoneRole
from yasuki_core.game_pieces.cards import L5RCard
from yasuki_core.game_pieces.constants import LEGACY_PROXY_ID, Side
from yasuki_core.game_pieces.prints import RulebookPrint

LEGACY = "legacy"
BANISH_RESOLVER = "legacy_banish"
SEARCH_RESOLVER = "legacy_search"
FIND_RESOLVER = "legacy_find"
PLACE_RESOLVER = "legacy_place"

# The print each seat's Legacy proxy presents. ``rulebook/proxies.py`` deals it.
LEGACY_PROXY = RulebookPrint(
    name="Legacy", side=Side.FATE, printed_id=LEGACY_PROXY_ID, card_type="Other"
)


def is_legacy(action: Action) -> TypeGuard[ActivateAbility]:
    """Whether ``action`` takes the Legacy ability on a seat's Legacy proxy."""
    return isinstance(action, ActivateAbility) and action.ability_key == LEGACY


def _legacy_cost(game: GameState, source: L5RCard) -> list[Effect]:
    """Spend the seat's Legacy for the turn and banish a card from its hand. A hand holding no
    Fate card leaves the pick unpayable, so Legacy is not offered."""
    seat = source.owner
    candidates = tuple(card.id for card in cards_in_hand(game, seat))
    return [
        SpendSeatOncePerTurn(seat=seat, tag=LEGACY),
        Choose(seat=seat, candidates=candidates, minimum=1, maximum=1, resolver=BANISH_RESOLVER),
    ]


def _legacy_targets(game: GameState, source: L5RCard) -> list[str]:
    """The proxy itself while the seat's Legacy is unspent this turn. Offered even when no Legacy
    card can be found: the rules make the whiff a loss, and hiding the option would leak what the
    face-down Provinces hold."""
    if game.has_used(seat_once_key(source.owner, LEGACY, game.turn)):
        return []
    return itself(game, source)


def _legacy_effects(game: GameState, source: L5RCard, target: L5RCard) -> list[Effect]:
    """The search, evaluated as it resolves, so it looks through the deck only after the Interrupt
    step closes."""
    return [Evaluate(resolver=SEARCH_RESOLVER, source_id=source.id, seat=source.owner)]


register_ability(
    LEGACY_PROXY_ID,
    Ability(
        timings=(ActionTiming.DYNASTY,),
        label=(
            "Dynasty: Banish a card from your hand to search your deck and Provinces for a Legacy "
            "card. Put it face up in one of your Provinces, discarding the card there. If you fail "
            "to find a Legacy card, you lose the game."
        ),
        cost=_legacy_cost,
        targets=_legacy_targets,
        effects=_legacy_effects,
        hits_every_target=True,
        key=LEGACY,
        located_at=(CardLocation.RULEBOOK,),
        from_rulebook=True,
    ),
)


@triggers.choice_resolver(
    BANISH_RESOLVER, prompt="Banish a card from hand to search for a Legacy card"
)
def _banish(
    game: GameState, source_id: str | None, chosen: tuple[str, ...], seat: PlayerId
) -> list[Effect]:
    return [Banish(card_id=chosen[0])]


@triggers.choice_resolver(SEARCH_RESOLVER)
def _search(
    game: GameState, source_id: str | None, chosen: tuple[str, ...], seat: PlayerId
) -> list[Effect]:
    """Look through the search pool, then ask which Legacy card to take. Finding nothing loses the
    game.

    A face-down Province card is searched, so the seat has seen it by the time it chooses which
    Province to displace.
    """
    for card in legacy_search_pool(game, seat):
        game.show_to(card, seat)
    found = tuple(card.id for card in legacy_candidates(game, seat))
    if not found:
        return [LoseGame(seat=seat, reason="failed Legacy", victory="opponent failed Legacy")]
    return [Choose(seat=seat, candidates=found, minimum=1, maximum=1, resolver=FIND_RESOLVER)]


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
