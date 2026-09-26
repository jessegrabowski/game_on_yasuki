import inspect
import re

import pytest

from yasuki_core.engine import ops
from yasuki_core.engine.players import PlayerId
from yasuki_core.engine.table import TableState, ZoneKey, ZoneRole, DeckKey
from yasuki_core.game_pieces.constants import Side
from yasuki_core.game_pieces.cards import L5RCard
from yasuki_core.game_pieces.prints import (
    DynastyPrint,
    FatePrint,
    RulebookPrint,
)
from yasuki_core.engine.rules.vocabulary.actions import (
    Lobby,
    ActionTiming,
    ActivateAbility,
    Pass,
    Recruit,
)
from yasuki_core.engine.rules.state import GameState
from yasuki_core.engine.rules.vocabulary.modifiers import (
    Condition,
    ConditionalModifier,
    Duration,
    Stat,
)
from yasuki_core.engine.rules.triggers import choice_resolver
from yasuki_core.engine.rules.turn.structure import (
    ActionRound,
    BATTLE_SEGMENT_TIMINGS,
    Boundary,
    END_OF_TURN,
    FIRED_MOMENTS,
    Moment,
    PHASE_TIMINGS,
    Phase,
    RESPONSE_TIMINGS,
    RoundKind,
    Turn,
)
from yasuki_core.engine.rules.battle import resolution
from yasuki_core.engine.rules.vocabulary.decisions import (
    ChooseDiscard,
    Confirm,
    DecisionResponse,
    LeaveBowed,
)
from yasuki_core.engine.rules.effects import (
    Ask,
    Choose,
    Banish,
    DelayStraighten,
    DelayedEffect,
    Straighten,
)
from yasuki_core.engine.rules import legality
from yasuki_core.engine.rules.turn import action_sequence, sequence
from yasuki_core.engine.rules.turn import structure
from yasuki_core.engine.rules.projection import project
from yasuki_core.engine.rules.vocabulary.game_events import (
    CardDiscarded,
    EnteredPlay,
    PhaseStarted,
    Revealed,
    Straightened,
    TurnStarted,
)
from yasuki_core.engine.rules import triggers
from yasuki_core.engine.rules.abilities.idioms import TRAIT_ENTRY
from yasuki_core.engine.session import EngineSession
from yasuki_core.engine.rules.abilities.costs import no_cost
from yasuki_core.engine.rules.abilities.model import Ability, itself
from yasuki_core.engine.rules.abilities.registry import register_ability
from yasuki_core.engine.rules.board.queries import favor_actions_this_turn
from yasuki_core.engine.rules.rulebook import proxies
from yasuki_core.engine.rules.effects import TakeFavor
from yasuki_core.engine.rules.turn.action_sequence import submit
from yasuki_core.engine.rules.vocabulary.game_events import ActionResolved
from yasuki_core.game_pieces.constants import IMPERIAL_FAVOR_ID

from tests.yasuki_core.engine.builders import (
    datasheet_favor_ability,
    dealt_table,
    end_phase,
    end_turn,
    fate_card,
    holding,
    put_in_play,
    register,
)
from yasuki_core.game_pieces.prints import SenseiPrint, StrongholdPrint


def _game(hand: int = 0, fate_deck: int = 1) -> GameState:
    """A two-seat game where P1 holds ``hand`` fate cards and each seat's fate deck holds
    ``fate_deck`` cards."""
    state = TableState.empty_two_seat()
    for seat in PlayerId:
        state.decks[DeckKey(seat, Side.FATE)].cards = [
            register(
                state,
                L5RCard.of(
                    FatePrint, id=f"{seat.name}-fd{i}", name="F", side=Side.FATE, owner=seat
                ),
            )
            for i in range(fate_deck)
        ]
    hand_zone = state.zones[ZoneKey(PlayerId.P1, ZoneRole.HAND)]
    for i in range(hand):
        hand_zone.add(
            register(
                state,
                L5RCard.of(FatePrint, id=f"P1-h{i}", name="H", side=Side.FATE, owner=PlayerId.P1),
            )
        )
    return GameState.start(state, PlayerId.P1)


def _advance_to_end_of_turn(game: GameState) -> None:
    sequence.advance(game)  # Action -> Battle
    sequence.advance(game)  # Battle -> Dynasty
    sequence.advance(game)  # Dynasty -> end of turn


def test_advance_walks_the_three_phases():
    game = _game()
    assert game.phase is Phase.ACTION
    sequence.advance(game)
    assert game.phase is Phase.BATTLE
    sequence.advance(game)
    assert game.phase is Phase.DYNASTY


