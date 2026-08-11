import pytest

from yasuki_core.engine.players import PlayerId
from yasuki_core.engine.table import DeckKey, TableState, ZoneKey, ZoneRole
from yasuki_core.engine.rules import legality
from yasuki_core.engine.rules.actions import KharmicDraw, KharmicRefill, Pass
from yasuki_core.engine.rules.decisions import ChoosePayment, DecisionResponse
from yasuki_core.engine.session import EngineSession
from yasuki_core.game_pieces.constants import Side
from yasuki_core.game_pieces.cards import L5RCard
from yasuki_core.game_pieces.prints import FatePrint
from tests.yasuki_core.engine.builders import (
    end_phase,
    fate_card,
    holding,
    province_card,
    put_in_play,
    register,
)

KHARMIC = ("Kharmic",)


def _table(*, hand_kharmic=1, province_kharmic=1, production=2, seat=PlayerId.P1):
    """A board where ``seat`` can pay for Kharmic and has a card to spend on each form."""
    state = TableState.empty_two_seat()
    put_in_play(
        state,
        holding(
            f"{seat.name}-sh", printed_id="plain_stronghold", gold_production=production, owner=seat
        ),
    )
    hand = state.zones[ZoneKey(seat, ZoneRole.HAND)]
    for index in range(hand_kharmic):
        hand.add(
            register(
                state,
                L5RCard.of(
                    FatePrint,
                    id=f"{seat.name}-k{index}",
                    name="Kharmic Fate",
                    side=Side.FATE,
                    owner=seat,
                    keywords=KHARMIC,
                ),
            )
        )
    for index in range(province_kharmic):
        province_card(
            state,
            f"{seat.name}-pk{index}",
            printed_id="plain_holding",
            keywords=KHARMIC,
            seat=seat,
            index=index,
        )
    state.decks[DeckKey(seat, Side.FATE)].cards = [
        register(state, fate_card(f"{seat.name}-fd{i}", seat)) for i in range(3)
    ]
    state.decks[DeckKey(seat, Side.DYNASTY)].cards = [
        register(state, holding(f"{seat.name}-dd{i}", printed_id="plain_holding", owner=seat))
        for i in range(3)
    ]
    return state


def _pay(session, seat=PlayerId.P1):
    """Answer the Kharmic gold cost by bowing whatever the payment offers."""
    pending = session.game.pending
    assert isinstance(pending, ChoosePayment)
    session.submit(seat, DecisionResponse(pending.candidates))


def test_both_kharmic_abilities_are_offered_in_the_action_phase():
    session = EngineSession.start(_table(), PlayerId.P1)

    offered = session.legal_actions(PlayerId.P1)

    assert KharmicDraw("P1-k0") in offered
    assert KharmicRefill("P1-pk0") in offered


def test_kharmic_is_not_offered_outside_the_action_phase():
    # Kharmic is Open, and only the Action Phase's round permits Open actions.
    session = EngineSession.start(_table(), PlayerId.P1)
    end_phase(session)

    offered = session.legal_actions(PlayerId.P1)

    assert KharmicDraw("P1-k0") not in offered and KharmicRefill("P1-pk0") not in offered


def test_kharmic_is_withheld_when_the_seat_cannot_reach_the_cost():
    # One Gold of production against a cost of two. Cycle is still offered — it is the first turn
    # and costs nothing — so the assertion names Kharmic rather than the whole list.
    session = EngineSession.start(_table(production=1), PlayerId.P1)

    offered = session.legal_actions(PlayerId.P1)

    assert KharmicDraw("P1-k0") not in offered and KharmicRefill("P1-pk0") not in offered


@pytest.mark.parametrize(
    ("action", "kwargs"),
    [
        (KharmicDraw("P1-k0"), {"hand_kharmic": 0}),
        (KharmicRefill("P1-pk0"), {"province_kharmic": 0}),
    ],
    ids=["draw-without-a-hand-card", "refill-without-a-province-card"],
)
def test_each_form_is_withheld_without_a_card_to_spend(action, kwargs):
    session = EngineSession.start(_table(**kwargs), PlayerId.P1)

    assert action not in session.legal_actions(PlayerId.P1)


def test_a_face_down_province_card_cannot_be_spent():
    # Provinces are revealed as their owner's turn begins, so before P2 has had one its cards are
    # face-down — unknown even to P2. Its Open window still offers the Fate form, which spends from
    # a hand it can see, and withholds the Dynasty form, which would name a card nobody has seen.
    state = _table(seat=PlayerId.P2, province_kharmic=0)
    put_in_play(state, holding("P1-sh", printed_id="plain_stronghold", gold_production=2))
    province_card(
        state,
        "P2-hidden",
        printed_id="plain_holding",
        keywords=KHARMIC,
        seat=PlayerId.P2,
        index=0,
        face_up=False,
    )
    session = EngineSession.start(state, PlayerId.P1)
    session.act(PlayerId.P1, Pass())

    offered = session.legal_actions(PlayerId.P2)

    assert KharmicDraw("P2-k0") in offered
    assert KharmicRefill("P2-hidden") not in offered


