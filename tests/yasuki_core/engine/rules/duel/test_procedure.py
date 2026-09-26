from dataclasses import replace

import pytest

from yasuki_core import ruleset
from yasuki_core.engine.players import PlayerId
from yasuki_core.engine.replay.game_log import replay
from yasuki_core.engine.rules.abilities.costs import no_cost
from yasuki_core.engine.rules.abilities.model import Ability
from yasuki_core.engine.rules.board.queries import personalities_in_play
from yasuki_core.engine.rules.duel import procedure
from yasuki_core.engine.rules.duel.records import DuelStep
from yasuki_core.engine.rules.effects import StartDuel
from yasuki_core.engine.rules.triggers import apply_effect
from yasuki_core.engine.rules.vocabulary.actions import ActionTiming, ActivateAbility
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

from tests.yasuki_core.engine.builders import (
    fate_card,
    holding,
    personality,
    put_in_play,
    register,
)
from tests.yasuki_core.engine.rules.conftest import probe_ability

P1, P2 = PlayerId.P1, PlayerId.P2

DUEL_PROBE = "probe_challenge_to_a_duel"


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
    hand: dict[PlayerId, int] | None = None,
    deck: dict[PlayerId, int] | None = None,
    probe: str = DUEL_PROBE,
):
    """P1's challenger and P2's rival in play, each seat holding ``hand`` Fate cards and with
    ``deck`` in its Fate deck. Both default to one each, so either source is available."""
    hand = {P1: 1, P2: 1} if hand is None else hand
    deck = {P1: 1, P2: 1} if deck is None else deck
    state = TableState.empty_two_seat()
    put_in_play(state, personality("challenger", owner=P1, printed_id=probe))
    put_in_play(state, personality("rival", owner=P2))
    for seat in PlayerId:
        for i in range(hand.get(seat, 0)):
            state.zones[ZoneKey(seat, ZoneRole.HAND)].add(
                register(state, fate_card(f"{seat.name}-h{i}", seat))
            )
        state.decks[DeckKey(seat, Side.FATE)].cards = [
            register(state, fate_card(f"{seat.name}-d{i}", seat)) for i in range(deck.get(seat, 0))
        ]
    return EngineSession.start(state, P1)


def _challenge(session: EngineSession) -> None:
    """Take the probe action that puts challenger and rival in a duel."""
    session.act(P1, ActivateAbility("challenger"))
    session.submit(P1, DecisionResponse(("rival",)))


def _focused_ids(session: EngineSession, seat: PlayerId) -> list[str]:
    return [card.id for card in procedure.focused_cards(session.game, seat)]


def test_a_declared_duel_records_both_duelists_and_opens_the_focusing():
    with probe_ability(DUEL_PROBE, DUEL_ABILITY):
        session = _duel_game()
        _challenge(session)

        duel = session.game.duel
        assert duel is not None
        assert (duel.challenger, duel.challenged) == (P1, P2)
        assert (duel.challenger_duelist, duel.challenged_duelist) == ("challenger", "rival")
        assert duel.source == "challenger"
        assert duel.step is DuelStep.FOCUSING


def test_the_challenged_seat_has_the_first_option():
    with probe_ability(DUEL_PROBE, DUEL_ABILITY):
        session = _duel_game()
        _challenge(session)

        pending = session.game.pending
        assert isinstance(pending, FocusOrStrike)
        assert pending.seat is P2
        assert set(pending.candidates) == {focus_token("P2-h0"), DECK_TOP, STRIKE}


def test_a_card_focused_from_hand_is_face_down_and_read_by_its_owner_alone():
    with probe_ability(DUEL_PROBE, DUEL_ABILITY):
        session = _duel_game()
        _challenge(session)

        session.submit(P2, DecisionResponse((focus_token("P2-h0"),)))

        focused = session.game.table.cards_by_id["P2-h0"]
        assert _focused_ids(session, P2) == ["P2-h0"]
        assert not focused.face_up
        assert focused.peekers == frozenset({P2})
        assert session.game.table.zones[ZoneKey(P2, ZoneRole.HAND)].cards == []


def test_a_card_focused_off_the_deck_is_read_by_its_owner_once_it_has_landed():
    with probe_ability(DUEL_PROBE, DUEL_ABILITY):
        session = _duel_game()
        _challenge(session)

        session.submit(P2, DecisionResponse((DECK_TOP,)))

        focused = session.game.table.cards_by_id["P2-d0"]
        assert _focused_ids(session, P2) == ["P2-d0"]
        assert not focused.face_up
        # Chosen unseen and read afterwards: the seat commits to the card before learning what it is.
        assert focused.peekers == frozenset({P2})
        assert session.game.table.decks[DeckKey(P2, Side.FATE)].cards == []


