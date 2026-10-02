from yasuki_core.engine.players import PlayerId
from yasuki_core.engine.rules.abilities.costs import no_cost
from yasuki_core.engine.rules.abilities.model import (
    Ability,
    CardLocation,
    Interrupt,
    Interruption,
    itself,
)
from yasuki_core.engine.rules.abilities.registry import register_ability, register_interrupt
from yasuki_core.engine.rules.board.counts_as import Asking
from yasuki_core.engine.rules.board.queries import (
    has_keyword,
    owned_personalities,
    remaining_look,
    rings_in_play,
    top_of_deck,
)
from yasuki_core.engine.rules.effects import (
    Arrange,
    Bow,
    Choose,
    Effect,
    EndLook,
    GrantConditionalModifier,
    LookAtTop,
    Move,
    MoveToHand,
    Negated,
    SpendSeatOncePerTurn,
)
from yasuki_core.engine.rules.legality import location_permits
from yasuki_core.engine.rules.rulebook.looks import PUT_ON_BOTTOM
from yasuki_core.engine.rules.state import GameState, seat_once_key
from yasuki_core.engine.rules.triggers import choice_resolver
from yasuki_core.engine.rules.vocabulary import keywords
from yasuki_core.engine.rules.vocabulary.actions import ActionTiming
from yasuki_core.engine.rules.vocabulary.modifiers import Condition, Duration, Stat
from yasuki_core.engine.rules.units.membership import attached_to
from yasuki_core.engine.table import DeckKey, location_of
from yasuki_core.game_pieces.cards import L5RCard
from yasuki_core.game_pieces.prints import PersonalityPrint, StrongholdPrint
from yasuki_core.game_pieces.constants import Side


# --- Banish All Doubt ---

BANISH_ALL_DOUBT_LOOK = 4


def _banish_all_doubt_targets(game: GameState, source: L5RCard) -> list[str]:
    """Your unbowed Tacticians. The Tactician performs the action and is not bowed by it."""
    return [
        card.id
        for card in owned_personalities(game, source.owner)
        if not card.bowed and has_keyword(game, card, keywords.TACTICIAN)
    ]


def _banish_all_doubt_effects(game: GameState, source: L5RCard, target: L5RCard) -> list[Effect]:
    """Look at the top four and take one. An empty deck leaves nothing to do."""
    seat = source.owner
    fate = DeckKey(seat, Side.FATE)
    seen = top_of_deck(game, fate, BANISH_ALL_DOUBT_LOOK)
    if not seen:
        return []
    return [
        LookAtTop(seat, fate, len(seen)),
        Choose(seat, seen, 1, 1, "banish_all_doubt", source.id),
    ]


@choice_resolver("banish_all_doubt", prompt="Put one of them in your hand")
def _resolve_banish_all_doubt(
    game: GameState, source_id: str, chosen: tuple[str, ...], seat: PlayerId
) -> list[Effect]:
    """The other three go on the bottom in the order the seat gives."""
    rest = tuple(card_id for card_id in remaining_look(game) if card_id not in chosen)
    taken = [MoveToHand(card_id, seat) for card_id in chosen]
    if not rest:
        return [*taken, EndLook()]
    return [*taken, Arrange(seat, rest, PUT_ON_BOTTOM, source_id, to_bottom=True)]


register_ability(
    "banish_all_doubt",
    Ability(
        timings=(ActionTiming.LIMITED,),
        keywords=frozenset({keywords.TACTICAL}),
        cost=no_cost,
        targets=_banish_all_doubt_targets,
        targeting_message="your performing unbowed Tactician",
        effects=_banish_all_doubt_effects,
        located_at=(CardLocation.HAND,),
    ),
)


# --- Cowed by Wisdom ---


