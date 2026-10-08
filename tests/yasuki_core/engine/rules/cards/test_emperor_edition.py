from yasuki_core.engine import ops
from yasuki_core.engine.players import PlayerId
from yasuki_core.engine.replay.game_log import replay
from yasuki_core.engine.rules.cards.emperor_edition import (
    SANCTIONED_DUEL_ACCEPT,
    SANCTIONED_DUEL_REFUSE,
)
from yasuki_core.engine.rules.battle.records import AttackPhase, BattlefieldInfo
from yasuki_core.engine.rules.rulebook.recruit import RECRUIT
from yasuki_core.engine.rules.stats.card_values import effective_force
from yasuki_core.engine.rules.vocabulary.actions import ActivateAbility, Pass, PlayStrategy
from yasuki_core.engine.rules.vocabulary.game_events import Destroyed
from yasuki_core.engine.rules.vocabulary.decisions import (
    STRIKE,
    ChooseOption,
    DecisionResponse,
    FocusOrStrike,
    focus_token,
)
from yasuki_core.engine.session import EngineSession
from yasuki_core.engine.table import DeckKey, Location, TableState, ZoneKey, ZoneRole
from yasuki_core.engine.zones import ProvinceZone
from yasuki_core.game_pieces.cards import L5RCard
from yasuki_core.game_pieces.constants import Side
from yasuki_core.game_pieces.prints import FatePrint

from yasuki_core.engine.rules.duel.procedure import declare_duel
from yasuki_core.engine.rules.effects import DiscardFromHand
from yasuki_core.engine.rules.turn.sequence import run_stack

from tests.yasuki_core.engine.rules.conftest import (
    probe_challenge_cost,
    probe_challenge_restriction,
)
from tests.yasuki_core.engine.builders import (
    end_phase,
    fate_card,
    focus_card,
    pay,
    personality,
    put_in_play,
    register,
    stronghold,
    two_seat_game,
)

P1, P2 = PlayerId.P1, PlayerId.P2


# --- Sanctioned Duel ---


def _sanctioned_duel_game(*, chi: dict[PlayerId, int] | None = None) -> EngineSession:
    """Sanctioned Duel in P1's hand, P1's unbowed Personality and P2's rival in play with ``chi``
    each, and one card of Focus Value 1 in each hand to focus with."""
    chi = {P1: 3, P2: 3} if chi is None else chi
    state = TableState.empty_two_seat()
    put_in_play(state, register(state, stronghold(P1)))
    put_in_play(state, register(state, personality("mine", owner=P1, chi=chi[P1])))
    put_in_play(state, register(state, personality("theirs", owner=P2, chi=chi[P2])))
    strategy = register(
        state,
        L5RCard.of(
            FatePrint,
            id="duel",
            printed_id="sanctioned_duel",
            name="Sanctioned Duel",
            side=Side.FATE,
            owner=P1,
            gold_cost=0,
        ),
    )
    state.zones[ZoneKey(P1, ZoneRole.HAND)].add(strategy)
    for seat in PlayerId:
        card = register(state, focus_card(f"{seat.name}-fv", seat, 1))
        state.zones[ZoneKey(seat, ZoneRole.HAND)].add(card)
    return EngineSession.start(state, P1)


def _in_play(session: EngineSession) -> set[str]:
    """The ids on the battlefield. ``cards_by_id`` indexes the discard piles too, so it never
    reports a destruction."""
    return {card.id for card in session.game.table.battlefield.cards}


def _challenge(session: EngineSession) -> None:
    """Play the Strategy, target the challenger, and pick whom it challenges."""
    session.act(P1, PlayStrategy("duel"))
    session.submit(P1, DecisionResponse(("mine",)))
    session.submit(P1, DecisionResponse(("theirs",)))