def test_advance_past_dynasty_draws_fate_and_passes_the_turn():
    game = _game(hand=0, fate_deck=1)

    _advance_to_end_of_turn(game)

    assert game.turn == 2
    assert game.active is PlayerId.P2
    assert game.phase is Phase.ACTION
    assert len(game.table.zones[ZoneKey(PlayerId.P1, ZoneRole.HAND)].cards) == 1
    # Only the active player draws at their turn-end; the opponent's hand is untouched.
    assert game.table.zones[ZoneKey(PlayerId.P2, ZoneRole.HAND)].cards == []


def test_empty_fate_deck_draws_nothing_and_still_passes_the_turn():
    game = _game(hand=0, fate_deck=0)

    _advance_to_end_of_turn(game)

    assert game.turn == 2 and game.active is PlayerId.P2
    assert game.table.zones[ZoneKey(PlayerId.P1, ZoneRole.HAND)].cards == []


def test_the_turns_end_drops_a_conditional_modifier_with_the_rest():
    game = _game(hand=0, fate_deck=1)
    game.ongoing.append(
        ConditionalModifier(
            "flashy", Condition.ATTACKING, Stat.FORCE, -1, Duration.UNTIL_END_OF_TURN
        )
    )

    _advance_to_end_of_turn(game)

    assert game.ongoing == []


def test_advance_empties_the_gold_pool_on_each_phase_change():
    game = _game()
    game.add_gold(PlayerId.P1, 5)
    sequence.advance(game)
    assert game.gold[PlayerId.P1] == 0


def test_the_end_of_turn_discard_is_not_the_seats_own_action():
    """A card that pays its controller "if the action was yours and discarded a Fate card" must not
    be paid for the rulebook trimming their hand. There was no action."""
    game = _game(hand=sequence.MAX_HAND_SIZE, fate_deck=1)
    caravansary = holding(
        "P1-caravansary", printed_id="caravansary", name="Caravansary", owner=PlayerId.P1
    )
    put_in_play(game, caravansary)

    _advance_to_end_of_turn(game)
    victim = game.table.zones[ZoneKey(PlayerId.P1, ZoneRole.HAND)].cards[0].id
    action_sequence.submit(game, DecisionResponse((victim,)))

    assert caravansary.counters == {}


def test_overfull_hand_pauses_for_discard_then_resumes():
    game = _game(hand=sequence.MAX_HAND_SIZE, fate_deck=1)  # 8 held + 1 drawn = 9

    _advance_to_end_of_turn(game)

    assert game.awaiting_decision
    assert isinstance(game.pending, ChooseDiscard) and game.pending.count == 1
    # The request offers the whole hand as candidates.
    hand_cards = game.table.zones[ZoneKey(PlayerId.P1, ZoneRole.HAND)].cards
    assert set(game.pending.candidates) == {card.id for card in hand_cards}
    assert game.turn == 1 and game.active is PlayerId.P1  # turn not yet passed

    hand = game.table.zones[ZoneKey(PlayerId.P1, ZoneRole.HAND)]
    victim = hand.cards[0].id
    action_sequence.submit(game, DecisionResponse((victim,)))

    assert not game.awaiting_decision
    assert game.turn == 2 and game.active is PlayerId.P2
    assert len(hand.cards) == sequence.MAX_HAND_SIZE
    discard = game.table.zones[ZoneKey(PlayerId.P1, ZoneRole.FATE_DISCARD)]
    assert any(card.id == victim for card in discard.cards)


def test_a_refused_cancel_leaves_the_question_pending():
    game = _game(hand=sequence.MAX_HAND_SIZE, fate_deck=1)
    _advance_to_end_of_turn(game)

    with pytest.raises(ValueError, match="cannot be canceled"):
        action_sequence.cancel(game)

    assert isinstance(game.pending, ChooseDiscard)


def test_cannot_advance_while_a_decision_is_pending():
    game = _game(hand=sequence.MAX_HAND_SIZE, fate_deck=1)
    _advance_to_end_of_turn(game)
    assert game.awaiting_decision
    with pytest.raises(RuntimeError):
        sequence.advance(game)


def test_submit_rejects_a_malformed_or_illegal_answer():
    game = _game(hand=sequence.MAX_HAND_SIZE, fate_deck=1)
    _advance_to_end_of_turn(game)

    with pytest.raises(ValueError):  # wrong count: must discard exactly one
        action_sequence.submit(game, DecisionResponse(()))
    with pytest.raises(ValueError):  # right count, but the card is not in hand
        action_sequence.submit(game, DecisionResponse(("not-in-hand",)))
    assert game.awaiting_decision  # both rejections leave the game paused


def _bowed_on_battlefield(state: TableState, seat: PlayerId, card_id: str):
    card = register(
        state, L5RCard.of(DynastyPrint, id=card_id, name="B", side=Side.DYNASTY, owner=seat)
    )
    card.bow()
    state.battlefield.add(card)
    return card