def _cowed_by_wisdom_applies(game: GameState, source: L5RCard, effect: Move) -> bool:
    """ "The action's movement of other players' Personalities from the current battlefield", read
    off the unit the Move names a card in."""
    attack = game.attack
    card = game.table.cards_by_id.get(effect.card_id)
    if attack is None or attack.current is None or card is None:
        return False
    personality = card if isinstance(card.printed, PersonalityPrint) else attached_to(game, card)
    if personality is None or personality.owner is source.owner:
        return False
    return (
        location_of(game.table, personality).battlefield == attack.current
        and effect.to.battlefield != attack.current
    )


def _cowed_by_wisdom_interrupt(game: GameState, source: L5RCard, effect: Move) -> Interruption:
    return Interruption(Negated(effect))


register_interrupt(
    "cowed_by_wisdom",
    Interrupt(
        answers=Move,
        interrupt=_cowed_by_wisdom_interrupt,
        applies=_cowed_by_wisdom_applies,
        answers_every=True,
    ),
)


def _cowed_by_wisdom_enemies(game: GameState, seat: PlayerId) -> tuple[str, ...]:
    """The enemy cards the action may target where they stand. A Stronghold is left out, as
    Ring of Fire leaves it out of "a target enemy card"."""
    return tuple(
        card.id
        for card in game.table.battlefield.cards
        if card.owner is not seat
        and not isinstance(card.printed, StrongholdPrint)
        and location_permits(game, card)
    )


def _cowed_by_wisdom_targets(game: GameState, source: L5RCard) -> list[str]:
    """Your unbowed Personalities, once there is an enemy card to bow."""
    if not _cowed_by_wisdom_enemies(game, source.owner):
        return []
    return [card.id for card in owned_personalities(game, source.owner) if not card.bowed]


def _cowed_by_wisdom_effects(game: GameState, source: L5RCard, target: L5RCard) -> list[Effect]:
    """ "Bow them unless you control a Ring. Bow a target enemy card." The enemy card bows either
    way."""
    enemies = _cowed_by_wisdom_enemies(game, source.owner)
    bow_enemy = Choose(source.owner, enemies, 1, 1, "cowed_by_wisdom", source.id)
    if rings_in_play(game, source.owner, Asking.action(source)):
        return [bow_enemy]
    return [Bow(target.id), bow_enemy]


@choice_resolver("cowed_by_wisdom", prompt="Bow a target enemy card")
def _resolve_cowed_by_wisdom(
    game: GameState, source_id: str, chosen: tuple[str, ...], seat: PlayerId
) -> list[Effect]:
    return [Bow(chosen[0])]


register_ability(
    "cowed_by_wisdom",
    Ability(
        printed_index=1,
        timings=(ActionTiming.BATTLE,),
        cost=no_cost,
        targets=_cowed_by_wisdom_targets,
        targeting_message="your unbowed Personality",
        effects=_cowed_by_wisdom_effects,
        located_at=(CardLocation.HAND,),
    ),
)


# --- Flashy Technique ---

FLASHY_TECHNIQUE = "flashy_technique"
FLASHY_TECHNIQUE_PENALTY = -1


def _flashy_technique_effects(game: GameState, source: L5RCard, target: L5RCard) -> list[Effect]:
    """The penalty, unless its controller has played another Flashy Technique this turn, in which
    case the action is legal and does nothing. The Focus Effect only applies inside a duel and none
    is fought yet."""
    if game.has_used(seat_once_key(source.owner, FLASHY_TECHNIQUE, game.turn)):
        return []
    return [
        SpendSeatOncePerTurn(source.owner, FLASHY_TECHNIQUE),
        GrantConditionalModifier(
            source.id,
            Condition.ATTACKING,
            Stat.FORCE,
            FLASHY_TECHNIQUE_PENALTY,
            Duration.UNTIL_END_OF_TURN,
        ),
    ]


register_ability(
    "flashy_technique",
    Ability(
        timings=(ActionTiming.OPEN,),
        cost=no_cost,
        targets=itself,
        effects=_flashy_technique_effects,
        located_at=(CardLocation.HAND,),
        hits_every_target=True,
    ),
)