def test_sanctioned_duel_offers_the_challenged_seat_the_choice_to_refuse():
    session = _sanctioned_duel_game()

    _challenge(session)

    pending = session.game.pending
    assert isinstance(pending, ChooseOption)
    assert pending.seat is P2
    assert pending.candidates == (SANCTIONED_DUEL_REFUSE, SANCTIONED_DUEL_ACCEPT)
    # A refused challenge creates no duel, so nothing is on the game until the answer comes back.
    assert session.game.duel is None


def test_refusing_sanctioned_duel_dishonors_him_and_creates_no_duel():
    session = _sanctioned_duel_game()
    _challenge(session)

    session.submit(P2, DecisionResponse((SANCTIONED_DUEL_REFUSE,)))

    assert session.game.table.cards_by_id["theirs"].dishonorable is True
    assert session.game.table.seats[P1].honor == 2
    # "The duel doesn't happen" (CR, Challenge): no record, and both Personalities stay.
    assert session.game.duel is None
    assert {"mine", "theirs"} <= _in_play(session)


def test_accepting_sanctioned_duel_fights_it_and_destroys_the_loser():
    session = _sanctioned_duel_game(chi={P1: 5, P2: 2})
    _challenge(session)

    session.submit(P2, DecisionResponse((SANCTIONED_DUEL_ACCEPT,)))

    assert isinstance(session.game.pending, FocusOrStrike)
    session.submit(P2, DecisionResponse((STRIKE,)))

    assert session.game.duel.outcome.winners == (P1,)
    assert "theirs" not in _in_play(session)
    # Nothing happens to the winner, and the refusal branch did not run.
    assert "mine" in _in_play(session)
    assert session.game.table.cards_by_id["mine"].dishonorable is False
    assert session.game.table.seats[P1].honor == 0


def test_sanctioned_duels_loser_is_read_when_the_duel_ends_not_when_it_is_declared():
    # The Chi the duelists enter on is reversed by what each focuses, so a destruction decided at
    # declaration would kill the wrong Personality.
    session = _sanctioned_duel_game(chi={P1: 2, P2: 3})
    _challenge(session)
    session.submit(P2, DecisionResponse((SANCTIONED_DUEL_ACCEPT,)))
    session.submit(P2, DecisionResponse((focus_token("P2-fv"),)))

    session.submit(P1, DecisionResponse((focus_token("P1-fv"),)))

    # Neither seat has a second card to focus, so the duel strikes without being asked again.
    assert session.game.duel.outcome.totals == {P1: 3, P2: 4}
    assert "mine" not in _in_play(session)
    assert "theirs" in _in_play(session)


def test_sanctioned_duel_replays_after_refusing():
    session = _sanctioned_duel_game()
    _challenge(session)

    session.submit(P2, DecisionResponse((SANCTIONED_DUEL_REFUSE,)))

    assert replay(session.log).table == session.game.table


def test_sanctioned_duel_replays_after_accepting():
    session = _sanctioned_duel_game()
    _challenge(session)
    session.submit(P2, DecisionResponse((SANCTIONED_DUEL_ACCEPT,)))

    session.submit(P2, DecisionResponse((STRIKE,)))

    assert replay(session.log).table == session.game.table


def test_sanctioned_duel_records_the_challengers_controller_as_destroying_the_loser():
    # The seat answering the refuse-or-accept question is the challenged one, so a destruction
    # attributed to the answerer would read as the loser destroying its own Personality.
    session = _sanctioned_duel_game(chi={P1: 5, P2: 2})
    _challenge(session)
    session.submit(P2, DecisionResponse((SANCTIONED_DUEL_ACCEPT,)))

    session.submit(P2, DecisionResponse((STRIKE,)))

    destroyed = [event for event in session.game.turn_events if isinstance(event, Destroyed)]
    assert [(event.card_id, event.cause) for event in destroyed] == [("theirs", P1)]