def _facedown_in_province(state: TableState, seat: PlayerId, card_id: str):
    card = register(
        state, L5RCard.of(DynastyPrint, id=card_id, name="P", side=Side.DYNASTY, owner=seat)
    )
    card.turn_face_down()
    state.zones[ops.create_province(state, seat)].add(card)
    return card


@choice_resolver("pause_probe")
def _pause_probe_resolves_to_nothing(game, source_id, chosen, seat):
    return []


def _pause_on_own_event(ctx):
    """A trigger that stops the cascade with an empty choice when the event names its own card."""
    if ctx.event.card_id != ctx.card.id:
        return []
    return [Choose(ctx.card.owner, (), 0, 0, "pause_probe", ctx.card.id)]


def _answer(game: GameState) -> None:
    action_sequence.submit(game, DecisionResponse(()))


def test_a_new_game_starts_with_an_empty_stack():
    game = _game()

    sequence.begin_game(game)

    assert not game.stack and game.pending is None


def test_two_pregame_permanents_that_pause_are_each_answered_before_the_turn_opens(reacting):
    state = TableState.empty_two_seat()
    put_in_play(
        state,
        L5RCard.of(
            StrongholdPrint,
            id="P1-SH",
            name="SH",
            side=Side.STRONGHOLD,
            owner=PlayerId.P1,
            printed_id="pause_probe",
        ),
    )
    put_in_play(
        state,
        L5RCard.of(
            SenseiPrint,
            id="P1-SE",
            name="Sensei",
            side=Side.FATE,
            owner=PlayerId.P1,
            printed_id="pause_probe",
        ),
    )
    bowed = _bowed_on_battlefield(state, PlayerId.P1, "P1-bowed")
    reacting(EnteredPlay, "pause_probe", _pause_on_own_event)
    game = GameState.start(state, PlayerId.P1)

    sequence.begin_game(game)
    assert game.pending is not None and bowed.bowed is True
    _answer(game)
    assert game.pending is not None and bowed.bowed is True
    _answer(game)

    assert game.pending is None and bowed.bowed is False
    assert not game.stack and game.round.priority is game.active


def test_two_cards_that_pause_on_straightening_are_answered_before_any_reveal(reacting):
    state = TableState.empty_two_seat()
    for card_id in ("P1-a", "P1-b"):
        card = put_in_play(state, holding(card_id, printed_id="pause_probe"))
        card.bow()
    facedown = _facedown_in_province(state, PlayerId.P1, "P1-pv")
    reacting(Straightened, "pause_probe", _pause_on_own_event)
    game = GameState.start(state, PlayerId.P1)

    sequence.begin_game(game)
    assert game.pending is not None and facedown.face_up is False
    _answer(game)
    assert game.pending is not None and facedown.face_up is False
    _answer(game)

    assert game.pending is None and facedown.face_up is True
    assert not game.stack and game.round.priority is game.active


def test_a_reveal_that_pauses_is_answered_before_the_turn_starts(reacting):
    state = TableState.empty_two_seat()
    started: list[PlayerId] = []
    put_in_play(state, holding("P1-eyes", printed_id="pause_probe"))
    _facedown_in_province(state, PlayerId.P1, "P1-pv")
    reacting(
        Revealed,
        "pause_probe",
        lambda ctx: [Choose(ctx.card.owner, (), 0, 0, "pause_probe", ctx.card.id)],
    )
    reacting(TurnStarted, "pause_probe", lambda ctx: started.append(ctx.event.seat) or [])
    game = GameState.start(state, PlayerId.P1)

    sequence.begin_game(game)
    assert game.pending is not None and started == []
    _answer(game)

    assert started == [PlayerId.P1]
    assert not game.stack and game.round.priority is game.active


def test_a_pause_on_the_next_seats_straighten_holds_the_turn_boundary(reacting):
    state = dealt_table(hand=0)
    put_in_play(state, holding("P2-a", owner=PlayerId.P2, printed_id="pause_probe")).bow()
    reacting(Straightened, "pause_probe", _pause_on_own_event)
    session = EngineSession.start(state, PlayerId.P1)

    end_turn(session)

    theirs = session.game.table.cards_by_id["P2-a"]
    assert session.game.active is PlayerId.P2 and session.game.pending is not None
    assert theirs.bowed is False and session.game.stack
    session.submit(PlayerId.P2, DecisionResponse(()))
    assert session.game.pending is None and not session.game.stack
    assert session.game.round.priority is PlayerId.P2


def test_a_pause_on_the_turn_starting_leaves_a_clean_record_for_the_first_action(reacting):
    state = TableState.empty_two_seat()
    put_in_play(state, holding("P1-eyes", printed_id="pause_probe"))
    reacting(
        TurnStarted,
        "pause_probe",
        lambda ctx: [Choose(ctx.card.owner, (), 0, 0, "pause_probe", ctx.card.id)],
    )
    game = GameState.start(state, PlayerId.P1)
    game.action_taken = "the Recruit of something"

    sequence.begin_game(game)
    assert game.pending is not None
    _answer(game)

    assert game.action_events == [] and game.action_taken == ""
    assert not game.stack and game.round.priority is game.active


