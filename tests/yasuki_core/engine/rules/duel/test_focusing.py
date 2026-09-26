import pytest

from yasuki_core import ruleset
from yasuki_core.engine.players import PlayerId
from yasuki_core.engine.replay.game_log import replay
from yasuki_core.engine.rules.abilities.costs import no_cost
from yasuki_core.engine.rules.abilities.model import Ability
from yasuki_core.engine.rules.board.queries import personalities_in_play
from yasuki_core.engine.rules.duel import focusing as focusing_rules
from yasuki_core.engine.rules.duel import resolution
from yasuki_core.engine.rules.duel.focusing import TWENTY_FESTIVALS_FOCUSING
from yasuki_core.engine.rules.vocabulary.segments import DuelStep
from yasuki_core.engine.rules.effects import StartDuel
from yasuki_core.engine.rules.vocabulary.actions import ActionTiming, ActivateAbility
from yasuki_core.engine.rules.vocabulary.game_events import StrikeDeclared
from yasuki_core.engine.rules.vocabulary.decisions import (
    DECK_TOP,
    STRIKE,
    DecisionResponse,
    FocusOrStrike,
    focus_token,
)
from yasuki_core.engine.session import EngineSession
from yasuki_core.engine.table import DeckKey, TableState, ZoneKey, ZoneRole
from yasuki_core.game_pieces.constants import Side

from tests.yasuki_core.engine.builders import focus_card, personality, put_in_play, register
from tests.yasuki_core.engine.rules.conftest import probe_ability
from tests.yasuki_core.engine.rules.duel.conftest import (
    PRE_GOLD_FOCUSING,
    focusing,
)

P1, P2 = PlayerId.P1, PlayerId.P2

FOCUS_PROBE = "probe_challenge_under_either_procedure"

PROCEDURES = [TWENTY_FESTIVALS_FOCUSING, PRE_GOLD_FOCUSING]
PROCEDURE_IDS = ["twenty_festivals", "pre_gold"]


def _enemy_personalities(game, source):
    return [card.id for card in personalities_in_play(game) if card.owner is not source.owner]


DUEL_ABILITY = Ability(
    timings=(ActionTiming.OPEN,),
    label="Open: challenge a target enemy Personality to a duel",
    cost=no_cost,
    targets=_enemy_personalities,
    effects=lambda game, source, target: [StartDuel(source.id, target.id, source.id)],
)


def _duel_game(
    *,
    held: dict[PlayerId, int] | None = None,
    deck: dict[PlayerId, int] | None = None,
) -> EngineSession:
    """P1's challenger and P2's rival at 3 Chi each, holding ``held`` cards of Focus Value 1 and with
    ``deck`` of them in each Fate deck."""
    held = held or {}
    deck = deck or {}
    state = TableState.empty_two_seat()
    put_in_play(state, personality("challenger", owner=P1, printed_id=FOCUS_PROBE))
    put_in_play(state, personality("rival", owner=P2))
    for seat in PlayerId:
        for i in range(held.get(seat, 0)):
            state.zones[ZoneKey(seat, ZoneRole.HAND)].add(
                register(state, focus_card(f"{seat.name}-h{i}", seat, 1))
            )
        for i in range(deck.get(seat, 0)):
            state.decks[DeckKey(seat, Side.FATE)].cards.append(
                register(state, focus_card(f"{seat.name}-d{i}", seat, 1))
            )
    return EngineSession.start(state, P1)


def _in_play(session: EngineSession) -> set[str]:
    return {card.id for card in session.game.table.battlefield.cards}


def _challenge(session: EngineSession) -> None:
    session.act(P1, ActivateAbility("challenger"))
    session.submit(P1, DecisionResponse(("rival",)))


@pytest.fixture(params=PROCEDURES, ids=PROCEDURE_IDS)
def either_procedure(request):
    """Play the duel under each focus procedure in turn. Every test taking this fixture asserts what
    the two eras agree on, and the ones below it assert where they differ."""
    with focusing(request.param):
        yield request.param


def test_the_challenged_seat_focuses_first_and_the_option_alternates(either_procedure):
    with probe_ability(FOCUS_PROBE, DUEL_ABILITY):
        session = _duel_game(held={P1: 2, P2: 2})
        _challenge(session)

        assert session.game.pending.seat is P2
        session.submit(P2, DecisionResponse((focus_token("P2-h0"),)))
        assert session.game.pending.seat is P1
        session.submit(P1, DecisionResponse((focus_token("P1-h0"),)))

        assert session.game.pending.seat is P2
        assert (session.game.duel.focuses(P1), session.game.duel.focuses(P2)) == (1, 1)


def test_a_focused_card_is_face_down_and_read_by_its_owner_alone(either_procedure):
    with probe_ability(FOCUS_PROBE, DUEL_ABILITY):
        session = _duel_game(held={P1: 1, P2: 1})
        _challenge(session)

        session.submit(P2, DecisionResponse((focus_token("P2-h0"),)))

        focused = session.game.table.cards_by_id["P2-h0"]
        assert [card.id for card in focusing_rules.focused_cards(session.game, P2)] == ["P2-h0"]
        assert not focused.face_up
        assert focused.peekers == frozenset({P2})


