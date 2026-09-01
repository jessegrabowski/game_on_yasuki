from yasuki_core.engine.players import PlayerId
from yasuki_core.engine.rules.abilities import (
    Ability,
    CardLocation,
    no_cost,
    personalities_in_play,
    register_ability,
)
from yasuki_core.engine.rules.actions import ActionTiming, BattleDesignator
from yasuki_core.engine.rules.effects import (
    Ask,
    Bow,
    CreateToken,
    Effect,
    Move,
    PayGold,
)
from yasuki_core.engine.rules.payments import can_afford
from yasuki_core.engine.rules.state import GameState
from yasuki_core.engine.rules.triggers import choice_resolver
from yasuki_core.engine.rules.units import followers_of
from yasuki_core.engine.table import Location
from yasuki_core.game_pieces.cards import L5RCard


# --- Refugees ---

# "The target's controller may pay :g1:" and what it buys, as the card prints them.
ASHIGARU = "ashigaru_2"
ASHIGARU_GOLD = 1


def _refugees_targets(game: GameState, source: L5RCard) -> list[str]:
    """Every Personality with no Follower attached, either side's — the card names no side."""
    return [card.id for card in personalities_in_play(game) if not followers_of(game, card)]


def _refugees_effects(game: GameState, source: L5RCard, target: L5RCard) -> list[Effect]:
    """Send the target home, bow them as they move, then offer their controller the Ashigaru.

    The offer is withheld from a controller who could not pay it, which is what "may pay" means for
    a seat with no Gold to reach.
    """
    controller = target.owner
    # The bow rides the movement, so a card negating the move — The Height of Courage — should take
    # the bow with it. Nothing can negate one until the Interrupt layer exists, so the two never
    # differ yet and the bow is written plainly.
    sent_home: list[Effect] = [Move(target.id, Location.home(controller)), Bow(target.id)]
    if not can_afford(game, controller, ASHIGARU_GOLD):
        return sent_home
    return [
        *sent_home,
        Ask(
            controller,
            f"Pay {ASHIGARU_GOLD} Gold to create a 1F Ashigaru Follower and attach it to "
            f"{target.name}?",
            "refugees",
            subjects=(target.id,),
            source_id=source.id,
        ),
    ]


@choice_resolver("refugees")
def _resolve_refugees(
    game: GameState, source_id: str, chosen: tuple[str, ...], seat: PlayerId
) -> list[Effect]:
    """Declining costs nothing and buys nothing; the Follower is the controller's own."""
    if not chosen:
        return []
    return [
        PayGold(seat, ASHIGARU_GOLD, "Refugees"),
        CreateToken(ASHIGARU, seat, source_id, attach_to=chosen[0]),
    ]


register_ability(
    "refugees",
    Ability(
        timings=(ActionTiming.BATTLE,),
        label="Absent Battle: Move home a target Personality without Followers. Bow the target as "
        "they move. The target's controller may pay 1 Gold to create a 1F Ashigaru Follower and "
        "attach it to them",
        cost=no_cost,
        targets=_refugees_targets,
        effects=_refugees_effects,
        located_at=(CardLocation.HAND,),
        battle=frozenset({BattleDesignator.ABSENT}),
    ),
)
