from yasuki_core.engine.players import PlayerId
from yasuki_core.engine.rules.abilities.costs import bow_cost, no_cost
from yasuki_core.engine.rules.abilities.idioms import ask_whose_honor_moves
from yasuki_core.engine.rules.abilities.model import Ability, CardLocation, itself
from yasuki_core.engine.rules.abilities.registry import register_ability
from yasuki_core.engine.rules.board.queries import owned_personalities
from yasuki_core.engine.rules.vocabulary.actions import ActionTiming
from yasuki_core.engine.rules.gold.production import gold_handler
from yasuki_core.engine.rules.effects import Bow, Choose, DrawCard, Effect, PayGold
from yasuki_core.engine.rules.legality import location_permits
from yasuki_core.engine.rules.state import GameState
from yasuki_core.engine.rules.stats.keyword_grants import effective_keywords
from yasuki_core.engine.rules.triggers import choice_resolver
from yasuki_core.engine.rules.units.membership import attachments_of
from yasuki_core.engine.rules.vocabulary import keywords
from yasuki_core.game_pieces.cards import L5RCard


# --- Inexplicable Challenge ---

CHALLENGE_HONOR = 2


def _inexplicable_challenge_bowable(game: GameState, seat: PlayerId) -> tuple[str, ...]:
    """The enemy cards the challenge may bow: nothing attached to them, still standing, and within
    reach of the Rules of Location, which the card lifts for its Courtier alone.

    An already-bowed card is left out because bowing it would change nothing, and a target an
    effect cannot affect is no target (CR, Targeting).
    """
    return tuple(
        card.id
        for card in game.table.battlefield.cards
        if card.owner is not seat
        and not card.bowed
        and not attachments_of(game, card)
        and location_permits(game, card)
    )


def _inexplicable_challenge_targets(game: GameState, source: L5RCard) -> list[str]:
    """The controller's Courtiers, wherever they stand, once there is an enemy card to bow.

    The challenge names three targets and none of them is optional, so a board holding no card the
    second clause could reach withholds the action rather than resolving half of it.
    """
    if not _inexplicable_challenge_bowable(game, source.owner):
        return []
    return [
        personality.id
        for personality in owned_personalities(game, source.owner)
        if keywords.COURTIER in effective_keywords(game, personality)
    ]


def _inexplicable_challenge_effects(
    game: GameState, source: L5RCard, target: L5RCard
) -> list[Effect]:
    """Nothing happens to the Courtier named. The card to bow and the player whose Honor moves are
    the two targets asked for next."""
    return [
        Choose(
            source.owner,
            _inexplicable_challenge_bowable(game, source.owner),
            1,
            1,
            "inexplicable_challenge_bow",
            source.id,
        )
    ]


@choice_resolver("inexplicable_challenge_bow", prompt="Bow a target enemy card without attachments")
def _resolve_inexplicable_challenge_bow(
    game: GameState, source_id: str, chosen: tuple[str, ...], seat: PlayerId
) -> list[Effect]:
    return [Bow(chosen[0]), ask_whose_honor_moves(game, seat, CHALLENGE_HONOR, source_id)]


register_ability(
    "inexplicable_challenge",
    Ability(
        timings=(ActionTiming.BATTLE,),
        keywords=frozenset({keywords.POLITICAL}),
        label="Political Battle: Target your Courtier at any location to bow a target enemy card "
        f"without attachments and move a target player's Honor by {CHALLENGE_HONOR}",
        cost=no_cost,
        targets=_inexplicable_challenge_targets,
        targeting_message="your Courtier at any location",
        effects=_inexplicable_challenge_effects,
        located_at=(CardLocation.HAND,),
        targets_any_location=True,
    ),
)


# --- Traveling Peddler ---

PEDDLER_PRODUCTION = 2
PEDDLER_DRAW_COST = 3


@gold_handler("traveling_peddler")
def _traveling_peddler_gold(
    card: L5RCard, game: GameState, seat: PlayerId, targets: tuple[L5RCard, ...]
) -> int:
    """ "Produce 2 Gold", which the Peddler prints as text rather than as a Gold Production stat."""
    return PEDDLER_PRODUCTION


def _traveling_peddler_cost(game: GameState, source: L5RCard) -> list[Effect]:
    """Bow the Peddler and pay 3 Gold. Both, so the bowing this cost spends is not available to
    produce the Peddler's own gold."""
    return [
        *bow_cost(game, source),
        PayGold(source.owner, PEDDLER_DRAW_COST, source.name),
    ]


def _traveling_peddler_effects(game: GameState, source: L5RCard, target: L5RCard) -> list[Effect]:
    return [DrawCard(source.owner)]


register_ability(
    "traveling_peddler",
    Ability(
        timings=(ActionTiming.LIMITED,),
        label=f"Limited, Bow: Pay {PEDDLER_DRAW_COST} gold to draw a card",
        cost=_traveling_peddler_cost,
        targets=itself,
        effects=_traveling_peddler_effects,
        hits_every_target=True,
    ),
)
