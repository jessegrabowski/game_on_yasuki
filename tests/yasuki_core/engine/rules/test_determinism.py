import hashlib
import json

from yasuki_core.engine.players import PlayerId
from yasuki_core.engine.table import TableState, ZoneKey, ZoneRole, DeckKey
from yasuki_core.game_pieces.constants import Side
from yasuki_core.game_pieces.fate import FateCard
from yasuki_core.engine.snapshot import InitialRecord, encode_initial
from yasuki_core.engine.rules.state import GameState
from yasuki_core.engine.rules.decisions import DecisionResponse
from yasuki_core.engine.rules import flow
from yasuki_core.engine.rules.actions import Pass
from yasuki_core.engine.rules.log import (
    GameLog,
    build_game,
    act_and_log,
    submit_and_log,
    replay,
    game_log_to_dict,
    game_log_from_dict,
)


def _register(state: TableState, card):
    state.cards_by_id[card.id] = card
    return card


def _dealt_table() -> TableState:
    """A two-seat table with stocked fate decks and a full P1 hand, so P1's turns end in a discard
    while P2's do not."""
    state = TableState.empty_two_seat()
    for seat in PlayerId:
        state.decks[DeckKey(seat, Side.FATE)].cards = [
            _register(
                state, FateCard(id=f"{seat.name}-fd{i}", name="F", side=Side.FATE, owner=seat)
            )
            for i in range(5)
        ]
    hand = state.zones[ZoneKey(PlayerId.P1, ZoneRole.HAND)]
    for i in range(flow.MAX_HAND_SIZE):
        hand.add(
            _register(state, FateCard(id=f"P1-h{i}", name="H", side=Side.FATE, owner=PlayerId.P1))
        )
    return state


def _discard_top_of_hand(game: GameState, log: GameLog) -> None:
    victim = game.table.zones[ZoneKey(PlayerId.P1, ZoneRole.HAND)].cards[0].id
    submit_and_log(game, log, DecisionResponse((victim,)))


def _play_three_turns(game: GameState, log: GameLog) -> None:
    for _ in range(3):  # P1 turn 1: into the end-of-turn discard
        act_and_log(game, log, Pass())
    _discard_top_of_hand(game, log)
    for _ in range(3):  # P2 turn 2: small hand, no discard
        act_and_log(game, log, Pass())
    for _ in range(3):  # P1 turn 3: discards again
        act_and_log(game, log, Pass())
    _discard_top_of_hand(game, log)


def _fingerprint(game: GameState) -> str:
    """A canonical sha256 over the full final state — the table plus every rules field — so any
    divergence in a replay changes the digest."""
    canonical = {
        "table": encode_initial(InitialRecord.from_state(game.table)),
        "turn": game.turn,
        "active": game.active.name,
        "phase": game.phase.value,
        "first_player": game.first_player.name,
        "gold": {seat.name: amount for seat, amount in game.gold.items()},
        "favor_holder": None if game.favor_holder is None else game.favor_holder.name,
        "once_per": sorted(game.once_per),
        "seed": game.seed,
        "pending": repr(game.pending),
        "stack": repr(game.stack),
    }
    return hashlib.sha256(json.dumps(canonical, sort_keys=True).encode()).hexdigest()


def test_replay_is_deterministic_across_runs_and_serialization():
    log = GameLog(
        initial=InitialRecord.from_state(_dealt_table()), first_player=PlayerId.P1, seed=42
    )
    live = build_game(log)
    _play_three_turns(live, log)
    expected = _fingerprint(live)

    assert live.turn == 4 and not live.awaiting_decision  # the script ran to a clean turn boundary

    # Replaying the tape reproduces the exact final state, every time...
    assert _fingerprint(replay(log)) == expected
    assert _fingerprint(replay(log)) == expected
    # ...and survives a round-trip through the serialized save format.
    restored = game_log_from_dict(json.loads(json.dumps(game_log_to_dict(log))))
    assert _fingerprint(restored.replay()) == expected
