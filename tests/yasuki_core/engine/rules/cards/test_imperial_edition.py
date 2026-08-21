import pytest

from yasuki_core.engine.players import PlayerId
from yasuki_core.engine.rules.actions import ActivateAbility, Pass
from yasuki_core.engine.rules.decisions import ChooseCards, DecisionResponse
from yasuki_core.engine.rules.log import replay
from yasuki_core.engine.session import EngineSession
from yasuki_core.engine.table import DeckKey, TableState, ZoneKey, ZoneRole
from yasuki_core.game_pieces.cards import L5RCard
from yasuki_core.game_pieces.constants import AttachmentType, Side
from yasuki_core.game_pieces.prints import AttachmentPrint, FatePrint

from tests.yasuki_core.engine.builders import (
    attached,
    end_turn,
    attachment,
    holding,
    personality,
    province_card,
    put_in_play,
    register,
    two_seat_game,
)

P1 = PlayerId.P1


# --- Fantastic Gardens ---


def _gardens_game():
    """The Gardens in play, in the Action phase a Limited ability is taken in."""
    game = two_seat_game()
    put_in_play(game, holding("gardens", printed_id="fantastic_gardens", name="the Gardens"))
    return EngineSession.start(game.table, P1)


def test_bowing_the_gardens_gains_two_honor():
    session = _gardens_game()

    session.act(P1, ActivateAbility("gardens"))

    game = session.game
    assert game.table.seats[P1].honor == 2
    assert game.table.cards_by_id["gardens"].bowed is True


def test_the_gardens_may_be_bowed_again_the_same_turn():
    """Repeatable: bowing is the only thing rationing it, so a Gardens straightened again pays out
    a second time."""
    session = _gardens_game()

    session.act(P1, ActivateAbility("gardens"))
    session.game.table.cards_by_id["gardens"].unbow()
    session.act(PlayerId.P2, Pass())  # priority alternates; the turn is still P1's

    session.act(P1, ActivateAbility("gardens"))

    assert session.game.table.seats[P1].honor == 4


def test_the_gardens_are_withheld_while_bowed():
    session = _gardens_game()
    session.game.table.cards_by_id["gardens"].bow()

    assert ActivateAbility("gardens") not in session.legal_actions(P1)


def test_the_gardens_are_withheld_on_another_seats_turn():
    """Limited rather than Open: only the active player may take it, so its own controller cannot
    use it while the turn belongs to someone else."""
    session = _gardens_game()
    end_turn(session)

    assert session.game.active is PlayerId.P2
    assert ActivateAbility("gardens") not in session.legal_actions(P1)


def test_the_gardens_replay_to_the_same_board():
    session = _gardens_game()
    session.act(P1, ActivateAbility("gardens"))

    assert replay(session.log).table == session.game.table


# --- Imperial Gift ---


def _gift_game(*, items=("katana",), plain=("strategy",), dynasty=("next-card",)) -> EngineSession:
    """A session with Imperial Gift face-up in P1's Province and a Fate deck holding ``items`` Items
    alongside ``plain`` non-Items, so the search has to pick the Items out. ``dynasty`` stocks the
    Dynasty deck the vacated Province refills from."""
    state = TableState.empty_two_seat()
    province_card(state, "gift", printed_id="imperial_gift", name="Imperial Gift")
    for card_id in dynasty:
        state.decks[DeckKey(P1, Side.DYNASTY)].cards.append(
            register(state, holding(card_id, owner=P1))
        )
    deck = state.decks[DeckKey(P1, Side.FATE)]
    for card_id in plain:
        deck.cards.append(
            register(
                state,
                L5RCard.of(FatePrint, id=card_id, name=card_id, side=Side.FATE, owner=P1),
            )
        )
    for card_id in items:
        deck.cards.append(
            register(
                state,
                L5RCard.of(
                    AttachmentPrint,
                    id=card_id,
                    name=card_id,
                    side=Side.FATE,
                    owner=P1,
                    attachment_type=AttachmentType.ITEM,
                ),
            )
        )
    return EngineSession.start(state, P1)


def _hand(session) -> list[str]:
    return [c.id for c in session.game.table.zones[ZoneKey(P1, ZoneRole.HAND)].cards]


def test_it_is_offered_from_its_province():
    session = _gift_game()
    assert ActivateAbility("gift") in session.legal_actions(P1)


def test_the_search_offers_only_items():
    """887 cards are Items and a Fate deck is mostly not; picking them out is the whole search."""
    session = _gift_game(items=("katana", "bow"), plain=("strategy", "spell"))
    session.act(P1, ActivateAbility("gift"))

    pending = session.game.pending
    assert isinstance(pending, ChooseCards)
    assert set(pending.candidates) == {"katana", "bow"}


def test_taking_an_item_shows_it_and_puts_it_in_hand():
    session = _gift_game()
    session.act(P1, ActivateAbility("gift"))
    session.submit(P1, DecisionResponse(("katana",)))

    katana = session.game.table.cards_by_id["katana"]
    assert _hand(session) == ["katana"]
    assert katana.shown  # the opponent saw which Item was taken
    assert "katana" not in {c.id for c in session.game.table.decks[DeckKey(P1, Side.FATE)].cards}


def test_the_honor_is_gained_and_the_event_spent():
    session = _gift_game()
    before = session.game.table.seats[P1].honor
    session.act(P1, ActivateAbility("gift"))

    assert session.game.table.seats[P1].honor == before + 2
    discard = session.game.table.zones[ZoneKey(P1, ZoneRole.DYNASTY_DISCARD)]
    assert "gift" in {c.id for c in discard.cards}


