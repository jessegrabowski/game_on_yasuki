from dataclasses import dataclass

from yasuki_core.engine.players import PlayerId
from yasuki_core.engine.redaction import redact, ViewSnapshot
from yasuki_core.engine.rules.state import GameState, Phase
from yasuki_core.engine.rules.decisions import DecisionRequest


@dataclass(frozen=True, slots=True)
class GameView:
    """A per-seat projection of a :class:`GameState` — everything one seat is entitled to see.

    The table is redacted for the viewer (the opponent's hand, face-down cards, and deck contents
    appear as backs); the turn-level rules fields are public to both seats; and a pending decision
    reaches only the seat that must answer it.

    Attributes
    ----------
    viewer : PlayerId
        The seat this view is built for.
    table : ViewSnapshot
        The viewer's redacted view of the board.
    turn : int
        The current turn number.
    active : PlayerId
        The seat whose turn it is.
    phase : Phase
        The current phase.
    first_player : PlayerId
        The seat that took the first turn.
    gold : dict mapping PlayerId to int
        Every seat's gold pool — public to both seats.
    favor_holder : PlayerId or None
        The seat holding the Imperial Favor, or None.
    pending : DecisionRequest or None
        The decision the viewer must answer, or None when nothing is awaited from this viewer —
        including when the engine is instead waiting on the other seat.
    """

    viewer: PlayerId
    table: ViewSnapshot
    turn: int
    active: PlayerId
    phase: Phase
    first_player: PlayerId
    gold: dict[PlayerId, int]
    favor_holder: PlayerId | None
    pending: DecisionRequest | None


def project(game: GameState, viewer: PlayerId) -> GameView:
    """Project ``game`` into the view ``viewer`` is entitled to: the board redacted for the viewer,
    the public rules fields, and the pending decision only if this viewer is the one to answer
    it."""
    pending = game.pending if game.pending is not None and game.pending.seat is viewer else None
    return GameView(
        viewer=viewer,
        table=redact(game.table, viewer),
        turn=game.turn,
        active=game.active,
        phase=game.phase,
        first_player=game.first_player,
        gold=dict(game.gold),
        favor_holder=game.favor_holder,
        pending=pending,
    )
