from yasuki_core.engine.players import PlayerId
from yasuki_core.engine.rules.gold.self_grants import register_self_grant, SELF_GRANT, self_grant
from yasuki_core.engine.rules.board.seats import went_second
from yasuki_core.engine.rules.abilities.costs import bow_cost
from yasuki_core.engine.rules.abilities.model import Ability, itself
from yasuki_core.engine.rules.abilities.registry import register_ability
from yasuki_core.engine.rules.board.queries import top_of_deck
from yasuki_core.engine.rules.effects import (
    Arrange,
    DelayStraighten,
    Destroy,
    DrawCard,
    Effect,
    GainHonor,
    GrantModifier,
    LookAtTop,
)
from yasuki_core.engine.rules.rulebook.looks import PUT_BACK_ON_TOP
from yasuki_core.engine.rules.vocabulary.actions import ActionTiming
from yasuki_core.engine.table import DeckKey
from yasuki_core.game_pieces.constants import Side
from yasuki_core.engine.rules.vocabulary.game_events import ProducingGold
from yasuki_core.engine.rules.vocabulary.modifiers import Duration, Stat
from yasuki_core.engine.rules.gold.payment import offer_self_grant
from yasuki_core.engine.rules.state import GameState, claim_once_per_turn
from yasuki_core.engine.rules.triggers import TriggerContext, choice_resolver, on
from yasuki_core.game_pieces.cards import L5RCard


# --- Divination Bowl ---

DIVINATION_BOWL_LOOK = 3


def _divination_bowl_look_effects(
    game: GameState, source: L5RCard, target: L5RCard
) -> list[Effect]:
    seat = source.owner
    fate = DeckKey(seat, Side.FATE)
    seen = top_of_deck(game, fate, DIVINATION_BOWL_LOOK)
    if not seen:
        return []
    return [LookAtTop(seat, fate, len(seen)), Arrange(seat, seen, PUT_BACK_ON_TOP, source.id)]


def _divination_bowl_draw_effects(
    game: GameState, source: L5RCard, target: L5RCard
) -> list[Effect]:
    return [DrawCard(source.owner), Destroy(source.id, source.owner)]


register_ability(
    "divination_bowl",
    Ability(
        key="look",
        timings=(ActionTiming.LIMITED,),
        cost=bow_cost,
        targets=itself,
        hits_every_target=True,
        effects=_divination_bowl_look_effects,
    ),
)
register_ability(
    "divination_bowl",
    Ability(
        printed_index=1,
        key="draw",
        timings=(ActionTiming.LIMITED,),
        cost=bow_cost,
        targets=itself,
        hits_every_target=True,
        effects=_divination_bowl_draw_effects,
    ),
)


# --- Jade Mine ---

JADE_MINE_GRANT = 1

register_self_grant("jade_mine", JADE_MINE_GRANT)


@on(ProducingGold, "jade_mine")
def _jade_mine_producing_gold(ctx: TriggerContext) -> list[Effect]:
    """ "When this Holding produces Gold, you may give it +1GP. If you do, it will not straighten
    until after your next Action Phase." """
    return offer_self_grant(
        ctx,
        f"Give Jade Mine +{JADE_MINE_GRANT}GP (this turn)? "
        "It will not straighten until after your next Action Phase.",
        "jade_mine_grant",
    )


@choice_resolver("jade_mine_grant")
def _resolve_jade_mine_grant(
    game: GameState, source_id: str | None, chosen: tuple[str, ...], seat: PlayerId
) -> list[Effect]:
    if not chosen:
        return []
    card = game.table.cards_by_id[chosen[0]]
    claim_once_per_turn(game, card, SELF_GRANT)
    return [
        GrantModifier(
            card.id, card.id, Stat.GOLD_PRODUCTION, JADE_MINE_GRANT, Duration.UNTIL_END_OF_TURN
        ),
        DelayStraighten(card.id),
    ]


# --- Slave Pits ---

SLAVE_PITS_GRANT = 1
SLAVE_PITS_HONOR_COST = 2


@self_grant("slave_pits")
def _slave_pits_gold(card: L5RCard, game: GameState, seat: PlayerId) -> int:
    """Courtesy offers nothing to the player who went first, so affordability must not count it for
    them, since a grant it counted and the window then withheld would strand the purchase."""
    return SLAVE_PITS_GRANT if went_second(game, seat) else 0


@on(ProducingGold, "slave_pits")
def _slave_pits_producing_gold(ctx: TriggerContext) -> list[Effect]:
    """ "Courtesy: When this Holding produces Gold, you may give it +1GP and lose 2 Honor." """
    return offer_self_grant(
        ctx,
        f"Give Slave Pits +{SLAVE_PITS_GRANT}GP (this turn) "
        f"and lose {SLAVE_PITS_HONOR_COST} Honor?",
        "slave_pits_grant",
    )


@choice_resolver("slave_pits_grant")
def _resolve_slave_pits_grant(
    game: GameState, source_id: str | None, chosen: tuple[str, ...], seat: PlayerId
) -> list[Effect]:
    if not chosen:
        return []
    card = game.table.cards_by_id[chosen[0]]
    claim_once_per_turn(game, card, SELF_GRANT)
    return [
        GrantModifier(
            card.id, card.id, Stat.GOLD_PRODUCTION, SLAVE_PITS_GRANT, Duration.UNTIL_END_OF_TURN
        ),
        GainHonor(seat, -SLAVE_PITS_HONOR_COST),
    ]
