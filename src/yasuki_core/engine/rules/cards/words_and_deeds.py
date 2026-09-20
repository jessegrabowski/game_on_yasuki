from dataclasses import replace

from yasuki_core.engine.players import PlayerId
from yasuki_core.engine.rules.abilities.activation import ResolveAbility
from yasuki_core.engine.rules.abilities.model import Ability, Interrupt, Interruption
from yasuki_core.engine.rules.abilities.registry import register_ability, register_interrupt
from yasuki_core.engine.rules.vocabulary.actions import ActionTiming
from yasuki_core.engine.rules.board.queries import has_keyword
from yasuki_core.engine.rules.effects import Ask, Bow, CreateToken, Effect, PayGold, Unpayable
from yasuki_core.engine.rules.rulebook.equip import creation_targets
from yasuki_core.engine.rules.gold.payment import can_afford
from yasuki_core.engine.rules.interrupts import legal_substitutes
from yasuki_core.engine.rules.state import GameState
from yasuki_core.engine.rules.triggers import choice_resolver
from yasuki_core.engine.rules.vocabulary import keywords
from yasuki_core.game_pieces.cards import L5RCard


# --- Final Sacrifice ---


def _final_sacrifice_targets(
    game: GameState, source: L5RCard, targeting: ResolveAbility
) -> tuple[str, ...]:
    """Your Yojimbo the action could target instead: "if legal", so one the ability could not
    have targeted is not offered."""
    yojimbo = [
        card.id
        for card in game.table.battlefield.cards
        if card.owner is source.owner and has_keyword(game, card, keywords.YOJIMBO)
    ]
    return legal_substitutes(game, targeting, yojimbo)


def _final_sacrifice_interrupt(
    game: GameState, source: L5RCard, targeting: ResolveAbility, target: L5RCard
) -> Interruption:
    """ "Interrupt: Target your Yojimbo. The action targets him instead of another card, if
    legal." """
    return Interruption(replace(targeting, target_id=target.id, effects=None))


register_interrupt(
    "final_sacrifice",
    Interrupt(
        label="Interrupt: the action targets your Yojimbo instead of another card, if legal",
        answers=ResolveAbility,
        interrupt=_final_sacrifice_interrupt,
        targets=_final_sacrifice_targets,
    ),
)


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