def test_the_fate_form_discards_a_kharmic_card_and_draws():
    session = EngineSession.start(_table(), PlayerId.P1)
    hand = session.game.table.zones[ZoneKey(PlayerId.P1, ZoneRole.HAND)]
    deck = session.game.table.decks[DeckKey(PlayerId.P1, Side.FATE)]
    before = len(deck.cards)

    session.act(PlayerId.P1, KharmicDraw("P1-k0"))
    _pay(session)

    discard = session.game.table.zones[ZoneKey(PlayerId.P1, ZoneRole.FATE_DISCARD)]
    assert [card.id for card in discard.cards] == ["P1-k0"]
    assert len(deck.cards) == before - 1
    assert "P1-k0" not in [card.id for card in hand.cards]


def test_the_dynasty_form_discards_from_a_province_and_refills_it_face_up():
    session = EngineSession.start(_table(), PlayerId.P1)

    session.act(PlayerId.P1, KharmicRefill("P1-pk0"))
    _pay(session)

    province = session.game.table.zones[ZoneKey(PlayerId.P1, ZoneRole.PROVINCE, 0)]
    discard = session.game.table.zones[ZoneKey(PlayerId.P1, ZoneRole.DYNASTY_DISCARD)]
    assert [card.id for card in discard.cards] == ["P1-pk0"]
    # Face-up is the whole point: a face-down refill would leave the Province unrecruitable, and a
    # count-based assertion would pass either way.
    assert len(province.cards) == 1 and province.cards[0].face_up


def test_kharmic_is_repeatable_within_one_turn():
    # No once-per-turn key, so a seat that can still pay and still holds a card may take it again.
    session = EngineSession.start(_table(hand_kharmic=2, production=4), PlayerId.P1)

    session.act(PlayerId.P1, KharmicDraw("P1-k0"))
    _pay(session)
    session.act(PlayerId.P2, Pass())  # the action handed the window on; P2 declines it

    # The spent card is gone, so what proves repeatability is the second one still being offered.
    offered = session.legal_actions(PlayerId.P1)
    assert KharmicDraw("P1-k1") in offered
    assert KharmicDraw("P1-k0") not in offered


def test_the_inactive_seat_may_take_kharmic_in_the_opponents_action_phase():
    # Kharmic is Open, so it is the first action either player can take on a turn that is not theirs.
    state = _table(seat=PlayerId.P2)
    put_in_play(state, holding("P1-sh", printed_id="plain_stronghold", gold_production=2))
    session = EngineSession.start(state, PlayerId.P1)
    session.act(PlayerId.P1, Pass())  # hand the Action-phase window to P2

    assert session.game.round.priority is PlayerId.P2
    assert KharmicDraw("P2-k0") in session.legal_actions(PlayerId.P2)


def test_paying_on_the_opponents_turn_leaves_the_producer_bowed_into_your_own():
    # The economic cost of an Open action: a producer bowed on someone else's turn straightens only
    # when its owner's turn begins.
    state = _table(seat=PlayerId.P2)
    put_in_play(state, holding("P1-sh", printed_id="plain_stronghold", gold_production=2))
    session = EngineSession.start(state, PlayerId.P1)
    session.act(PlayerId.P1, Pass())
    session.act(PlayerId.P2, KharmicDraw("P2-k0"))
    _pay(session, PlayerId.P2)

    assert session.game.table.cards_by_id["P2-sh"].bowed

    while session.game.turn == 1:
        end_phase(session)

    assert session.game.active is PlayerId.P2
    assert not session.game.table.cards_by_id["P2-sh"].bowed


def test_cancelling_the_cost_backs_the_ability_out():
    # A payment advertises itself as cancellable, and the undo used to demand a Recruit behind it —
    # so cancelling a rulebook cost raised instead of backing out. Nothing is committed until the
    # payment is answered, so the board must be exactly as it was.
    session = EngineSession.start(_table(), PlayerId.P1)
    before = [
        card.id for card in session.game.table.zones[ZoneKey(PlayerId.P1, ZoneRole.HAND)].cards
    ]

    session.act(PlayerId.P1, KharmicDraw("P1-k0"))
    session.cancel(PlayerId.P1)

    assert session.game.pending is None
    assert session.game.stack == []
    assert not session.game.table.cards_by_id["P1-sh"].bowed
    hand = session.game.table.zones[ZoneKey(PlayerId.P1, ZoneRole.HAND)]
    assert [card.id for card in hand.cards] == before
    assert KharmicDraw("P1-k0") in session.legal_actions(PlayerId.P1)  # and it can be taken again


def test_a_kharmic_card_is_recognized_by_its_keyword():
    game = EngineSession.start(_table(), PlayerId.P1).game
    kharmic = game.table.cards_by_id["P1-k0"]
    plain = game.table.cards_by_id["P1-fd0"]

    assert legality.is_kharmic_card(game, kharmic)
    assert not legality.is_kharmic_card(game, plain)
