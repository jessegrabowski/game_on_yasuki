from contextlib import contextmanager
from dataclasses import dataclass, replace

from yasuki_core import ruleset
from yasuki_core.engine import ops
from yasuki_core.engine.players import PlayerId, Rulebook
from yasuki_core.engine.rules.duel.focusing import FocusProcedure, focus_value
from yasuki_core.engine.rules.abilities.costs import no_cost
from yasuki_core.engine.rules.abilities.model import Ability
from yasuki_core.engine.rules.board.queries import personalities_in_play
from yasuki_core.engine.rules.duel.records import DuelRecord
from yasuki_core.engine.rules.effects import Destroy, Effect, GrantModifier, StartDuel
from yasuki_core.engine.rules.state import GameState
from yasuki_core.engine.rules.vocabulary.actions import ActionTiming, ActivateAbility
from yasuki_core.engine.rules.vocabulary.decisions import (
    DecisionResponse,
    focus_source,
    focus_token,
)
from yasuki_core.engine.session import EngineSession
from yasuki_core.engine.rules.vocabulary.modifiers import Duration, Stat
from yasuki_core.engine.table import TableState, ZoneKey, ZoneRole
from yasuki_core.game_pieces.cards import L5RCard

from tests.yasuki_core.engine.builders import focus_card, personality, put_in_play, register


@dataclass(frozen=True, slots=True)
class PreGoldFocusing:
    """The pre-Gold Edition focusing rules, as a second shape for the seam to be measured against.

    It differs from the shipped procedure on every axis the seam claims to own: only the hand is a
    legal source, nothing caps how often a seat focuses, each Focus Value applies as a secret duel
    stat bonus the moment its card is focused rather than totaling at the reveal, and the rulebook
    destroys the loser with no card saying so.

    A test fixture rather than a shipped arc. The engine plays Shattered Empire, and an Imperial
    ruleset is its own job with its own corpus questions.
    """

    focus_limit: int | None = None

    def sources(self, game: GameState, duel: DuelRecord, seat: PlayerId) -> tuple[str, ...]:
        hand = game.table.zones[ZoneKey(seat, ZoneRole.HAND)]
        return tuple(focus_token(card.id) for card in hand.cards)

    def focus(self, game: GameState, duel: DuelRecord, seat: PlayerId, token: str) -> list[Effect]:
        card_id = focus_source(token)
        card = game.table.cards_by_id[card_id]
        ops.move_card(game.table, card, ZoneKey(seat, ZoneRole.FOCUS))
        card.turn_face_down()
        card.clear_peekers()
        card.add_peeker(seat)
        return [
            GrantModifier(
                source_id=card.id,
                target_id=duel.duelist_of(seat),
                stat=Stat.CHI,
                amount=focus_value(card),
                duration=Duration.UNTIL_END_OF_TURN,
            )
        ]

    def focus_total(self, game: GameState, duel: DuelRecord, seat: PlayerId) -> int:
        return 0

    def cleanup(self, game: GameState, duel: DuelRecord) -> list[Effect]:
        outcome = duel.outcome
        if outcome is None:
            return []
        return [
            Destroy(duel.duelist_of(loser), Rulebook.DUEL_RESOLUTION) for loser in outcome.losers
        ]


PRE_GOLD_FOCUSING = PreGoldFocusing()


@contextmanager
def focusing(procedure: FocusProcedure):
    """Play under ``procedure`` for the body of a ``with`` and restore the live ruleset after.

    ``ruleset.ACTIVE`` is a module global, so a procedure left behind would decide every later duel
    in the process.
    """
    live = ruleset.ACTIVE
    ruleset.ACTIVE = replace(live, focus_procedure=procedure)
    try:
        yield
    finally:
        ruleset.ACTIVE = live


def enemy_personalities(game, source):
    """Every Personality another seat controls, which is what a duel-creating probe targets."""
    return [card.id for card in personalities_in_play(game) if card.owner is not source.owner]


CHALLENGE_PROBE = "probe_challenge_to_a_duel_for_the_hooks"

CHALLENGE_ABILITY = Ability(
    timings=(ActionTiming.OPEN,),
    label="Open: challenge a target enemy Personality to a duel",
    cost=no_cost,
    targets=enemy_personalities,
    effects=lambda game, source, target: [StartDuel(source.id, target.id, source.id)],
)


def duel_focusing(card: L5RCard, *, mine_chi: int, theirs_chi: int = 3) -> EngineSession:
    """A duel between P1's challenger and P2's rival with ``card`` the only thing P1 focuses.

    The challenge comes from :data:`CHALLENGE_ABILITY`, so the caller holds the probe registered
    around this. Each seat focuses once and the next ask strikes, which carries the duel to its end.
    """
    state = TableState.empty_two_seat()
    put_in_play(
        state,
        personality("challenger", owner=PlayerId.P1, chi=mine_chi, printed_id=CHALLENGE_PROBE),
    )
    put_in_play(state, personality("rival", owner=PlayerId.P2, chi=theirs_chi))
    for held in (card, focus_card("P2-plain", PlayerId.P2, 1)):
        state.zones[ZoneKey(held.owner, ZoneRole.HAND)].add(register(state, held))
    session = EngineSession.start(state, PlayerId.P1)
    session.act(PlayerId.P1, ActivateAbility("challenger"))
    session.submit(PlayerId.P1, DecisionResponse(("rival",)))
    session.submit(PlayerId.P2, DecisionResponse((focus_token("P2-plain"),)))
    session.submit(PlayerId.P1, DecisionResponse((focus_token(card.id),)))
    return session