def test_sanctioned_duel_is_not_offered_with_no_personality_to_challenge():
    # Both targets have to exist, and the challenged one is picked after the card is played, so an
    # ability offered on the challenger alone strands the seat on a choice with no candidates.
    session = _sanctioned_duel_game()
    ops.remove_card(session.game.table, session.game.table.cards_by_id["theirs"])

    assert PlayStrategy("duel") not in session.legal_actions(P1)


def test_sanctioned_duel_is_not_offered_when_the_rival_may_not_be_challenged():
    def _theirs_may_not_be_challenged(game, holder, challenger, challenged):
        return challenged.id != "theirs"

    with probe_challenge_restriction("theirs", _theirs_may_not_be_challenged):
        session = _sanctioned_duel_game()

        assert PlayStrategy("duel") not in session.legal_actions(P1)


def test_sanctioned_duel_pays_the_rivals_challenge_cost_when_it_picks_him():
    def _discard_to_challenge(game, holder, challenger, challenged):
        seat = challenger.owner
        return [DiscardFromHand(seat, 1, seat, seat)] if challenged is holder else []

    with probe_challenge_cost("theirs", _discard_to_challenge):
        session = _sanctioned_duel_game()

        _challenge(session)

        discard = session.game.table.zones[ZoneKey(P1, ZoneRole.FATE_DISCARD)].cards
        assert "P1-fv" in {card.id for card in discard}
        assert isinstance(session.game.pending, ChooseOption)


def test_sanctioned_duel_does_not_target_a_bowed_challenger():
    session = _sanctioned_duel_game()
    session.game.table.cards_by_id["mine"].bow()

    assert PlayStrategy("duel") not in session.legal_actions(P1)


def test_sanctioned_duel_challenges_only_another_players_personality():
    session = _sanctioned_duel_game()
    put_in_play(session.game, register(session.game.table, personality("second", owner=P1)))

    session.act(P1, PlayStrategy("duel"))
    session.submit(P1, DecisionResponse(("mine",)))

    # "another player's target Personality": your own second Personality is not a candidate, and a
    # challenge between two of your own would not happen at all (CR, Challenge).
    assert session.game.pending.candidates == ("theirs",)


def test_sanctioned_duel_asks_nothing_when_the_last_rival_leaves_after_it_is_announced():
    # The candidates are recomputed when the target is answered, which is after the board could
    # have changed. A `Choose` of one from none would pend with no answer that satisfies it.
    session = _sanctioned_duel_game()

    session.act(P1, PlayStrategy("duel"))
    ops.remove_card(session.game.table, session.game.table.cards_by_id["theirs"])
    session.submit(P1, DecisionResponse(("mine",)))

    # "A challenge does not happen" (CR, Challenge), so the Strategy resolves having done nothing.
    assert session.game.pending is None
    assert session.game.duel is None


def test_a_challenge_that_did_not_happen_destroys_nobody_in_the_next_duel():
    """The destruction is delayed to a duel's end, and nothing discards it when the challenge turns
    out not to happen. Read off ``game.duel`` alone it would fire on whatever duel ended next."""
    session = _sanctioned_duel_game()
    put_in_play(session.game, register(session.game.table, personality("second", owner=P1, chi=1)))
    put_in_play(session.game, register(session.game.table, personality("other", owner=P2, chi=9)))
    _challenge(session)
    # The challenged Personality leaves between the challenge and the answer, so the challenge does
    # not happen (CR, Challenge) and no duel is created for the destruction to read.
    ops.remove_card(session.game.table, session.game.table.cards_by_id["theirs"])

    session.submit(P2, DecisionResponse((SANCTIONED_DUEL_ACCEPT,)))
    assert session.game.duel is None

    declare_duel(
        session.game, challenger_duelist="second", challenged_duelist="other", source="second"
    )
    run_stack(session.game)
    # Both seats hold a card to focus, so the second duel pauses until one of them strikes.
    session.submit(session.game.pending.seat, DecisionResponse((STRIKE,)))

    assert session.game.duel.outcome.losers == (P1,)
    assert "second" in _in_play(session)


