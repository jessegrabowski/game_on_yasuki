from yasuki_core.engine.players import PlayerId
from yasuki_core.engine.rules.actions import PlayStrategy
from yasuki_core.engine.rules.decisions import ChooseAmount, ChoosePayment, DecisionResponse
from yasuki_core.engine.session import EngineSession
from yasuki_core.engine.table import TableState, ZoneKey, ZoneRole
from yasuki_core.game_pieces.cards import L5RCard
from yasuki_core.game_pieces.constants import AttachmentType, Side
from yasuki_core.game_pieces.prints import ActionPrint

from tests.yasuki_core.engine.builders import (
    attached,
    attachment,
    holding,
    personality,
    put_in_play,
    register,
)

PLAYER, OPPONENT = PlayerId.P1, PlayerId.P2


def _hired_killer(state: TableState) -> L5RCard:
    """Hired Killer in the player's hand. It prints no Gold Cost: the cost is the amount paid."""
    card = register(
        state,
        L5RCard.of(
            ActionPrint,
            id="killer",
            name="Hired Killer",
            printed_id="hired_killer",
            side=Side.FATE,
            owner=PLAYER,
        ),
    )
    state.zones[ZoneKey(PLAYER, ZoneRole.HAND)].add(card)
    return card


def _table(*, gold: int = 10) -> TableState:
    """A board with enough Gold Production to cover the amount."""
    state = TableState.empty_two_seat()
    put_in_play(state, holding("mine", owner=PLAYER, gold_production=gold))
    return state


def _in_play(session: EngineSession) -> set[str]:
    return {card.id for card in session.game.table.battlefield.cards}


def _reply(asked, amount: int | None) -> DecisionResponse:
    """What a player would answer: the named amount when asked for one, nothing when the pool
    already covers a payment, and the first option otherwise.

    Answering a covered payment with a producer would bow it, which lowers what the seat can raise
    and so which amounts are offered — the walk declines rather than overpaying.
    """
    if isinstance(asked, ChooseAmount) and amount is not None:
        return DecisionResponse((str(amount),))
    if isinstance(asked, ChoosePayment) and asked.covers_cost(DecisionResponse()):
        return DecisionResponse()
    return DecisionResponse(asked.candidates[:1])


def _amount_asked(session: EngineSession) -> tuple[str, ...]:
    """Advance to the amount question and hand back the amounts on offer."""
    for _ in range(6):
        asked = session.game.pending
        if isinstance(asked, ChooseAmount):
            return asked.candidates
        assert asked is not None, "the amount was never asked"
        session.submit(asked.seat, _reply(asked, None))
    raise AssertionError("the amount was never asked")


def _answer_everything(session: EngineSession, *, amount: int | None = None) -> None:
    """Walk the action to its end, spending ``amount`` when asked."""
    for _ in range(12):
        asked = session.game.pending
        if asked is None:
            return
        session.submit(asked.seat, _reply(asked, amount))
    raise AssertionError("the action never resolved")


def test_it_destroys_the_personality_the_amount_reaches():
    """The card reaches a unit whose Gold Cost is the amount paid minus two."""
    state = _table()
    put_in_play(state, personality("cheap", owner=OPPONENT, gold_cost=1))
    put_in_play(state, personality("dear", owner=OPPONENT, gold_cost=6))
    card = _hired_killer(state)
    session = EngineSession.start(state, PLAYER)

    session.act(PLAYER, PlayStrategy(card.id))
    _answer_everything(session, amount=8)  # his unit costs 6

    assert "dear" not in _in_play(session)
    assert "cheap" in _in_play(session)  # the amount did not reach him


def test_the_price_counts_the_whole_unit_not_just_the_personality():
    """A unit's Gold Cost is the Personality's and everything attached to him (CR, Unit), so a
    Follower raises the amount that reaches him."""
    state = _table()
    put_in_play(state, personality("guarded", owner=OPPONENT, gold_cost=2))
    card = _hired_killer(state)
    session = EngineSession.start(state, PLAYER)
    attached(
        session.game,
        attachment("banner", attachment_type=AttachmentType.FOLLOWER, gold_cost=3, owner=OPPONENT),
        "guarded",
    )

    session.act(PLAYER, PlayStrategy(card.id))
    _answer_everything(session, amount=7)  # 2 for him, 3 for the Follower, 2 over

    assert "guarded" not in _in_play(session)


def test_the_player_loses_three_honor():
    state = _table()
    put_in_play(state, personality("mark", owner=OPPONENT, gold_cost=1))
    card = _hired_killer(state)
    session = EngineSession.start(state, PLAYER)
    before = session.game.table.seats[PLAYER].honor

    session.act(PLAYER, PlayStrategy(card.id))
    _answer_everything(session, amount=3)  # his unit costs 1

    assert session.game.table.seats[PLAYER].honor == before - 3


def test_the_amounts_offered_run_up_to_what_the_seat_can_raise():
    """The seat names any amount it could pay, not only the ones that reach a target, so the range
    is bounded by its Gold and by nothing else."""
    state = _table(gold=2)
    put_in_play(state, personality("cheap", owner=OPPONENT, gold_cost=0))
    put_in_play(state, personality("dear", owner=OPPONENT, gold_cost=9))
    card = _hired_killer(state)
    session = EngineSession.start(state, PLAYER)

    session.act(PLAYER, PlayStrategy(card.id))

    assert _amount_asked(session) == ("0", "1", "2")


def test_an_amount_that_reaches_no_target_spends_the_gold_and_stops():
    """Naming the amount means naming one that reaches nobody is possible. An effect that requires
    a target and cannot find one stops the effects after it (CR, Action Sequence step E), so neither
    the destruction nor the Honor loss happens."""
    state = _table()
    put_in_play(state, personality("mark", owner=OPPONENT, gold_cost=1))
    card = _hired_killer(state)
    session = EngineSession.start(state, PLAYER)
    before = session.game.table.seats[PLAYER].honor

    session.act(PLAYER, PlayStrategy(card.id))
    _answer_everything(session, amount=9)  # no unit costs seven

    assert "mark" in _in_play(session)
    assert session.game.table.seats[PLAYER].honor == before
    assert session.game.gold[PLAYER] == 1  # 10 produced, 9 spent


def test_it_is_not_offered_when_there_is_nobody_to_kill():
    """No Personality in play means no amount reaches a target, and a cost with no amount to choose
    is not payable — so the card is never offered."""
    state = _table()
    card = _hired_killer(state)
    session = EngineSession.start(state, PLAYER)

    assert PlayStrategy(card.id) not in session.legal_actions(PLAYER)


def test_it_goes_to_the_discard_once_it_has_resolved():
    state = _table()
    put_in_play(state, personality("mark", owner=OPPONENT, gold_cost=1))
    card = _hired_killer(state)
    session = EngineSession.start(state, PLAYER)

    session.act(PLAYER, PlayStrategy(card.id))
    _answer_everything(session, amount=3)  # his unit costs 1

    discard = session.game.table.zones[ZoneKey(PLAYER, ZoneRole.FATE_DISCARD)]
    assert [held.id for held in discard.cards] == [card.id]


def test_the_player_may_pay_to_destroy_his_own_personality():
    """The card says "a target Personality" without a side, so the seat's own units are reachable —
    at the same price and the same Honor loss."""
    state = _table()
    put_in_play(state, personality("own", owner=PLAYER, gold_cost=1))
    card = _hired_killer(state)
    session = EngineSession.start(state, PLAYER)

    session.act(PLAYER, PlayStrategy(card.id))
    _answer_everything(session, amount=3)  # his unit costs 1

    assert "own" not in _in_play(session)
