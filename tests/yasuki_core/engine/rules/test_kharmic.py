import json

import pytest


from yasuki_core.engine.players import PlayerId
from yasuki_core.engine.rules.abilities.registry import abilities_for
from yasuki_core.engine.rules.rulebook.kharmic import KHARMIC_DRAW, KHARMIC_REFILL, kharmic_ability
from yasuki_core.engine.rules.vocabulary.actions import ActivateAbility, Pass, PlayStrategy
from yasuki_core.engine.replay.game_log import game_log_from_dict, game_log_to_dict, replay
from yasuki_core.engine.session import EngineSession
from yasuki_core.engine.table import DeckKey, TableState, ZoneKey, ZoneRole
from yasuki_core.game_pieces.cards import L5RCard
from yasuki_core.game_pieces.constants import AttachmentType, Side
from yasuki_core.game_pieces.prints import FatePrint
from tests.yasuki_core.engine.builders import (
    attachment,
    end_phase,
    fate_card,
    holding,
    pay,
    province_card,
    put_in_play,
    register,
)

KHARMIC = ("Kharmic",)
P1, P2 = PlayerId.P1, PlayerId.P2


def _table(*, hand_kharmic=1, province_kharmic=1, production=2, seat=P1):
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


DRAW = ActivateAbility("P1-k0", KHARMIC_DRAW)
REFILL = ActivateAbility("P1-pk0", KHARMIC_REFILL)


def spend(session: EngineSession, seat: PlayerId, action: ActivateAbility) -> None:
    session.act(seat, action)
    pay(session, seat)


def test_kharmic_is_an_ability_of_every_card_carrying_the_keyword():
    game = EngineSession.start(_table(), P1).game

    assert [a.key for a in abilities_for(game, game.table.cards_by_id["P1-k0"])] == [
        KHARMIC_DRAW,
        KHARMIC_REFILL,
    ]
    assert abilities_for(game, game.table.cards_by_id["P1-fd0"]) == ()


def test_both_kharmic_abilities_are_offered_in_the_action_phase():
    session = EngineSession.start(_table(), P1)

    offered = session.legal_actions(P1)

    assert DRAW in offered
    assert REFILL in offered


def test_kharmic_is_not_offered_outside_the_action_phase():
    # Kharmic is Open, and only the Action Phase's round permits Open actions.
    session = EngineSession.start(_table(), P1)
    end_phase(session)

    offered = session.legal_actions(P1)

    assert DRAW not in offered and REFILL not in offered


def test_kharmic_is_withheld_when_the_seat_cannot_reach_the_cost():
    # One Gold of production against a cost of two. Cycle is still offered because it is the first
    # turn and costs nothing, so the assertion names Kharmic rather than the whole list.
    session = EngineSession.start(_table(production=1), P1)

    offered = session.legal_actions(P1)

    assert DRAW not in offered and REFILL not in offered


def test_each_form_is_offered_only_where_its_card_sits():
    # The Fate form spends from the hand and the Dynasty form from a Province, so neither form
    # reaches the other's card.
    session = EngineSession.start(_table(), P1)

    offered = session.legal_actions(P1)

    assert ActivateAbility("P1-k0", KHARMIC_REFILL) not in offered
    assert ActivateAbility("P1-pk0", KHARMIC_DRAW) not in offered


def test_a_kharmic_card_in_hand_is_activated_rather_than_played():
    session = EngineSession.start(_table(), P1)

    offered = session.legal_actions(P1)

    assert DRAW in offered
    assert PlayStrategy("P1-k0", KHARMIC_DRAW) not in offered


def test_a_face_down_province_card_cannot_be_spent():
    # Provinces are revealed as their owner's turn begins, so before P2 has had one its cards are
    # face-down, unknown even to P2. Its Open window still offers the Fate form, which spends from
    # a hand it can see, and withholds the Dynasty form, which would name a card nobody has seen.
    state = _table(seat=P2, province_kharmic=0)
    put_in_play(state, holding("P1-sh", printed_id="plain_stronghold", gold_production=2))
    province_card(
        state,
        "P2-hidden",
        printed_id="plain_holding",
        keywords=KHARMIC,
        seat=P2,
        index=0,
        face_up=False,
    )
    session = EngineSession.start(state, P1)
    session.act(P1, Pass())

    offered = session.legal_actions(P2)

    assert ActivateAbility("P2-k0", KHARMIC_DRAW) in offered
    assert ActivateAbility("P2-pk0", KHARMIC_REFILL) not in offered


def test_the_fate_form_discards_the_card_and_draws_without_a_target_step():
    session = EngineSession.start(_table(), P1)
    hand = session.game.table.zones[ZoneKey(P1, ZoneRole.HAND)]
    deck = session.game.table.decks[DeckKey(P1, Side.FATE)]
    before = len(deck.cards)

    spend(session, P1, DRAW)

    assert session.game.pending is None
    discard = session.game.table.zones[ZoneKey(P1, ZoneRole.FATE_DISCARD)]
    assert [card.id for card in discard.cards] == ["P1-k0"]
    assert len(deck.cards) == before - 1
    assert "P1-k0" not in [card.id for card in hand.cards]