def test_a_pause_as_a_phase_starts_is_answered_before_its_round_opens(reacting):
    state = dealt_table(hand=0)
    put_in_play(state, holding("P1-eyes", printed_id="pause_probe"))
    reacting(
        PhaseStarted,
        "pause_probe",
        lambda ctx: (
            [Choose(ctx.card.owner, (), 0, 0, "pause_probe", ctx.card.id)]
            if ctx.event.phase is Phase.BATTLE
            else []
        ),
    )
    session = EngineSession.start(state, PlayerId.P1)
    end_phase(session)

    assert session.game.phase is Phase.BATTLE and session.game.pending is not None
    assert [type(item).__name__ for item in session.game.stack] == ["OpenRound", "ResumeCascade"]
    session.submit(PlayerId.P1, DecisionResponse(()))

    assert session.game.round.timings == PHASE_TIMINGS[Phase.BATTLE]
    assert not session.game.stack


def test_a_new_game_refills_a_short_province_before_the_first_action():
    state = TableState.empty_two_seat()
    empty = ops.create_province(state, PlayerId.P1)
    state.decks[DeckKey(PlayerId.P1, Side.DYNASTY)].cards = [
        register(
            state,
            L5RCard.of(DynastyPrint, id="P1-next", name="N", side=Side.DYNASTY, owner=PlayerId.P1),
        )
    ]
    game = GameState.start(state, PlayerId.P1)

    sequence.begin_game(game)

    assert [card.id for card in game.table.zones[empty].cards] == ["P1-next"]


def test_begin_game_straightens_and_reveals_only_the_active_board():
    state = TableState.empty_two_seat()
    mine_bowed = _bowed_on_battlefield(state, PlayerId.P1, "P1-bf")
    mine_facedown = _facedown_in_province(state, PlayerId.P1, "P1-pv")
    foe_bowed = _bowed_on_battlefield(state, PlayerId.P2, "P2-bf")
    foe_facedown = _facedown_in_province(state, PlayerId.P2, "P2-pv")

    game = GameState.start(state, PlayerId.P1)
    sequence.begin_game(game)

    assert mine_bowed.bowed is False and mine_facedown.face_up is True
    # The opponent's board is untouched at the active player's start of turn.
    assert foe_bowed.bowed is True and foe_facedown.face_up is False


def test_the_turn_start_straighten_announces_each_card_it_stands_up(reacting):
    """A card that watches for its own straightening has to hear about the one the rulebook does,
    not only the one an effect does. Culling Grounds gives up its Personality either way."""
    state = TableState.empty_two_seat()
    bowed = put_in_play(state, holding("P1-bowed", printed_id="straighten_probe"))
    bowed.bow()
    already_up = put_in_play(state, holding("P1-up", printed_id="plain_farm"))
    seen: list[str] = []
    reacting(Straightened, "straighten_probe", lambda ctx: seen.append(ctx.event.card_id) or [])

    game = GameState.start(state, PlayerId.P1)
    sequence.begin_game(game)

    # One probe hears every Straightened raised, whichever card it names, so a card announced
    # for standing up when it was never bowed would show up here as a second entry.
    assert seen == [bowed.id]
    assert already_up.bowed is False


def test_begin_game_leaves_an_ordinary_seat_enforcing_honor_requirements():
    game = _begun_game_with_sensei("some_other_sensei")
    assert game.table.seats[PlayerId.P1].ignores_honor_requirements is False


# --- the Response Step ---


def _responder_game(*holders: PlayerId) -> GameState:
    """A game where each of ``holders`` holds one Response, the active seat by default. A
    Caravansary per holder, answering its owner's own Fate discard."""
    holders = holders or (PlayerId.P1,)
    state = TableState.empty_two_seat()
    for seat in holders:
        put_in_play(
            state,
            holding(
                f"caravansary-{seat.name}",
                printed_id="caravansary",
                name="Caravansary",
                owner=seat,
                gold_production=2,
            ),
        )
    game = GameState.start(state, PlayerId.P1)
    game.action_events[:] = [
        CardDiscarded(f"some-fate-{seat.name}", Side.FATE, seat) for seat in holders
    ]
    return game


def test_a_response_step_opens_only_when_a_seat_holds_a_response():
    """A Step nobody could act in is a pass nobody needs to be asked for."""
    game = _responder_game()
    game.action_events.clear()  # the discard the Caravansary answers never happened

    assert sequence.open_response_window(game) is False
    assert game.round_stack == []