def test_the_option_alternates_after_each_focus():
    with probe_ability(DUEL_PROBE, DUEL_ABILITY):
        session = _duel_game(hand={P1: 2, P2: 2})
        _challenge(session)

        session.submit(P2, DecisionResponse((focus_token("P2-h0"),)))
        assert session.game.pending.seat is P1
        assert session.game.duel.option is P1

        session.submit(P1, DecisionResponse((focus_token("P1-h0"),)))
        assert session.game.pending.seat is P2

        assert (session.game.duel.focuses(P1), session.game.duel.focuses(P2)) == (1, 1)


def test_a_seat_with_nothing_to_focus_strikes_without_being_asked():
    with probe_ability(DUEL_PROBE, DUEL_ABILITY):
        session = _duel_game(hand={P1: 1}, deck={P1: 1})
        _challenge(session)

        duel = session.game.duel
        assert duel.struck is P2
        assert duel.step is DuelStep.ENDED
        assert session.game.pending is None


def test_striking_ends_the_focusing_where_the_seat_chooses_to():
    with probe_ability(DUEL_PROBE, DUEL_ABILITY):
        session = _duel_game()
        _challenge(session)

        session.submit(P2, DecisionResponse((STRIKE,)))

        duel = session.game.duel
        assert duel.struck is P2
        assert duel.option is None
        # The strike carries the duel through the reveal to its outcome without another answer.
        assert duel.step is DuelStep.ENDED
        assert _focused_ids(session, P2) == []


def test_a_seat_may_focus_four_times_and_then_only_strike():
    with probe_ability(DUEL_PROBE, DUEL_ABILITY):
        # Deep enough decks that neither seat runs out before the limit bites.
        session = _duel_game(hand={}, deck={P1: 6, P2: 6})
        _challenge(session)

        for _ in range(ruleset.ACTIVE.focus_limit):
            for seat in (P2, P1):
                assert session.game.pending.seat is seat
                session.submit(seat, DecisionResponse((DECK_TOP,)))

        duel = session.game.duel
        assert (duel.focuses(P1), duel.focuses(P2)) == (4, 4)
        # Neither seat may focus a fifth time, so the loop strikes for whoever's option it was.
        assert duel.struck is P2
        assert session.game.pending is None


def test_the_focus_limit_is_counted_per_seat():
    # The alternating loop can only drive both seats to the cap together, so what the cap is counted
    # against is read off the sources each seat is offered at the same moment.
    with probe_ability(DUEL_PROBE, DUEL_ABILITY):
        limit = ruleset.ACTIVE.focus_limit
        session = _duel_game(hand={}, deck={P1: 6, P2: 6})
        _challenge(session)

        for _ in range(limit - 1):
            session.submit(P2, DecisionResponse((DECK_TOP,)))
            session.submit(P1, DecisionResponse((DECK_TOP,)))
        session.submit(P2, DecisionResponse((DECK_TOP,)))
        duel = session.game.duel

        assert (duel.focuses(P2), duel.focuses(P1)) == (limit, limit - 1)
        assert procedure.focus_sources(session.game, duel, P2) == ()
        assert DECK_TOP in procedure.focus_sources(session.game, duel, P1)


def test_the_focus_limit_comes_from_the_ruleset(monkeypatch):
    monkeypatch.setattr(ruleset, "ACTIVE", replace(ruleset.ACTIVE, focus_limit=1))
    with probe_ability(DUEL_PROBE, DUEL_ABILITY):
        session = _duel_game(hand={}, deck={P1: 6, P2: 6})
        _challenge(session)

        session.submit(P2, DecisionResponse((DECK_TOP,)))
        session.submit(P1, DecisionResponse((DECK_TOP,)))

        # One focus each is the whole allowance, so the second offer strikes for the seat instead.
        assert (session.game.duel.focuses(P1), session.game.duel.focuses(P2)) == (1, 1)
        assert session.game.pending is None
        assert session.game.duel.step is DuelStep.ENDED


def test_an_arc_with_no_focus_limit_is_capped_only_by_what_a_seat_holds(monkeypatch):
    monkeypatch.setattr(ruleset, "ACTIVE", replace(ruleset.ACTIVE, focus_limit=None))
    with probe_ability(DUEL_PROBE, DUEL_ABILITY):
        session = _duel_game(hand={}, deck={P1: 6, P2: 6})
        _challenge(session)

        for _ in range(5):
            session.submit(P2, DecisionResponse((DECK_TOP,)))
            session.submit(P1, DecisionResponse((DECK_TOP,)))

        assert session.game.duel.focuses(P2) == 5
        pending = session.game.pending
        assert isinstance(pending, FocusOrStrike)
        assert pending.seat is P2
        assert DECK_TOP in pending.candidates


