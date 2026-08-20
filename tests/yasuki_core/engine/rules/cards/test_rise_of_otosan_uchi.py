import pytest

from yasuki_core.engine.players import PlayerId
from yasuki_core.engine.rules.actions import ActivateAbility, Pass
from yasuki_core.engine.rules.cards.rise_of_otosan_uchi import (
    CAVALRY_FOLLOWER,
    EXPENDABLE_SERVANT,
    LION_ANCESTOR,
)
from yasuki_core.engine.rules.decisions import Confirm, DecisionResponse
from yasuki_core.engine.rules.attachments import attachments_of
from yasuki_core.engine.rules.economy import effective_chi, effective_force
from yasuki_core.engine.rules.events import EnteredPlay
from yasuki_core.engine.rules.effects import Straighten
from yasuki_core.engine.rules.triggers import fire, resolve_effects
from yasuki_core.engine.rules.log import replay
from yasuki_core.engine.session import EngineSession
from yasuki_core.engine.table import DeckKey, TableState, ZoneKey, ZoneRole
from yasuki_core.game_pieces.cards import L5RCard
from yasuki_core.game_pieces.constants import Side
from yasuki_core.game_pieces.prints import FatePrint

from tests.yasuki_core.engine.builders import (
    end_turn,
    holding,
    personality,
    province_card,
    put_in_play,
    register,
    token_template,
    two_seat_game,
)

P1, P2 = PlayerId.P1, PlayerId.P2


def _panda_game(fate_cards: int = 2, *, dynasty: tuple[str, ...] = ()) -> EngineSession:
    """A session with Blessings of the Red Panda Spirit face-up in P1's Province and a stocked Fate
    deck for each seat, so both have something to draw. ``dynasty`` stocks P1's Dynasty deck; it is
    empty by default so a test that does not care about the refill sees no card arrive."""
    state = TableState.empty_two_seat()
    province_card(
        state,
        "panda",
        printed_id="blessings_of_the_red_panda_spirit",
        name="Blessings of the Red Panda Spirit",
    )
    for card_id in dynasty:
        state.decks[DeckKey(P1, Side.DYNASTY)].cards.append(
            register(state, holding(card_id, owner=P1))
        )
    for seat in (P1, P2):
        state.decks[DeckKey(seat, Side.FATE)].cards = [
            register(
                state,
                L5RCard.of(FatePrint, id=f"{seat.name}-f{i}", name="F", side=Side.FATE, owner=seat),
            )
            for i in range(fate_cards)
        ]
    return EngineSession.start(state, P1)


def _hand(session, seat) -> list[str]:
    return [c.id for c in session.game.table.zones[ZoneKey(seat, ZoneRole.HAND)].cards]


def _honor(session, seat) -> int:
    return session.game.table.seats[seat].honor


def test_it_is_offered_from_its_province():
    session = _panda_game()
    assert ActivateAbility("panda") in session.legal_actions(P1)


def test_every_seat_gains_honor_and_draws_not_just_the_controller():
    """ "Each player gains 1 Honor and draws a card" — the opponent benefits too, which is the
    card's whole character and the easiest half to leave out."""
    session = _panda_game()
    before = {seat: (_honor(session, seat), len(_hand(session, seat))) for seat in (P1, P2)}

    session.act(P1, ActivateAbility("panda"))

    for seat in (P1, P2):
        honor, hand = before[seat]
        assert _honor(session, seat) == honor + 1
        assert len(_hand(session, seat)) == hand + 1


def test_it_asks_whether_to_keep_the_event_rather_than_offering_it_as_a_target():
    session = _panda_game()
    session.act(P1, ActivateAbility("panda"))

    pending = session.game.pending
    assert isinstance(pending, Confirm)
    assert pending.prompt() == (
        "Shuffle Blessings of the Red Panda Spirit into your Dynasty deck instead of discarding it?"
    )


def test_answering_yes_shuffles_the_event_back_into_the_dynasty_deck():
    """With the Dynasty deck otherwise empty the Event is the only card in it, so the refill of the
    Province it just left draws it straight back — face-down, as a refill arrives. That round trip
    is the sharpest evidence it went to the deck rather than the discard; a stocked deck makes the
    return a chance rather than a certainty."""
    session = _panda_game()
    session.act(P1, ActivateAbility("panda"))
    session.submit(P1, DecisionResponse(("panda",)))

    discard = session.game.table.zones[ZoneKey(P1, ZoneRole.DYNASTY_DISCARD)]
    province = session.game.table.zones[ZoneKey(P1, ZoneRole.PROVINCE, 0)]
    assert "panda" not in {card.id for card in discard.cards}
    assert [card.id for card in province.cards] == ["panda"]
    assert not province.cards[0].face_up


def test_answering_no_discards_the_event():
    """Declining is not doing nothing: the Event is spent either way, only its destination differs."""
    session = _panda_game()
    session.act(P1, ActivateAbility("panda"))
    session.submit(P1, DecisionResponse(()))

    deck = session.game.table.decks[DeckKey(P1, Side.DYNASTY)]
    discard = session.game.table.zones[ZoneKey(P1, ZoneRole.DYNASTY_DISCARD)]
    assert "panda" in {card.id for card in discard.cards}
    assert "panda" not in {card.id for card in deck.cards}