def test_a_response_opens_under_a_suspended_round_that_is_not_a_response_step():
    """Whether a Response Step may open is a question about the round that is open, not about how
    deep the round stack is. A battle segment suspends the phase round, so reading depth there would
    take every Response in the battle for a Response already in progress and open none of them."""
    game = _responder_game()
    # Standing where the Engage and Combat Segments will: pushed over the phase round, and not
    # itself a Response Step.
    game.round_stack.append(game.round)
    game.round = ActionRound(timings=game.round.timings, priority=game.active)

    assert sequence.open_response_window(game) is True
    assert game.round.kind is RoundKind.RESPONSE
    assert len(game.round_stack) == 2  # the phase round and the segment round, both suspended


def test_a_response_step_opens_no_step_of_its_own():
    """A Response is an action, and one taken inside the Step belongs to the window already open."""
    game = _responder_game()
    sequence.open_response_window(game)

    assert sequence.open_response_window(game) is False


def test_a_response_step_permits_every_seat_a_response_and_nothing_else():
    """Which is permission, not an opportunity: only a seat holding one is asked."""
    game = _responder_game()

    assert sequence.open_response_window(game) is True

    assert game.round.timings == RESPONSE_TIMINGS
    for seat in PlayerId:
        assert legality.permits(game, seat, ActionTiming.RESPONSE)
        assert not legality.permits(game, seat, ActionTiming.OPEN)


def test_passing_a_response_step_returns_to_the_round_it_suspended():
    """The Step is a round over a round: passing it out closes it and hands the opportunity back,
    rather than passing the phase out from under the action that opened it. The one seat holding a
    Response is the only seat asked, so its pass closes the Step."""
    game = _responder_game()
    suspended = game.round
    sequence.open_response_window(game)

    action_sequence.perform(game, Pass())

    assert game.phase is Phase.ACTION
    assert game.round_stack == []
    assert game.round.timings == suspended.timings


def test_taking_the_only_response_closes_the_step():
    game = _responder_game()
    suspended = game.round
    sequence.open_response_window(game)

    action_sequence.perform(game, ActivateAbility("caravansary-P1"))

    assert game.round_stack == []
    assert game.round.timings == suspended.timings
    assert game.table.cards_by_id["caravansary-P1"].counters == {"wealth": 1}


def test_the_step_opens_on_the_seat_holding_the_response():
    """The active seat acts first in every other round."""
    game = _responder_game(PlayerId.P2)

    assert sequence.open_response_window(game) is True

    assert game.round.priority is PlayerId.P2


def test_every_seat_holding_a_response_is_asked_before_the_step_closes():
    game = _responder_game(PlayerId.P1, PlayerId.P2)
    sequence.open_response_window(game)

    action_sequence.perform(game, ActivateAbility("caravansary-P1"))

    assert game.round.kind is RoundKind.RESPONSE
    assert game.round.priority is PlayerId.P2

    action_sequence.perform(game, ActivateAbility("caravansary-P2"))

    assert game.round_stack == []


register_ability(
    "banked_wealth_probe",
    Ability(
        timings=(ActionTiming.RESPONSE,),
        label="Response: nothing, once any wealth is banked",
        cost=no_cost,
        targets=lambda game, source: [source.id]
        if any(card.counters.get("wealth") for card in game.table.cards_by_id.values())
        else [],
        effects=lambda game, source, target: [],
        hits_every_target=True,
    ),
)


def test_a_seat_that_gains_a_response_mid_step_is_asked_before_the_step_closes():
    """The seats are polled as the opportunity comes round, so a Response the first one's effect
    made available is offered instead of missed."""
    game = _responder_game()
    put_in_play(game, holding("probe", printed_id="banked_wealth_probe", owner=PlayerId.P2))
    sequence.open_response_window(game)
    assert game.round.priority is PlayerId.P1

    action_sequence.perform(game, ActivateAbility("caravansary-P1"))

    assert game.round.kind is RoundKind.RESPONSE
    assert game.round.priority is PlayerId.P2


def test_a_new_phase_leaves_no_response_step_open():
    game = _responder_game()
    sequence.open_response_window(game)

    sequence.open_round(game)

    assert game.round_stack == []


def test_an_action_is_worded_for_the_seat_that_must_answer_it():
    """What the Step's banner says. Each action names itself and the card it was taken on, so a seat
    passing the Step is told what it is declining."""
    game = _responder_game()

    assert (
        action_sequence.describe_action(game, Recruit("caravansary-P1"))
        == "the Recruit of Caravansary"
    )
    assert (
        action_sequence.describe_action(game, ActivateAbility("caravansary-P1"))
        == "the ability on Caravansary"
    )
    assert action_sequence.describe_action(game, Lobby()) == "Lobby"
    proxies.spawn_rulebook_proxies(game)
    assert (
        action_sequence.describe_action(game, datasheet_favor_ability("discard_to_draw"))
        == "the ability on Imperial Favor"
    )


