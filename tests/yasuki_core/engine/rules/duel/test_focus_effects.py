from contextlib import contextmanager

from yasuki_core.engine.players import PlayerId
from yasuki_core.engine.rules.duel.focus_effects import FOCUS_EFFECTS, focus_effect
from yasuki_core.engine.rules.duel.records import DuelStep
from yasuki_core.engine.rules.effects import Ask, GainHonor
from yasuki_core.engine.rules.vocabulary.actions import ActivateAbility
from yasuki_core.engine.rules.vocabulary.decisions import (
    STRIKE,
    ChooseFocusEffect,
    DecisionResponse,
    focus_token,
)
from yasuki_core.engine.session import EngineSession
from yasuki_core.engine.table import TableState, ZoneKey, ZoneRole
from yasuki_core.game_pieces.cards import L5RCard

from tests.yasuki_core.engine.builders import focus_card, personality, put_in_play, register
from tests.yasuki_core.engine.rules.conftest import probe_ability, probe_resolver
from tests.yasuki_core.engine.rules.duel.conftest import CHALLENGE_ABILITY, CHALLENGE_PROBE

P1, P2 = PlayerId.P1, PlayerId.P2

HONOR_FOCUS = "probe_focus_effect_gains_honor"
ASKING_FOCUS = "probe_focus_effect_that_asks"


@contextmanager
def probe_focus_effect(printed_id: str, handler):
    """Register ``handler`` as ``printed_id``'s Focus Effect for the body of a ``with``.

    The registry is module-global and refuses a second handler for one id, so one left behind fails
    every later test that registers the same probe.
    """
    focus_effect(printed_id)(handler)
    try:
        yield
    finally:
        FOCUS_EFFECTS.pop(printed_id)


def _duel_game(*, held: tuple[L5RCard, ...]) -> EngineSession:
    """P1's challenger and P2's rival in play, with ``held`` in their owners' hands."""
    state = TableState.empty_two_seat()
    put_in_play(state, personality("challenger", owner=P1, printed_id=CHALLENGE_PROBE))
    put_in_play(state, personality("rival", owner=P2))
    for card in held:
        state.zones[ZoneKey(card.owner, ZoneRole.HAND)].add(register(state, card))
    return EngineSession.start(state, P1)


def _challenge(session: EngineSession) -> None:
    session.act(P1, ActivateAbility("challenger"))
    session.submit(P1, DecisionResponse(("rival",)))


def _focus_and_strike(session: EngineSession, focused: tuple[tuple[PlayerId, str], ...]) -> None:
    for seat, card_id in focused:
        session.submit(seat, DecisionResponse((focus_token(card_id),)))
    session.submit(session.game.pending.seat, DecisionResponse((STRIKE,)))


def test_a_revealed_cards_focus_effect_resolves():
    with probe_ability(CHALLENGE_PROBE, CHALLENGE_ABILITY):
        with probe_focus_effect(HONOR_FOCUS, lambda game, card: [GainHonor(card.owner, 3)]):
            session = _duel_game(
                held=(
                    focus_card("P2-honor", P2, 1, printed_id=HONOR_FOCUS),
                    focus_card("P2-plain", P2, 1),
                    focus_card("P1-plain", P1, 1),
                )
            )
            _challenge(session)
            _focus_and_strike(session, ((P2, "P2-honor"), (P1, "P1-plain")))

            assert session.game.table.seats[P2].honor == 3
            assert session.game.duel.step is DuelStep.ENDED


def test_the_active_player_names_the_order_when_two_cards_carry_one():
    with probe_ability(CHALLENGE_PROBE, CHALLENGE_ABILITY):
        with probe_focus_effect(HONOR_FOCUS, lambda game, card: [GainHonor(card.owner, 3)]):
            session = _duel_game(
                held=(
                    focus_card("P2-honor", P2, 1, printed_id=HONOR_FOCUS),
                    focus_card("P2-spare", P2, 1),
                    focus_card("P1-honor", P1, 1, printed_id=HONOR_FOCUS),
                    focus_card("P1-spare", P1, 1),
                )
            )
            _challenge(session)
            _focus_and_strike(session, ((P2, "P2-honor"), (P1, "P1-honor")))

            pending = session.game.pending
            assert isinstance(pending, ChooseFocusEffect)
            assert pending.seat is P1
            assert set(pending.candidates) == {"P1-honor", "P2-honor"}

            session.submit(P1, DecisionResponse(("P1-honor",)))

            # The second resolves without another question, since one card has no order to choose.
            assert session.game.table.seats[P1].honor == 3
            assert session.game.table.seats[P2].honor == 3
            assert session.game.pending is None


def test_a_focus_effect_that_asks_a_question_resumes_into_the_next_card():
    def _asking(game, card) -> list:
        return [Ask(card.owner, "Gain 3 Honor?", "probe_focus_gain", (card.id,), card.id)]

    with probe_ability(CHALLENGE_PROBE, CHALLENGE_ABILITY):
        with probe_resolver(
            "probe_focus_gain",
            lambda game, source_id, chosen, seat: [GainHonor(seat, 3)] if chosen else [],
        ):
            with (
                probe_focus_effect(ASKING_FOCUS, _asking),
                probe_focus_effect(HONOR_FOCUS, lambda game, card: [GainHonor(card.owner, 1)]),
            ):
                session = _duel_game(
                    held=(
                        focus_card("P2-asks", P2, 1, printed_id=ASKING_FOCUS),
                        focus_card("P2-spare", P2, 1),
                        focus_card("P1-honor", P1, 1, printed_id=HONOR_FOCUS),
                        focus_card("P1-spare", P1, 1),
                    )
                )
                _challenge(session)
                _focus_and_strike(session, ((P2, "P2-asks"), (P1, "P1-honor")))

                session.submit(P1, DecisionResponse(("P2-asks",)))
                # The asking Focus Effect paused for its own question, which the duel waits on.
                assert session.game.pending.seat is P2
                session.submit(P2, DecisionResponse(("P2-asks",)))

                assert session.game.table.seats[P2].honor == 3
                assert session.game.table.seats[P1].honor == 1
                assert session.game.duel.step is DuelStep.ENDED
