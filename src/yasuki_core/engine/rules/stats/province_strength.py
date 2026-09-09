from yasuki_core.engine.rules.registrar import HandlerRegistry
from collections.abc import Callable

from yasuki_core.engine.rules.board.seats import seat_stronghold
from yasuki_core.engine.rules.modifiers import ProvinceModifier, Stat
from yasuki_core.engine.rules.stats.ongoing_grants import grant_applies
from yasuki_core.engine.rules.state import GameState
from yasuki_core.engine.rules.stats.calculation import effective_stat
from yasuki_core.engine.table import ZoneKey
from yasuki_core.game_pieces.cards import L5RCard
from yasuki_core.game_pieces.counters import counter_from_key


# What a card attached to a Province gives it, beyond anything it prints. Makeshift Fortifications
# reads "This Province has +3PS"; a Fortification carries no Province Strength stat of its own, so
# the grant is text rather than a number on the print. Keyed by printed id like the other registries.
ProvinceGrant = Callable[[GameState, L5RCard, ZoneKey], int]
PROVINCE_STRENGTH_GRANTS: HandlerRegistry[ProvinceGrant] = HandlerRegistry(
    "province strength grants", "already grants Province Strength"
)
province_strength_grant = PROVINCE_STRENGTH_GRANTS.make_decorator()


def effective_province_strength(game: GameState, province: ZoneKey) -> int:
    """How strong ``province`` is right now, floored at zero.

    Four sources, summed: the owning seat's Stronghold prints the strength every one of its
    Provinces starts at — a stat of a Stronghold *or* of a Province (CR, Province Strength) — then
    the counters resting on this slot, then what the Fortifications attached to it grant, then the
    recorded modifiers a card has laid on it. A seat with no Stronghold in play contributes no
    printed base.
    """
    stronghold = seat_stronghold(game, province.owner)
    total = (
        effective_stat(game, stronghold, Stat.PROVINCE_STRENGTH) if stronghold is not None else 0
    )
    for name, count in game.table.province_counters.get(province, {}).items():
        total += counter_from_key(name).province_strength * count
    for card_id, holds in game.table.province_attachments.items():
        if holds != province:
            continue
        fortification = game.table.cards_by_id[card_id]
        grant = PROVINCE_STRENGTH_GRANTS.get(fortification.printed_id)
        if grant is not None:
            total += grant(game, fortification, province)
    total += sum(
        recorded.amount
        for recorded in game.ongoing
        if isinstance(recorded, ProvinceModifier)
        and recorded.province == province
        and grant_applies(game, recorded)
    )
    return max(0, total)