def test_no_response_step_leaves_the_view_naming_nothing():
    game = _responder_game()

    assert project(game, PlayerId.P1).responding_to is None


def test_a_suspended_round_that_is_not_a_response_step_names_nothing_either():
    """`responding_to` is what the prompt box reads to say "Responses to X". A battle segment
    suspends the phase round without being a Response Step, and a view that went by stack depth
    would have the prompt claim the seat was answering the last action taken."""
    game = _responder_game()
    game.action_taken = "the Recruit of Caravansary"
    game.round_stack.append(game.round)
    game.round = ActionRound(timings=game.round.timings, priority=game.active)

    assert project(game, PlayerId.P1).responding_to is None


def test_answering_the_turn_start_question_keeps_your_own_first_opportunity():
    """Turn structure is not an action. Answering it must not hand the opportunity on, or a seat
    holding a card that may remain bowed forfeits the opening action of each of its own turns."""
    state = TableState.empty_two_seat()
    put_in_play(state, holding("grounds", printed_id="culling_grounds", owner=PlayerId.P1))
    game = GameState.start(state, PlayerId.P1)
    game.table.cards_by_id["grounds"].bow()
    sequence._begin_turn(game)
    assert isinstance(game.pending, LeaveBowed)

    action_sequence.submit(game, DecisionResponse(("grounds",)))

    assert game.active is PlayerId.P1
    assert game.round.priority is PlayerId.P1


def test_a_turn_boundary_forgets_the_action_a_response_would_answer():
    """A Step opens on what the action just resolved did. An event still recorded a turn later is
    not that, and would open a Step on an action long gone."""
    game = _responder_game()
    game.action_taken = "the Recruit of something"

    sequence.begin_game(game)

    assert game.action_events == []
    assert game.action_taken == ""
    assert sequence.open_response_window(game) is False


def test_opening_a_turn_records_none_of_its_own_events_as_an_action():
    """Straightening and revealing are steps of the turn, not something a seat may respond to."""
    game = _responder_game()

    sequence.begin_game(game)

    assert game.action_events == []


def test_a_straighten_delay_lifts_after_its_own_controller_s_action_phase():
    """The card may not straighten "until after your next Action Phase", so the prohibition outlives
    the straighten step it blocks and belongs to its controller's turn rather than to whoever is
    playing. Lifting it on the wrong seat's phase would stand the card up a turn early.
    """
    # P2 goes first, so the next straighten to run is P1's rather than the delayed card's owner's.
    session = EngineSession.start(dealt_table(hand=0), PlayerId.P2)
    mine = put_in_play(session.game, holding("mine", owner=PlayerId.P2))
    mine.bow()
    triggers.resolve_effects(session.game, [DelayStraighten("mine")])

    _advance_turns(session, 1)  # P1's turn: neither its straighten nor its Action Phase is P2's
    assert "mine" in session.game.straighten_delayed
    assert session.game.table.cards_by_id["mine"].bowed

    _advance_turns(session, 1)  # P2's turn opens; the straighten it is forbidden to take
    assert "mine" in session.game.straighten_delayed
    assert session.game.table.cards_by_id["mine"].bowed

    end_phase(session)  # and P2's Action Phase ends, which is when the prohibition lifts
    assert "mine" not in session.game.straighten_delayed
    assert session.game.table.cards_by_id["mine"].bowed  # nothing straightens it until the step

    _advance_turns(session, 2)
    assert not session.game.table.cards_by_id["mine"].bowed


def test_a_card_forbidden_to_straighten_is_not_straightened_by_an_effect():
    """ "Will not straighten" is a prohibition, not a skipped step: an ability that straightens a
    target card finds this one immovable, and does not spend the prohibition by trying."""
    session = EngineSession.start(dealt_table(hand=0), PlayerId.P1)
    mine = put_in_play(session.game, holding("mine", owner=PlayerId.P1))
    mine.bow()
    triggers.resolve_effects(session.game, [DelayStraighten("mine")])

    triggers.resolve_effects(session.game, [Straighten("mine")])

    assert session.game.table.cards_by_id["mine"].bowed
    assert "mine" in session.game.straighten_delayed


def test_a_straighten_delay_leaves_with_the_card_it_forbids():
    """A token can be banished off the table while a delay is on it. Reading the delay back through
    a card registry that no longer holds it takes the game down on the next phase change."""
    session = EngineSession.start(dealt_table(hand=0), PlayerId.P1)
    mine = put_in_play(session.game, holding("mine", owner=PlayerId.P1))
    mine.bow()
    triggers.resolve_effects(session.game, [DelayStraighten("mine")])
    ops.remove_card(session.game.table, mine)

    end_phase(session)  # the Action phase ends, which is when delays are read

    assert session.game.straighten_delayed == {}