def test_a_strike_reveals_both_stacks_and_ends_the_duel(either_procedure):
    # A card each in reserve, so the strike is a choice rather than the loop striking for a seat
    # that has run out of cards to focus.
    with probe_ability(FOCUS_PROBE, DUEL_ABILITY):
        session = _duel_game(held={P1: 2, P2: 2})
        _challenge(session)
        session.submit(P2, DecisionResponse((focus_token("P2-h0"),)))
        session.submit(P1, DecisionResponse((focus_token("P1-h0"),)))
        session.submit(P2, DecisionResponse((STRIKE,)))

        duel = session.game.duel
        assert [
            event.seat for event in session.game.turn_events if isinstance(event, StrikeDeclared)
        ] == [P2]
        assert duel.step is DuelStep.ENDED
        assert duel.outcome.totals
        for card_id in ("P2-h0", "P1-h0"):
            card = session.game.table.cards_by_id[card_id]
            assert card.face_up
            assert card.peekers == frozenset()


def test_the_focused_cards_count_toward_the_totals_either_way(either_procedure):
    with probe_ability(FOCUS_PROBE, DUEL_ABILITY):
        session = _duel_game(held={P1: 2, P2: 2})
        _challenge(session)
        session.submit(P2, DecisionResponse((focus_token("P2-h0"),)))
        session.submit(P1, DecisionResponse((focus_token("P1-h0"),)))
        session.submit(P2, DecisionResponse((focus_token("P2-h1"),)))
        session.submit(P1, DecisionResponse((STRIKE,)))

        # Two Focus Values of 1 against one, on 3 Chi each, whether they were added as each card was
        # focused or totaled at the reveal.
        assert session.game.duel.outcome.totals == {P1: 4, P2: 5}
        assert session.game.duel.outcome.winners == (P2,)


def test_a_duel_replays_from_its_tape_either_way(either_procedure):
    with probe_ability(FOCUS_PROBE, DUEL_ABILITY):
        session = _duel_game(held={P1: 1, P2: 1})
        _challenge(session)
        session.submit(P2, DecisionResponse((focus_token("P2-h0"),)))
        session.submit(P1, DecisionResponse((STRIKE,)))

        assert session.game.duel.step is DuelStep.ENDED
        assert replay(session.log) == session.game


def test_only_the_shipped_procedure_offers_the_top_of_the_deck():
    with probe_ability(FOCUS_PROBE, DUEL_ABILITY):
        with focusing(TWENTY_FESTIVALS_FOCUSING):
            session = _duel_game(held={P2: 1}, deck={P2: 1})
            _challenge(session)
            assert DECK_TOP in session.game.pending.candidates

        with focusing(PRE_GOLD_FOCUSING):
            session = _duel_game(held={P2: 1}, deck={P2: 1})
            _challenge(session)
            assert isinstance(session.game.pending, FocusOrStrike)
            assert DECK_TOP not in session.game.pending.candidates


def test_a_fifth_focus_is_legal_only_where_the_procedure_sets_no_limit():
    with probe_ability(FOCUS_PROBE, DUEL_ABILITY):
        with focusing(TWENTY_FESTIVALS_FOCUSING):
            session = _duel_game(held={P1: 6, P2: 6})
            _challenge(session)
            for index in range(TWENTY_FESTIVALS_FOCUSING.focus_limit):
                session.submit(P2, DecisionResponse((focus_token(f"P2-h{index}"),)))
                session.submit(P1, DecisionResponse((focus_token(f"P1-h{index}"),)))
            assert session.game.duel.step is DuelStep.ENDED

        with focusing(PRE_GOLD_FOCUSING):
            session = _duel_game(held={P1: 6, P2: 6})
            _challenge(session)
            for index in range(5):
                session.submit(P2, DecisionResponse((focus_token(f"P2-h{index}"),)))
                session.submit(P1, DecisionResponse((focus_token(f"P1-h{index}"),)))
            assert session.game.duel.focuses(P2) == 5
            assert session.game.duel.step is DuelStep.FOCUSING


def test_only_the_pre_gold_procedure_destroys_the_loser_by_rulebook():
    with probe_ability(FOCUS_PROBE, DUEL_ABILITY):
        with focusing(TWENTY_FESTIVALS_FOCUSING):
            session = _duel_game(held={P1: 1, P2: 1})
            _challenge(session)
            session.submit(P2, DecisionResponse((focus_token("P2-h0"),)))
            session.submit(P1, DecisionResponse((STRIKE,)))
            assert session.game.duel.outcome.losers == (P1,)
            assert "challenger" in _in_play(session)

        with focusing(PRE_GOLD_FOCUSING):
            session = _duel_game(held={P1: 1, P2: 1})
            _challenge(session)
            session.submit(P2, DecisionResponse((focus_token("P2-h0"),)))
            session.submit(P1, DecisionResponse((STRIKE,)))
            assert session.game.duel.outcome.losers == (P1,)
            assert "challenger" not in _in_play(session)


def test_the_focus_value_lands_on_the_duel_stat_only_where_the_arc_says_so():
    with probe_ability(FOCUS_PROBE, DUEL_ABILITY):
        with focusing(PRE_GOLD_FOCUSING):
            session = _duel_game(held={P1: 1, P2: 1})
            _challenge(session)
            session.submit(P2, DecisionResponse((focus_token("P2-h0"),)))

            # The bonus is on the Personality the moment the card is focused, which a card reading
            # his Chi mid-duel can see, and the reveal adds nothing further.
            duel = session.game.duel
            rival = session.game.table.cards_by_id["rival"]
            assert focusing_rules.focus_value(session.game.table.cards_by_id["P2-h0"]) == 1
            assert resolution.duel_stat(session.game, rival) == 4
            assert ruleset.ACTIVE.focus_procedure.focus_total(session.game, duel, P2) == 0
            assert resolution.duel_total(session.game, duel, P2) == 4