def test_a_challenge_between_one_players_own_personalities_never_happens():
    with probe_ability(DUEL_PROBE, DUEL_ABILITY):
        session = _duel_game()
        put_in_play(session.game, personality("ally", owner=P1))

        procedure.declare_duel(
            session.game,
            challenger_duelist="challenger",
            challenged_duelist="ally",
            source="challenger",
        )

        assert session.game.duel is None
        assert not [key for key in session.game.table.zones if key.role is ZoneRole.FOCUS]


def test_a_challenge_to_a_card_that_is_not_a_personality_never_happens():
    with probe_ability(DUEL_PROBE, DUEL_ABILITY):
        session = _duel_game()
        put_in_play(session.game, holding("market", owner=P2))

        procedure.declare_duel(
            session.game,
            challenger_duelist="challenger",
            challenged_duelist="market",
            source="challenger",
        )

        assert session.game.duel is None


def test_a_duel_whose_target_left_play_starts_no_duel_from_the_effect():
    # The route a card takes. The effect reads no card off the table itself, so a Personality
    # destroyed between being targeted and the duel resolving refuses the challenge rather than
    # raising out of the engine.
    with probe_ability(DUEL_PROBE, DUEL_ABILITY):
        session = _duel_game()

        apply_effect(session.game, StartDuel("challenger", "gone", "challenger"))

        assert session.game.duel is None
        assert not [key for key in session.game.table.zones if key.role is ZoneRole.FOCUS]


def test_a_duel_paused_mid_focusing_replays_from_its_tape():
    with probe_ability(DUEL_PROBE, DUEL_ABILITY):
        session = _duel_game(hand={P1: 2, P2: 2})
        _challenge(session)
        session.submit(P2, DecisionResponse((focus_token("P2-h0"),)))
        session.submit(P1, DecisionResponse((DECK_TOP,)))

        assert replay(session.log) == session.game


def test_a_resolved_duel_replays_from_its_tape():
    # The reveal, the outcome, the discards and the focusing areas going away all have to come back
    # the same, and none of the duel is serialized: the tape rebuilds it by re-running the engine.
    with probe_ability(DUEL_PROBE, DUEL_ABILITY):
        session = _duel_game(hand={P1: 2, P2: 2})
        _challenge(session)
        session.submit(P2, DecisionResponse((focus_token("P2-h0"),)))
        session.submit(P1, DecisionResponse((DECK_TOP,)))
        session.submit(P2, DecisionResponse((STRIKE,)))

        assert session.game.duel.step is DuelStep.ENDED
        assert replay(session.log) == session.game


TWO_DUEL_PROBE = "probe_challenge_twice"

TWO_DUEL_ABILITY = Ability(
    timings=(ActionTiming.OPEN,),
    label="Open: challenge two enemy Personalities to duels",
    cost=no_cost,
    targets=lambda game, source: ["rival"],
    effects=lambda game, source, target: [
        StartDuel("challenger", "rival", "challenger"),
        StartDuel("ally", "rival2", "ally"),
    ],
)


def test_a_second_duel_from_one_effect_is_refused_rather_than_run_out_of_order():
    # An effect that creates several duels fights them in sequence (CR, Duration). Running several
    # sub-procedures from one effect is not the duel's own problem to solve, so the duel refuses it
    # loudly instead. No Shattered Empire-legal card duels twice.
    with probe_ability(TWO_DUEL_PROBE, TWO_DUEL_ABILITY):
        session = _duel_game(hand={P1: 2, P2: 2}, probe=TWO_DUEL_PROBE)
        put_in_play(session.game, personality("ally", owner=P1))
        put_in_play(session.game, personality("rival2", owner=P2))
        session.act(P1, ActivateAbility("challenger"))

        with pytest.raises(RuntimeError, match="already being fought"):
            session.submit(P1, DecisionResponse(("rival",)))


def test_declaring_over_a_duel_still_being_fought_is_refused():
    # The queue above is what keeps this unreachable. The guard stays because a duel declared on top
    # of a live one would lose the record of the one it replaced.
    with probe_ability(DUEL_PROBE, DUEL_ABILITY):
        session = _duel_game()
        _challenge(session)
        session.game.duel.step = DuelStep.FOCUSING

        with pytest.raises(RuntimeError, match="already being fought"):
            session.game.begin_duel(session.game.duel)


def test_focusing_a_card_the_seat_does_not_hold_is_refused():
    with probe_ability(DUEL_PROBE, DUEL_ABILITY):
        session = _duel_game()
        _challenge(session)

        with pytest.raises(ValueError):
            procedure.focus(session.game, P2, focus_token("P1-h0"))