def test_sanctioned_duel_destroys_both_personalities_when_neither_wins():
    # Equal totals that the Duelist tiebreak cannot separate are lost by both (CR, Duel), and the
    # card destroys the loser rather than a single loser.
    session = _sanctioned_duel_game(chi={P1: 3, P2: 3})
    _challenge(session)
    session.submit(P2, DecisionResponse((SANCTIONED_DUEL_ACCEPT,)))

    session.submit(P2, DecisionResponse((STRIKE,)))

    assert session.game.duel.outcome.winners == ()
    assert set(session.game.duel.outcome.losers) == {P1, P2}
    assert {"mine", "theirs"} & _in_play(session) == set()


# --- Togashi Korimi ---


def _korimi_game(*, also_in_province: tuple[L5RCard, ...] = ()) -> EngineSession:
    """P1's Dynasty phase, with Korimi face-up in P1's first Province, gold to Recruit her, and one
    card in P1's Fate deck to draw. ``also_in_province`` fill further Provinces face-up."""
    state = TableState.empty_two_seat()
    put_in_play(state, register(state, stronghold(P1, gold_production=8)))
    state.decks[DeckKey(P1, Side.FATE)].cards = [register(state, fate_card("drawn", P1))]
    state.decks[DeckKey(P1, Side.DYNASTY)].cards = [
        register(state, personality(f"refill{index}", owner=P1)) for index in range(3)
    ]
    for index, card in enumerate(
        (personality("korimi", owner=P1, printed_id=KORIMI, gold_cost=5), *also_in_province)
    ):
        register(state, card).turn_face_up()
        province = ProvinceZone(owner=P1)
        province.add(card)
        state.zones[ZoneKey(P1, ZoneRole.PROVINCE, index)] = province
    session = EngineSession.start(state, P1)
    end_phase(session)
    end_phase(session)
    return session


KORIMI = "togashi_korimi"


def _hand(session: EngineSession) -> list[str]:
    return [card.id for card in session.game.table.zones[ZoneKey(P1, ZoneRole.HAND)].cards]


def test_recruiting_korimi_offers_her_response_to_bow_and_draw():
    session = _korimi_game()
    session.act(P1, ActivateAbility("korimi", RECRUIT))
    pay(session, P1)

    session.act(P1, ActivateAbility("korimi"))

    assert session.game.table.cards_by_id["korimi"].bowed
    assert "drawn" in _hand(session)


def test_korimi_draws_nothing_when_her_response_is_passed():
    session = _korimi_game()
    session.act(P1, ActivateAbility("korimi", RECRUIT))
    pay(session, P1)

    session.act(P1, Pass())

    assert not session.game.table.cards_by_id["korimi"].bowed
    assert "drawn" not in _hand(session)


def test_korimi_answers_no_recruit_but_her_own():
    session = _korimi_game(also_in_province=(personality("other", owner=P1, gold_cost=1),))
    session.act(P1, ActivateAbility("korimi", RECRUIT))
    pay(session, P1)
    session.act(P1, Pass())

    session.act(P1, ActivateAbility("other", RECRUIT))
    pay(session, P1)

    assert ActivateAbility("korimi") not in session.legal_actions(P1)


def test_korimi_has_two_more_force_while_defending():
    game = two_seat_game()
    game.attack = AttackPhase(
        attacker=P2,
        defender=P1,
        battlefields=(BattlefieldInfo(province=ZoneKey(P1, ZoneRole.PROVINCE, 0)),),
        current=0,
    )
    korimi = put_in_play(game, personality("korimi", owner=P1, printed_id=KORIMI, force=3))
    assert effective_force(game, korimi) == 3  # at home, not defending

    ops.set_location(game.table, korimi, Location.at_battlefield(0))

    assert effective_force(game, korimi) == 5
