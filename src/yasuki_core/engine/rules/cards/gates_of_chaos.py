from yasuki_core.engine.players import PlayerId
from yasuki_core.engine.rules.economy import (
    SELF_GRANT,
    PlayerState,
    register_self_grant,
    self_grant,
)
from yasuki_core.engine.rules.effects import DelayStraighten, Effect, GainHonor, GrantModifier
from yasuki_core.engine.rules.events import ProducingGold
from yasuki_core.engine.rules.modifiers import Duration, Stat
from yasuki_core.engine.rules.payments import offer_self_grant
from yasuki_core.engine.rules.state import GameState, once_per_turn
from yasuki_core.engine.rules.triggers import TriggerContext, choice_resolver, on
from yasuki_core.game_pieces.cards import L5RCard


# --- Jade Mine ---

JADE_MINE_GRANT = 1

register_self_grant("jade_mine", JADE_MINE_GRANT)


@on(ProducingGold, "jade_mine")
def _jade_mine_producing_gold(ctx: TriggerContext) -> list[Effect]:
    """ "When this Holding produces Gold, you may give it +1GP; if you do, it will not straighten
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
    once_per_turn(game, card, SELF_GRANT)
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
def _slave_pits_gold(card: L5RCard, me: PlayerState, opponents: tuple[PlayerState, ...]) -> int:
    """Courtesy offers nothing to the player who went first, so affordability must not count it for
    them — a grant it counted and the window then withheld would strand the purchase."""
    return SLAVE_PITS_GRANT if me.went_second else 0


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
    once_per_turn(game, card, SELF_GRANT)
    return [
        GrantModifier(
            card.id, card.id, Stat.GOLD_PRODUCTION, SLAVE_PITS_GRANT, Duration.UNTIL_END_OF_TURN
        ),
        GainHonor(seat, -SLAVE_PITS_HONOR_COST),
    ]