def test_a_plain_hand_card_has_no_kharmic_ability():
    session = EngineSession.start(_table(), P1)
    session.game.table.zones[ZoneKey(P1, ZoneRole.HAND)].add(
        register(session.game.table, fate_card("plain", P1))
    )

    assert ActivateAbility("plain", KHARMIC_DRAW) not in session.legal_actions(P1)


def test_the_dynasty_form_discards_from_a_province_and_refills_it_face_up():
    session = EngineSession.start(_table(), P1)

    spend(session, P1, REFILL)

    province = session.game.table.zones[ZoneKey(P1, ZoneRole.PROVINCE, 0)]
    discard = session.game.table.zones[ZoneKey(P1, ZoneRole.DYNASTY_DISCARD)]
    assert [card.id for card in discard.cards] == ["P1-pk0"]
    # Face-up is the whole point: a face-down refill would leave the Province unrecruitable, and a
    # count-based assertion would pass either way.
    assert len(province.cards) == 1 and province.cards[0].face_up


def test_kharmic_is_repeatable_within_one_turn():
    # No once-per-turn key, so a seat that can still pay and still holds a card may take it again.
    session = EngineSession.start(_table(hand_kharmic=2, production=4), P1)

    spend(session, P1, DRAW)
    session.act(P2, Pass())  # the action handed the window on; P2 declines it

    assert ActivateAbility("P1-k1", KHARMIC_DRAW) in session.legal_actions(P1)


def test_the_inactive_seat_may_take_kharmic_in_the_opponents_action_phase():
    # Kharmic is Open, so it is the first action either player can take on a turn that is not
    # theirs.
    state = _table(seat=P2)
    put_in_play(state, holding("P1-sh", printed_id="plain_stronghold", gold_production=2))
    session = EngineSession.start(state, P1)
    session.act(P1, Pass())  # hand the Action-phase window to P2

    assert session.game.round.priority is P2
    assert ActivateAbility("P2-k0", KHARMIC_DRAW) in session.legal_actions(P2)


def test_paying_on_the_opponents_turn_leaves_the_producer_bowed_into_your_own():
    # The economic cost of an Open action: a producer bowed on someone else's turn straightens only
    # when its owner's turn begins.
    state = _table(seat=P2)
    put_in_play(state, holding("P1-sh", printed_id="plain_stronghold", gold_production=2))
    session = EngineSession.start(state, P1)
    session.act(P1, Pass())
    spend(session, P2, ActivateAbility("P2-k0", KHARMIC_DRAW))

    assert session.game.table.cards_by_id["P2-sh"].bowed

    while session.game.turn == 1:
        end_phase(session)

    assert session.game.active is P2
    assert not session.game.table.cards_by_id["P2-sh"].bowed


def test_cancelling_the_cost_backs_the_ability_out():
    # Nothing is committed until the payment is answered, so the board must be exactly as it was.
    session = EngineSession.start(_table(), P1)
    before = [card.id for card in session.game.table.zones[ZoneKey(P1, ZoneRole.HAND)].cards]

    session.act(P1, DRAW)
    session.cancel(P1)

    assert session.game.pending is None
    assert session.game.stack == []
    assert not session.game.table.cards_by_id["P1-sh"].bowed
    hand = session.game.table.zones[ZoneKey(P1, ZoneRole.HAND)]
    assert [card.id for card in hand.cards] == before
    assert DRAW in session.legal_actions(P1)  # and it can be taken again


def test_a_kharmic_use_replays_to_the_same_board_from_a_stored_tape():
    # The tape names the ability by key, so a replay from the stored form finds the same form.
    session = EngineSession.start(_table(), P1)
    spend(session, P1, REFILL)

    stored = game_log_from_dict(json.loads(json.dumps(game_log_to_dict(session.log))))

    assert replay(stored) == session.game


def test_a_kharmic_ability_names_one_of_the_two_forms():
    with pytest.raises(ValueError, match="'banish' is not a Kharmic form"):
        kharmic_ability("banish")


def test_a_kharmic_spell_in_hand_offers_kharmic_with_no_caster_in_play():
    # A Spell's abilities need a Shugenja to cast them once it is attached. In hand it is attached
    # to nobody, and Kharmic is the keyword's ability rather than the Spell's own.
    state = _table(hand_kharmic=0)
    state.zones[ZoneKey(P1, ZoneRole.HAND)].add(
        register(
            state,
            attachment("spell", attachment_type=AttachmentType.SPELL, keywords=KHARMIC, owner=P1),
        )
    )
    session = EngineSession.start(state, P1)

    assert ActivateAbility("spell", KHARMIC_DRAW) in session.legal_actions(P1)
