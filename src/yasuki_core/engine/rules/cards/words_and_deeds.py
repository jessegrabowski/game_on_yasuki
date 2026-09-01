from yasuki_core.engine.players import PlayerId
from yasuki_core.engine.rules.abilities import Ability, register_ability
from yasuki_core.engine.rules.actions import ActionTiming
from yasuki_core.engine.rules.effects import Ask, Bow, CreateToken, Effect, PayGold, Unpayable
from yasuki_core.engine.rules.equip import creation_targets
from yasuki_core.engine.rules.payments import can_afford
from yasuki_core.engine.rules.state import GameState
from yasuki_core.engine.rules.triggers import choice_resolver
from yasuki_core.game_pieces.cards import L5RCard


# --- Militia Training Ground ---

MILITIA_RECRUIT = "militia_recruit"
GOLD_INSTEAD_OF_BOWING = 2


def _militia_training_ground_cost(game: GameState, source: L5RCard) -> list[Effect]:
    """Bow, or pay 2 Gold.

    The seat is asked only while both are open to it. With one way left the card charges that one
    without asking, and with neither it is unpayable, so the ability is never offered as a question
    the seat cannot answer.
    """
    seat = source.owner
    may_bow = not source.bowed
    may_pay = can_afford(game, seat, GOLD_INSTEAD_OF_BOWING)
    if may_bow and may_pay:
        return [
            Ask(
                seat,
                f"Pay {GOLD_INSTEAD_OF_BOWING} gold instead of bowing {source.name}?",
                "militia_training_ground",
                subjects=(source.id,),
                source_id=source.id,
            )
        ]
    if may_bow:
        return [Bow(source.id)]
    if may_pay:
        return [PayGold(seat, GOLD_INSTEAD_OF_BOWING, source.name)]
    return [Unpayable(f"{source.id} can neither bow nor raise {GOLD_INSTEAD_OF_BOWING} gold")]


@choice_resolver("militia_training_ground")
def _resolve_militia_training_ground(
    game: GameState, source_id: str, chosen: tuple[str, ...], seat: PlayerId
) -> list[Effect]:
    if not chosen:
        return [Bow(source_id)]
    return [PayGold(seat, GOLD_INSTEAD_OF_BOWING, game.table.cards_by_id[source_id].name)]


def _militia_training_ground_targets(game: GameState, source: L5RCard) -> list[str]:
    recruit = game.table.creatable_tokens[MILITIA_RECRUIT]
    return [target.id for target in creation_targets(game, source.owner, recruit)]


def _militia_training_ground_effects(
    game: GameState, source: L5RCard, target: L5RCard
) -> list[Effect]:
    return [CreateToken(MILITIA_RECRUIT, source.owner, source.id, attach_to=target.id)]


register_ability(
    "militia_training_ground",
    Ability(
        timings=(ActionTiming.OPEN,),
        label=f"Open: Bow or pay {GOLD_INSTEAD_OF_BOWING} gold to Equip a 0F Follower",
        cost=_militia_training_ground_cost,
        targets=_militia_training_ground_targets,
        effects=_militia_training_ground_effects,
    ),
)
