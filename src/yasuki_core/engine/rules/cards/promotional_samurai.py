from yasuki_core.engine.players import PlayerId
from yasuki_core.engine.rules.abilities.costs import no_cost
from yasuki_core.engine.rules.abilities.model import Ability, CardLocation
from yasuki_core.engine.rules.abilities.registry import register_ability
from yasuki_core.engine.rules.board.counts_as import Asking
from yasuki_core.engine.rules.board.queries import rings_in_play
from yasuki_core.engine.rules.effects import Bow, Choose, Effect, Straighten
from yasuki_core.engine.rules.legality import location_permits
from yasuki_core.engine.rules.state import GameState
from yasuki_core.engine.rules.triggers import choice_resolver
from yasuki_core.engine.rules.units.membership import attached_to, attachments_of
from yasuki_core.engine.rules.vocabulary.actions import ActionTiming
from yasuki_core.game_pieces.cards import L5RCard
from yasuki_core.game_pieces.prints import AttachmentPrint, StrongholdPrint


# --- Aligned with the Elements ---


def _aligned_with_the_elements_rings(game: GameState, source: L5RCard, *, bowed: bool) -> list[str]:
    return [
        card.id
        for card in rings_in_play(game, source.owner, Asking.action(source))
        if card.bowed is bowed
    ]


def _aligned_with_the_elements_bare_enemies(game: GameState, seat: PlayerId) -> tuple[str, ...]:
    """The enemy cards without attachments the action may target where they stand. A Stronghold is
    left out, as Ring of Fire's same wording leaves it out."""
    return tuple(
        card.id
        for card in game.table.battlefield.cards
        if card.owner is not seat
        and not isinstance(card.printed, StrongholdPrint)
        and not attachments_of(game, card)
        and location_permits(game, card)
    )


def _aligned_with_the_elements_attachments(game: GameState) -> tuple[str, ...]:
    """Every attachment the action may target where it stands, either seat's."""
    return tuple(
        card.id
        for card in game.table.battlefield.cards
        if isinstance(card.printed, AttachmentPrint)
        and attached_to(game, card) is not None
        and location_permits(game, card)
    )


def _aligned_with_the_elements_bow_targets(game: GameState, source: L5RCard) -> list[str]:
    """Your unbowed Rings, once there is an enemy card without attachments to bow."""
    if not _aligned_with_the_elements_bare_enemies(game, source.owner):
        return []
    return _aligned_with_the_elements_rings(game, source, bowed=False)


def _aligned_with_the_elements_bow_effects(
    game: GameState, source: L5RCard, target: L5RCard
) -> list[Effect]:
    """ "Bow your target unbowed Ring to bow a target enemy card": a Ring bowed by the time this
    resolves bows nothing, so nothing else happens (CR, To)."""
    if target.bowed:
        return []
    enemies = _aligned_with_the_elements_bare_enemies(game, source.owner)
    return [
        Bow(target.id),
        Choose(source.owner, enemies, 1, 1, "aligned_with_the_elements_bow", source.id),
    ]


@choice_resolver(
    "aligned_with_the_elements_bow", prompt="Bow a target enemy card without attachments"
)
def _resolve_aligned_with_the_elements_bow(
    game: GameState, source_id: str, chosen: tuple[str, ...], seat: PlayerId
) -> list[Effect]:
    return [Bow(chosen[0])]


def _aligned_with_the_elements_straighten_targets(game: GameState, source: L5RCard) -> list[str]:
    """Your bowed Rings, once there is an attachment to target with one."""
    if not _aligned_with_the_elements_attachments(game):
        return []
    return _aligned_with_the_elements_rings(game, source, bowed=True)


def _aligned_with_the_elements_straighten_effects(
    game: GameState, source: L5RCard, target: L5RCard
) -> list[Effect]:
    attachments = _aligned_with_the_elements_attachments(game)
    return [
        Choose(source.owner, attachments, 1, 1, "aligned_with_the_elements_straighten", target.id)
    ]


@choice_resolver("aligned_with_the_elements_straighten", prompt="Target an attachment")
def _resolve_aligned_with_the_elements_straighten(
    game: GameState, source_id: str, chosen: tuple[str, ...], seat: PlayerId
) -> list[Effect]:
    """ "Straighten them": the Ring, which stands as the choice's source, and the attachment."""
    return [Straighten(source_id), Straighten(chosen[0])]


register_ability(
    "aligned_with_the_elements",
    Ability(
        timings=(ActionTiming.BATTLE,),
        cost=no_cost,
        targets=_aligned_with_the_elements_bow_targets,
        targeting_message="your unbowed Ring",
        effects=_aligned_with_the_elements_bow_effects,
        located_at=(CardLocation.HAND,),
        key="bow",
    ),
)
register_ability(
    "aligned_with_the_elements",
    Ability(
        timings=(ActionTiming.BATTLE,),
        cost=no_cost,
        targets=_aligned_with_the_elements_straighten_targets,
        targeting_message="your bowed Ring",
        effects=_aligned_with_the_elements_straighten_effects,
        located_at=(CardLocation.HAND,),
        key="straighten",
    ),
)
