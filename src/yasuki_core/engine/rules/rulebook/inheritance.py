from yasuki_core.engine.rules import triggers
from yasuki_core.engine.rules.board.queries import owned_holdings
from yasuki_core.engine.rules.vocabulary.decisions import ChooseInheritanceTarget, DecisionResponse
from yasuki_core.engine.rules.effects import GrantModifier
from yasuki_core.engine.rules.legality import (
    inheritance_key,
    INHERITANCE_PRODUCTION,
    seat_stronghold,
)
from yasuki_core.engine.rules.vocabulary.modifiers import Duration, Stat
from yasuki_core.engine.rules.state import GameState


def inheritance(game: GameState) -> None:
    """Announce the Inheritance ability by asking which Holding it raises. ``legal_actions`` has
    already checked the seat did not go first, has not spent the ability, and has both a Stronghold
    to turn over and a Holding to raise."""
    seat = game.active
    game.pending = ChooseInheritanceTarget(
        seat=seat,
        candidates=tuple(card.id for card in owned_holdings(game, seat)),
    )


def apply_inheritance_target(
    game: GameState, request: ChooseInheritanceTarget, response: DecisionResponse
) -> None:
    """Spend the once-per-game use, turn the Stronghold over, and raise the chosen Holding.

    The Stronghold turns over rather than to a named face: a seat whose Stronghold a card has
    already flipped turns it back (ShE, The Inheritance Rule).
    """
    seat = request.seat
    game.pending = None
    game.use_once(inheritance_key(seat))
    stronghold = seat_stronghold(game, seat)
    stronghold.flip_face()
    triggers.resolve_effects(
        game,
        [
            GrantModifier(
                source_id=stronghold.id,
                target_id=response.choices[0],
                stat=Stat.GOLD_PRODUCTION,
                amount=INHERITANCE_PRODUCTION,
                duration=Duration.UNTIL_END_OF_TURN,
            )
        ],
    )