def test_the_search_cannot_be_declined_once_an_item_is_there():
    """ "…search your Fate deck for an Item, show it, and put it in your hand" offers no choice about
    taking what it finds — unlike Wisdom Gained, which says "may"."""
    session = _gift_game()
    session.act(P1, ActivateAbility("gift"))

    with pytest.raises(ValueError, match="malformed answer"):
        session.submit(P1, DecisionResponse(()))


def test_the_fate_deck_is_shuffled_after_the_search_reads_it():
    """The search shows the seat their whole deck, so its order is no longer secret."""
    session = _gift_game(items=("katana",), plain=tuple(f"s{i}" for i in range(8)))
    before = [c.id for c in session.game.table.decks[DeckKey(P1, Side.FATE)].cards]
    session.act(P1, ActivateAbility("gift"))
    session.submit(P1, DecisionResponse(("katana",)))

    after = [c.id for c in session.game.table.decks[DeckKey(P1, Side.FATE)].cards]
    assert set(after) == set(before) - {"katana"}  # same cards, minus the one taken
    assert after != [c for c in before if c != "katana"]  # and not in the order it was read in


def test_a_fate_deck_with_no_item_still_gains_the_honor():
    """The honor is unconditional: the Items are searched for during resolution rather than
    targeted, so a deck holding none still pays out."""
    session = _gift_game(items=())
    before = session.game.table.seats[P1].honor
    assert ActivateAbility("gift") in session.legal_actions(P1)

    session.act(P1, ActivateAbility("gift"))

    assert session.game.table.seats[P1].honor == before + 2
    assert session.game.pending is None  # no dead prompt over an empty pile


def test_the_province_refills_behind_the_spent_event():
    """An Event that spends itself out of a Province leaves it short, and a Province that is short
    refills — otherwise the seat is down a Province for the rest of the game."""
    session = _gift_game()
    session.act(P1, ActivateAbility("gift"))
    session.submit(P1, DecisionResponse(("katana",)))

    province = session.game.table.zones[ZoneKey(P1, ZoneRole.PROVINCE, 0)]
    assert [c.id for c in province.cards] == ["next-card"]
    assert not province.cards[0].face_up  # a refill arrives face-down


def test_the_province_refills_even_when_the_search_finds_nothing():
    session = _gift_game(items=())
    session.act(P1, ActivateAbility("gift"))

    province = session.game.table.zones[ZoneKey(P1, ZoneRole.PROVINCE, 0)]
    assert [c.id for c in province.cards] == ["next-card"]


def test_the_gift_replays_to_the_same_state():
    session = _gift_game()
    session.act(P1, ActivateAbility("gift"))
    session.submit(P1, DecisionResponse(("katana",)))
    assert replay(session.log) == session.game


# --- Touch of Death ---


def _touch_game(*, caster_chi=3, victims=((4, True),)):
    """P1's Touch of Death on a Shugenja, against ``victims`` of ``(chi, bowed)`` owned by P2.

    A victim bowed here stays bowed: the turn-start straighten reaches the active player's cards
    only, and P1 is active.
    """
    game = two_seat_game()
    put_in_play(game, personality("caster", force=2, chi=caster_chi))
    for index, (chi, bowed) in enumerate(victims):
        victim = put_in_play(
            game, personality(f"victim{index}", force=2, chi=chi, owner=PlayerId.P2)
        )
        if bowed:
            victim.bow()
    attached(game, attachment("spell", printed_id="touch_of_death"), "caster")
    return game


def test_touch_of_death_destroys_a_bowed_personality_with_lower_chi():
    game = _touch_game(caster_chi=4, victims=((3, True),))
    session = EngineSession.start(game.table, P1)

    session.act(P1, ActivateAbility("spell"))
    session.submit(P1, DecisionResponse(("victim0",)))

    table = session.game.table
    assert table.cards_by_id["victim0"] not in table.battlefield.cards
    assert table.cards_by_id["caster"].bowed is True  # half the cost
    assert table.cards_by_id["spell"] not in table.battlefield.cards  # the other half


def test_touch_of_death_does_not_target_a_personality_with_higher_chi():
    """ "Equal or lower" is measured against the caster, so a hardier Personality is out of reach."""
    game = _touch_game(caster_chi=2)  # the victim's Chi 4 is above it
    session = EngineSession.start(game.table, P1)

    assert ActivateAbility("spell") not in session.legal_actions(P1)


def test_touch_of_death_targets_a_personality_with_equal_chi():
    """The boundary the card names. An off-by-one here would exclude every equal-Chi target."""
    game = _touch_game(caster_chi=3, victims=((3, True),))
    session = EngineSession.start(game.table, P1)

    assert ActivateAbility("spell") in session.legal_actions(P1)


def test_touch_of_death_does_not_target_an_unbowed_personality():
    # Chi 4 against a caster of 5 — only the standing is what puts him out of reach.
    game = _touch_game(caster_chi=5, victims=((4, False),))
    session = EngineSession.start(game.table, P1)

    assert ActivateAbility("spell") not in session.legal_actions(P1)


def test_touch_of_death_is_withheld_while_its_shugenja_is_bowed():
    """His bow is the cost, so an already-bowed Shugenja cannot pay it whatever the target's Chi."""
    game = _touch_game(caster_chi=5)
    session = EngineSession.start(game.table, P1)
    session.game.table.cards_by_id["caster"].bow()

    assert ActivateAbility("spell") not in session.legal_actions(P1)


def test_touch_of_death_replays_to_the_same_board():
    game = _touch_game(caster_chi=4, victims=((3, True),))
    session = EngineSession.start(game.table, P1)
    session.act(P1, ActivateAbility("spell"))
    session.submit(P1, DecisionResponse(("victim0",)))

    assert replay(session.log).table == session.game.table
