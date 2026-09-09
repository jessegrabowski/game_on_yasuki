from yasuki_core.engine.players import PlayerId
from yasuki_core.engine.rules.board.queries import province_key_of
from yasuki_core.engine.rules.effects import Discard, DrawCard, Effect, RefillProvince, Then
from yasuki_core.engine.rules.legality import KHARMIC_COST
from yasuki_core.engine.rules.rulebook.costs import announce_rulebook_cost
from yasuki_core.engine.rules.state import GameState
from yasuki_core.game_pieces import keywords


def kharmic_draw(game: GameState, card_id: str) -> None:
    """Announce the Fate Kharmic ability: discard ``card_id`` from hand to draw a card."""
    seat = game.round.priority
    _announce_kharmic(game, seat, (Discard(card_id, seat), Then((DrawCard(seat),))))


def kharmic_refill(game: GameState, card_id: str) -> None:
    """Announce the Dynasty Kharmic ability: discard ``card_id`` from its Province and refill that
    Province face-up."""
    seat = game.round.priority
    vacated = province_key_of(game, seat, card_id)
    _announce_kharmic(
        game, seat, (Discard(card_id, seat), Then((RefillProvince(vacated, face_up=True),)))
    )


def _announce_kharmic(game: GameState, seat: PlayerId, effects: tuple[Effect, ...]) -> None:
    """Pause for the gold cost both Kharmic forms share, queueing ``effects`` behind it. Repeatable,
    so no once-per-turn key is claimed."""
    game.pending = announce_rulebook_cost(game, seat, KHARMIC_COST, keywords.KHARMIC, effects)
