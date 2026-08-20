from yasuki_core import ruleset
from yasuki_core.engine.rules.abilities import Ability, register_ability
from yasuki_core.engine.rules.actions import ActionTiming
from yasuki_core.engine.rules.economy import PlayerState, is_clan, recruit_discount
from yasuki_core.engine.rules.effects import CreateToken, Effect, PayGold
from yasuki_core.engine.rules.equip import creation_targets
from yasuki_core.engine.rules.state import GameState
from yasuki_core.game_pieces.cards import L5RCard


# --- Colonial Farm ---

ASHIGARU = "ashigaru_2"
ASHIGARU_COST = 3


@recruit_discount("colonial_farm")
def _colonial_farm(card: L5RCard, me: PlayerState, opponents: tuple[PlayerState, ...]) -> int:
    """Enters play for 1 less Gold if you are a Lion Clan player."""
    return 1 if is_clan(me, ruleset.LION) else 0


def _colonial_farm_cost(game: GameState, source: L5RCard) -> list[Effect]:
    return [PayGold(source.owner, ASHIGARU_COST, source.name)]


def _colonial_farm_targets(game: GameState, source: L5RCard) -> list[str]:
    ashigaru = game.table.creatable_tokens[ASHIGARU]
    return [target.id for target in creation_targets(game, source.owner, ashigaru)]


def _colonial_farm_effects(game: GameState, source: L5RCard, target: L5RCard) -> list[Effect]:
    return [CreateToken(ASHIGARU, source.owner, source.id, attach_to=target.id)]


register_ability(
    "colonial_farm",
    Ability(
        timing=ActionTiming.OPEN,
        label=f"Open: Pay {ASHIGARU_COST} gold to Equip a 1F Ashigaru Follower to a Personality",
        cost=_colonial_farm_cost,
        targets=_colonial_farm_targets,
        effects=_colonial_farm_effects,
    ),
)
