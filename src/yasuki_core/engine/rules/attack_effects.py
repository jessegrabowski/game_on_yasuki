from collections.abc import Callable

from yasuki_core.engine.rules.effects import AttackEffect
from yasuki_core.engine.rules.registrar import HandlerRegistry
from yasuki_core.engine.rules.state import GameState
from yasuki_core.game_pieces.cards import L5RCard


# What a card's text does to an attack's strength. Every card in play is asked, because the scopes
# the corpus prints do not nest: a Follower speaks about itself, another about its unit, a Ring
# about every attack its controller makes. One walk and a handler that scopes itself is the only
# shape that holds all three.
AttackStrengthHandler = Callable[[GameState, L5RCard, L5RCard, AttackEffect], int]


ATTACK_STRENGTH_AGAINST: HandlerRegistry[AttackStrengthHandler] = HandlerRegistry(
    "attack strength", "already adjusts the attacks against it"
)


attack_strength_against = ATTACK_STRENGTH_AGAINST.make_decorator()


def effective_strength(game: GameState, attack: AttackEffect) -> int:
    """``attack``'s strength once every card in play has had its say.

    Not floored: a card that takes more strength off an attack than it had leaves it reaching
    nothing, which is what "have -2 strength" buys. The zero floor the CR puts on a stat
    (Calculating Stats) is about stats, and an attack's strength is not one.
    """
    target = game.table.cards_by_id.get(attack.target_id)
    if target is None:
        return attack.strength
    total = attack.strength
    for holder in game.table.battlefield.cards:
        handler = ATTACK_STRENGTH_AGAINST.get(holder.printed_id)
        if handler is not None:
            total += handler(game, holder, target, attack)
    return total