def test_the_province_refills_when_the_event_is_discarded():
    session = _panda_game(dynasty=("next-card",))
    session.act(P1, ActivateAbility("panda"))
    session.submit(P1, DecisionResponse(()))

    province = session.game.table.zones[ZoneKey(P1, ZoneRole.PROVINCE, 0)]
    assert [card.id for card in province.cards] == ["next-card"]
    assert not province.cards[0].face_up


def test_the_province_refills_when_the_event_is_shuffled_back_instead():
    """The refill follows the Event leaving rather than the Event being discarded, so the branch
    that puts it back in the deck refills too. Which card arrives is not asserted: the Event is in
    the shuffled deck it refills from and may be the one drawn."""
    session = _panda_game(dynasty=("next-card",))
    session.act(P1, ActivateAbility("panda"))
    session.submit(P1, DecisionResponse(("panda",)))

    province = session.game.table.zones[ZoneKey(P1, ZoneRole.PROVINCE, 0)]
    assert len(province.cards) == 1
    assert not province.cards[0].face_up  # never the face-up Event, still there to use again


def test_using_the_blessing_replays_to_the_same_state():
    session = _panda_game()
    session.act(P1, ActivateAbility("panda"))
    session.submit(P1, DecisionResponse(("panda",)))
    assert replay(session.log) == session.game


def test_it_cannot_be_backed_out_of_once_the_opponent_has_been_given_something():
    """Every other modeled card emits at its own owner, so this is the only one whose abort can
    reach across the table — and it must not. P2 has seen the card it drew, and taking the card back
    does not take back the seeing."""
    session = _panda_game()
    session.act(P1, ActivateAbility("panda"))
    assert (_honor(session, P2), len(_hand(session, P2))) == (1, 1)  # the gift landed
    drawn = _hand(session, P2)[0]

    assert session.abort(P1) is False
    with pytest.raises(ValueError, match="nothing left to unwind"):
        session.cancel(P1)

    assert _honor(session, P2) == 1  # still theirs
    assert _hand(session, P2) == [drawn]
    assert isinstance(session.game.pending, Confirm)  # and the question is still owed


# --- Culling Grounds ---


def _culling_game():
    """P1's Culling Grounds in play, unbowed and ready to trade Honor for a body."""
    state = TableState.empty_two_seat()
    put_in_play(
        state,
        holding(
            "grounds",
            printed_id="culling_grounds",
            name="Culling Grounds",
            keywords=("Maho", "Shadowlands"),
            gold_production=2,
        ),
    )
    token_template(
        state,
        EXPENDABLE_SERVANT,
        name="Expendable Servant",
        card_type="Personality",
        keywords=("Expendable",),
        force=0,
        chi=2,
    )
    return EngineSession.start(state, P1)


def _servant_of(session):
    return next(card for card in session.game.table.battlefield.cards if card.is_token)


def test_culling_grounds_bows_for_a_personality_and_an_honor():
    session = _culling_game()

    session.act(P1, ActivateAbility("grounds"))

    servant = _servant_of(session)
    assert servant.name == "Expendable Servant"
    assert effective_chi(session.game, servant) == 2
    assert session.game.table.cards_by_id["grounds"].bowed is True
    assert session.game.table.seats[P1].honor == -1


def test_culling_grounds_asks_nobody_to_pick_a_target():
    """The ability names no target, so announcing it resolves the whole thing."""
    session = _culling_game()

    session.act(P1, ActivateAbility("grounds"))

    assert session.game.pending is None


def test_the_servant_survives_the_turn_because_the_holding_stays_bowed():
    """ "May remain bowed": the straighten at the start of the next turn passes the Holding over, so
    nothing unbows it and the servant is safe. The plain Farm beside it is the control — the skip has
    to be for this card, not for the seat."""
    session = _culling_game()
    farm = put_in_play(session.game.table, holding("farm", printed_id="plain_farm"))
    session.act(P1, ActivateAbility("grounds"))
    servant = _servant_of(session)
    farm.bow()

    end_turn(session)
    end_turn(session)  # back around to P1, whose straighten would otherwise reach it

    assert session.game.table.cards_by_id["grounds"].bowed is True
    assert farm.bowed is False
    assert servant.id in session.game.table.cards_by_id


def test_straightening_the_holding_banishes_the_servant():
    session = _culling_game()
    session.act(P1, ActivateAbility("grounds"))
    servant = _servant_of(session)

    resolve_effects(session.game, [Straighten("grounds")])

    assert session.game.table.cards_by_id["grounds"].bowed is False
    assert servant.id not in session.game.table.cards_by_id


def test_a_second_servant_is_only_at_risk_of_its_own_bargain():
    """The banish reaches what the Holding still has out, not every servant it ever made."""
    session = _culling_game()
    session.act(P1, ActivateAbility("grounds"))
    first = _servant_of(session)
    resolve_effects(session.game, [Straighten("grounds")])
    session.act(P2, Pass())  # hand the opportunity back after the first activation
    session.act(P1, ActivateAbility("grounds"))
    second = _servant_of(session)

    assert first.id not in session.game.table.cards_by_id
    assert second.id in session.game.table.cards_by_id
    assert session.game.table.seats[P1].honor == -2