def _advance_turns(session, count: int) -> None:
    """Pass until ``count`` further turns have opened."""
    target = session.game.turn + count
    for _ in range(4 * count + 4):
        if session.game.turn == target:
            return
        end_phase(session)
    raise AssertionError(f"stuck on turn {session.game.turn}, wanted {target}")


def test_resolving_one_moment_drops_it_and_leaves_the_others_waiting():
    """The drop is what makes the walk re-entrant and what bounds ``game.delayed``: an effect that
    stayed on the list would resolve again at every later turn's end."""
    game = GameState.start(TableState.empty_two_seat(), PlayerId.P1)
    later = Moment(Phase.ACTION, Boundary.BEGINNING)
    game.delayed = [(END_OF_TURN, Banish("gone")), (later, Banish("staying"))]

    triggers.resolve_delayed(game, END_OF_TURN)

    assert game.delayed == [(later, Banish("staying"))]


def test_an_effect_delayed_while_the_moment_resolves_waits_for_the_next_one():
    """The list is rebuilt before the held effects run, so a delay one of them schedules survives to
    its own moment instead of being swept up by the walk that created it."""
    game = GameState.start(TableState.empty_two_seat(), PlayerId.P1)
    game.delayed = [(END_OF_TURN, DelayedEffect(Banish("later"), END_OF_TURN))]

    triggers.resolve_delayed(game, END_OF_TURN)

    assert game.delayed == [(END_OF_TURN, Banish("later"))]


def test_every_fired_moment_has_a_resolve_call_behind_it():
    """``FIRED_MOMENTS`` is what ``DelayedEffect`` validates against, so a moment listed there with
    no call site behind it would let through the delay it exists to refuse.

    The turn's own moments are named as constants at their call sites in the turn sequence, and a
    battle's end at its call site in battle resolution. A battle segment's beginning is fired
    generically as its round opens, so it is covered by
    ``test_battle_rounds.test_a_delay_to_a_segments_beginning_resolves_as_it_opens`` instead.
    """
    called = {
        name
        for module in (sequence, resolution)
        for name in re.findall(r"resolve_delayed\(game, (\w+)\)", inspect.getsource(module))
    }
    segment_beginnings = {Moment(segment, Boundary.BEGINNING) for segment in BATTLE_SEGMENT_TIMINGS}

    assert {getattr(structure, name) for name in called} | segment_beginnings == FIRED_MOMENTS


@pytest.mark.parametrize(
    "moment, worded",
    [
        (Moment(Phase.ACTION, Boundary.BEGINNING), "at the beginning of the Action Phase"),
        # A moment is both halves, so neither alone may let a delay through: the stage the flow
        # does reach at an edge it does not, and an edge it does reach on a stage it does not.
        (Moment(Turn.CURRENT, Boundary.BEGINNING), "at the beginning of the turn"),
        (Moment(Phase.ACTION, Boundary.END), "at the end of the Action Phase"),
    ],
)
def test_a_delayed_effect_refuses_a_moment_nothing_resolves(moment, worded):
    game = GameState.start(TableState.empty_two_seat(), PlayerId.P1)

    with pytest.raises(ValueError, match=f"nothing resolves {worded}"):
        DelayedEffect(Banish("card"), moment).perform(game)

    assert game.delayed == []


def test_a_delayed_effect_that_asks_a_question_at_the_end_of_the_turn_is_answered_first():
    # The draw and the hand-size check wait beneath the delayed effects, so the turn goes on once
    # the question is answered.
    game = _game(hand=0, fate_deck=1)
    game.delayed = [(END_OF_TURN, Ask(PlayerId.P1, "a question", TRAIT_ENTRY))]

    _advance_to_end_of_turn(game)
    assert isinstance(game.pending, Confirm)
    assert len(game.table.zones[ZoneKey(PlayerId.P1, ZoneRole.HAND)].cards) == 0

    action_sequence.submit(game, DecisionResponse(()))

    assert len(game.table.zones[ZoneKey(PlayerId.P1, ZoneRole.HAND)].cards) == 1
    assert game.turn == 2


def _begun_game_with_sensei(sensei_printed_id: str) -> GameState:
    state = TableState.empty_two_seat()
    put_in_play(
        state,
        L5RCard.of(StrongholdPrint, id="P1-SH", name="SH", side=Side.STRONGHOLD, owner=PlayerId.P1),
    )
    put_in_play(
        state,
        L5RCard.of(
            SenseiPrint,
            id="P1-SE",
            name="Sensei",
            side=Side.FATE,
            owner=PlayerId.P1,
            printed_id=sensei_printed_id,
        ),
    )
    game = GameState.start(state, PlayerId.P1)
    sequence.begin_game(game)
    return game


register_ability(
    "resolution_probe",
    Ability(
        timings=(ActionTiming.OPEN,),
        label="Open: nothing",
        cost=no_cost,
        targets=itself,
        effects=lambda game, source, target: [],
        hits_every_target=True,
    ),
)


def _resolutions(game: GameState) -> list[ActionResolved]:
    return [event for event in game.turn_events if isinstance(event, ActionResolved)]


def _probe_session() -> EngineSession:
    state = TableState.empty_two_seat()
    put_in_play(state, holding("probe", printed_id="resolution_probe"))
    return EngineSession.start(state, PlayerId.P1)


def test_an_action_announces_its_resolution_once():
    session = _probe_session()

    session.act(PlayerId.P1, ActivateAbility("probe"))

    assert _resolutions(session.game) == [
        ActionResolved(PlayerId.P1, "probe", favor=False, printed=True)
    ]


def test_a_pass_announces_no_resolution():
    session = _probe_session()

    session.act(PlayerId.P1, Pass())

    assert _resolutions(session.game) == []


def test_a_favor_action_that_paused_for_a_choice_is_announced_once_as_a_favor_action():
    game = GameState.start(TableState.empty_two_seat(), PlayerId.P1, seed=0)
    game.table.creatable_tokens[IMPERIAL_FAVOR_ID] = RulebookPrint(
        name="The Imperial Favor", side=Side.FATE, printed_id=IMPERIAL_FAVOR_ID
    )
    TakeFavor(PlayerId.P1).perform(game)
    hand = game.table.zones[ZoneKey(PlayerId.P1, ZoneRole.HAND)]
    hand.add(register(game.table, fate_card("first", PlayerId.P1)))
    hand.add(register(game.table, fate_card("second", PlayerId.P1)))
    proxies.spawn_rulebook_proxies(game)
    favor = datasheet_favor_ability("discard_to_draw")

    action_sequence.perform(game, favor)
    assert _resolutions(game) == []
    submit(game, DecisionResponse(choices=("first",)))

    assert _resolutions(game) == [
        ActionResolved(PlayerId.P1, favor.card_id, favor=True, printed=False)
    ]
    assert favor_actions_this_turn(game, PlayerId.P1) == 1
    assert favor_actions_this_turn(game, PlayerId.P2) == 0


def test_each_phase_announces_its_start_and_the_action_phase_follows_the_turn():
    session = EngineSession.start(dealt_table(hand=0), PlayerId.P1)
    end_phase(session)
    end_phase(session)

    opening = [
        event for event in session.game.turn_events if isinstance(event, TurnStarted | PhaseStarted)
    ]
    assert opening == [
        TurnStarted(PlayerId.P1),
        PhaseStarted(Phase.ACTION),
        PhaseStarted(Phase.BATTLE),
        PhaseStarted(Phase.DYNASTY),
    ]


def test_the_turn_history_is_dropped_as_the_next_turn_begins():
    session = _probe_session()
    session.act(PlayerId.P1, ActivateAbility("probe"))

    end_turn(session)

    assert _resolutions(session.game) == []
    assert any(isinstance(event, TurnStarted) for event in session.game.turn_events)


def _watching_the_hand_reach(game: GameState, size: int, watching) -> list[int]:
    """Put a watcher in P1's hand whose condition is a hand of ``size`` cards, and return the turns
    in which it is told the condition was fulfilled."""
    game.table.zones[ZoneKey(PlayerId.P1, ZoneRole.HAND)].add(
        register(
            game.table,
            L5RCard.of(
                FatePrint,
                id="watcher",
                name="W",
                printed_id="watch_probe",
                side=Side.FATE,
                owner=PlayerId.P1,
            ),
        )
    )
    told: list[int] = []

    def record(ctx):
        told.append(ctx.game.turn)
        return []

    watching(
        "watch_probe",
        lambda game, card: len(game.table.zones[ZoneKey(card.owner, ZoneRole.HAND)].cards) == size,
        record,
    )
    return told


def test_a_condition_the_end_of_turn_draw_fulfills_is_announced_before_the_next_turn(watching):
    game = _game(hand=2, fate_deck=1)
    told = _watching_the_hand_reach(game, 4, watching)

    _advance_to_end_of_turn(game)

    assert told == [1]
    assert game.turn == 2


def test_a_condition_the_end_of_turn_draw_fulfills_is_announced_before_the_hand_size_discard(
    watching,
):
    # Nine cards in hand holds only between the draw and the discard back down to eight.
    game = _game(hand=sequence.MAX_HAND_SIZE - 1, fate_deck=1)
    told = _watching_the_hand_reach(game, sequence.MAX_HAND_SIZE + 1, watching)

    _advance_to_end_of_turn(game)

    assert told == [1]
    assert isinstance(game.pending, ChooseDiscard)