def test_straightening_another_card_leaves_the_servant_alone():
    session = _culling_game()
    put_in_play(session.game.table, holding("farm", printed_id="plain_farm", gold_production=2))
    session.act(P1, ActivateAbility("grounds"))
    servant = _servant_of(session)

    resolve_effects(session.game, [Straighten("farm")])

    assert servant.id in session.game.table.cards_by_id


def test_culling_grounds_is_withheld_while_bowed():
    session = _culling_game()
    session.act(P1, ActivateAbility("grounds"))

    assert ActivateAbility("grounds") not in session.legal_actions(P1)


def test_culling_grounds_replays_to_the_same_board():
    session = _culling_game()
    session.act(P1, ActivateAbility("grounds"))

    assert replay(session.log).table == session.game.table


# --- Kitsu Watanabe ---


def _watanabe_game():
    """Watanabe in play with two Holdings he could spend and an opponent's he could not."""
    game = two_seat_game()
    token_template(
        game,
        LION_ANCESTOR,
        name="Lion Ancestor",
        card_type="Personality",
        keywords=("Ancestor", "Lion Clan", "Samurai", "Spirit"),
        force=2,
        chi=2,
    )
    put_in_play(
        game,
        personality("watanabe", printed_id="kitsu_watanabe_experienced", force=3, chi=3),
    )
    put_in_play(game, holding("shrine", gold_production=2))
    put_in_play(game, holding("dojo", gold_production=1))
    put_in_play(game, holding("theirs", owner=P2, gold_production=2))
    return EngineSession.start(game.table, P1)


def _ancestor_of(session):
    return next(card for card in session.game.table.battlefield.cards if card.is_token)


def test_kitsu_watanabe_spends_a_holding_to_call_an_ancestor():
    session = _watanabe_game()

    session.act(P1, ActivateAbility("watanabe"))
    session.submit(P1, DecisionResponse(("shrine",)))

    game = session.game
    ancestor = _ancestor_of(session)
    assert ancestor.name == "Lion Ancestor"
    assert effective_force(game, ancestor) == 2
    assert game.table.cards_by_id["shrine"] not in game.table.battlefield.cards


def test_kitsu_watanabe_only_spends_his_own_holdings():
    session = _watanabe_game()

    session.act(P1, ActivateAbility("watanabe"))

    assert set(session.game.pending.candidates) == {"shrine", "dojo"}


def test_kitsu_watanabe_is_withheld_with_no_holding_to_spend():
    game = two_seat_game()
    token_template(
        game, LION_ANCESTOR, name="Lion Ancestor", card_type="Personality", force=2, chi=2
    )
    put_in_play(
        game, personality("watanabe", printed_id="kitsu_watanabe_experienced", force=3, chi=3)
    )
    session = EngineSession.start(game.table, P1)

    assert ActivateAbility("watanabe") not in session.legal_actions(P1)


def test_kitsu_watanabe_replays_to_the_same_board():
    session = _watanabe_game()
    session.act(P1, ActivateAbility("watanabe"))
    session.submit(P1, DecisionResponse(("shrine",)))

    assert replay(session.log).table == session.game.table


# --- Shinjo Saeki, Clan Champion ---


def _saeki_game():
    """Saeki about to arrive among one mounted Personality and one on foot."""
    game = two_seat_game()
    token_template(
        game, CAVALRY_FOLLOWER, name="Cavalry", card_type="Follower", keywords=("Cavalry",), force=1
    )
    put_in_play(
        game,
        personality(
            "saeki",
            printed_id="shinjo_saeki_clan_champion_experienced_2",
            force=5,
            chi=4,
            keywords=("Cavalry", "Samurai"),
        ),
    )
    put_in_play(game, personality("rider", force=2, chi=2, keywords=("Cavalry",)))
    put_in_play(game, personality("footman", force=2, chi=2, keywords=("Infantry",)))
    put_in_play(game, personality("theirs", owner=P2, force=2, chi=2, keywords=("Cavalry",)))
    return game


def test_shinjo_saeki_mounts_every_cavalry_personality_he_finds():
    game = _saeki_game()

    fire(game, EnteredPlay("saeki"))

    mounted = {
        card_id: [
            follower.name for follower in attachments_of(game, game.table.cards_by_id[card_id])
        ]
        for card_id in ("saeki", "rider", "footman", "theirs")
    }

    # Saeki carries Cavalry himself, so he is among "each of your Cavalry Personalities"; the
    # Infantry Personality and the opponent's rider are not.
    assert mounted == {
        "saeki": ["Cavalry"],
        "rider": ["Cavalry"],
        "footman": [],
        "theirs": [],
    }


def test_another_arrival_does_not_mount_the_clan():
    game = _saeki_game()

    fire(game, EnteredPlay("rider"))

    assert attachments_of(game, game.table.cards_by_id["rider"]) == ()
