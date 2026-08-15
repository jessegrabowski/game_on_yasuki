import pytest

from yasuki_core.engine.players import PlayerId
from yasuki_core.engine.rules.actions import ActivateAbility
from yasuki_core.engine.rules.decisions import ChooseCards, Confirm, DecisionResponse
from yasuki_core.engine.rules.log import replay
from yasuki_core.engine.session import EngineSession
from yasuki_core.engine.table import DeckKey, TableState, ZoneKey, ZoneRole
from yasuki_core.game_pieces.cards import L5RCard
from yasuki_core.game_pieces.constants import AttachmentType, Side
from yasuki_core.game_pieces.prints import AttachmentPrint, FatePrint, RingPrint

from tests.yasuki_core.engine.builders import province_card, register

P1 = PlayerId.P1


def _gift_game(*, items=("katana",), plain=("strategy",)) -> EngineSession:
    """A session with Imperial Gift face-up in P1's Province and a Fate deck holding ``items`` Items
    alongside ``plain`` non-Items, so the search has to pick the Items out."""
    state = TableState.empty_two_seat()
    province_card(state, "gift", printed_id="imperial_gift", name="Imperial Gift")
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
    """Making the Items the ability's targets would have withheld the honor from a deck holding
    none, since an ability with no legal target is never offered."""
    session = _gift_game(items=())
    before = session.game.table.seats[P1].honor
    assert ActivateAbility("gift") in session.legal_actions(P1)

    session.act(P1, ActivateAbility("gift"))

    assert session.game.table.seats[P1].honor == before + 2
    assert session.game.pending is None  # no dead prompt over an empty pile


def test_the_gift_replays_to_the_same_state():
    session = _gift_game()
    session.act(P1, ActivateAbility("gift"))
    session.submit(P1, DecisionResponse(("katana",)))
    assert replay(session.log) == session.game


# --- Wisdom Gained ---


def _ring(state, card_id, seat):
    return register(
        state,
        L5RCard.of(RingPrint, id=card_id, name=card_id, side=Side.FATE, owner=seat),
    )


def _wisdom_game(*, p1_deck=("ring1",), p1_discard=(), p2_deck=("ring2",)) -> EngineSession:
    """Wisdom Gained face-up in P1's Province, with Rings salted through each seat's Fate piles."""
    state = TableState.empty_two_seat()
    province_card(state, "wisdom", printed_id="wisdom_gained", name="Wisdom Gained")
    for card_id in p1_deck:
        state.decks[DeckKey(P1, Side.FATE)].cards.append(_ring(state, card_id, P1))
    for card_id in p1_discard:
        state.zones[ZoneKey(P1, ZoneRole.FATE_DISCARD)].add(_ring(state, card_id, P1))
    for card_id in p2_deck:
        state.decks[DeckKey(PlayerId.P2, Side.FATE)].cards.append(
            _ring(state, card_id, PlayerId.P2)
        )
    return EngineSession.start(state, P1)


def _hand_of(session, seat):
    return [c.id for c in session.game.table.zones[ZoneKey(seat, ZoneRole.HAND)].cards]


def test_each_seat_is_offered_the_search_before_it_looks():
    """ "each player **may** search" — and searching is what costs the shuffle, so the offer comes
    before the deck is read rather than as a way out of the dialog afterwards."""
    session = _wisdom_game()
    session.act(P1, ActivateAbility("wisdom"))

    pending = session.game.pending
    assert isinstance(pending, Confirm) and pending.seat is P1
    assert pending.prompt() == "Search your discard pile and Fate deck for a Ring?"


def test_accepting_the_offer_searches_both_the_deck_and_the_discard():
    session = _wisdom_game(p1_deck=("ring1",), p1_discard=("ring-discarded",))
    session.act(P1, ActivateAbility("wisdom"))
    session.submit(P1, DecisionResponse(("wisdom",)))  # yes

    assert set(session.game.pending.candidates) == {"ring1", "ring-discarded"}


def test_declining_passes_the_offer_on_without_touching_the_deck():
    """A seat that declines keeps the order of its deck — nothing is searched, so nothing shuffles."""
    session = _wisdom_game()
    before = [c.id for c in session.game.table.decks[DeckKey(P1, Side.FATE)].cards]
    session.act(P1, ActivateAbility("wisdom"))
    session.submit(P1, DecisionResponse(()))  # no

    assert [c.id for c in session.game.table.decks[DeckKey(P1, Side.FATE)].cards] == before
    assert session.game.pending.seat is PlayerId.P2  # the offer moved on


def test_each_seat_is_offered_in_turn_starting_with_the_controller():
    session = _wisdom_game()
    session.act(P1, ActivateAbility("wisdom"))
    session.submit(P1, DecisionResponse(("wisdom",)))  # P1 accepts
    session.submit(P1, DecisionResponse(("ring1",)))  # and takes

    assert session.game.pending.seat is PlayerId.P2  # now the opponent is offered
    session.submit(PlayerId.P2, DecisionResponse(("wisdom",)))
    session.submit(PlayerId.P2, DecisionResponse(("ring2",)))

    assert session.game.pending is None
    assert _hand_of(session, P1) == ["ring1"]
    assert _hand_of(session, PlayerId.P2) == ["ring2"]


def test_a_seat_with_no_ring_is_not_offered_a_search_it_cannot_make():
    session = _wisdom_game(p1_deck=(), p2_deck=("ring2",))
    session.act(P1, ActivateAbility("wisdom"))

    assert session.game.pending.seat is PlayerId.P2


def test_taking_a_ring_shows_it_and_shuffles_the_deck_it_was_read_from():
    session = _wisdom_game(p1_deck=("ring1", "r2", "r3", "r4", "r5", "r6", "r7", "r8"))
    before = [c.id for c in session.game.table.decks[DeckKey(P1, Side.FATE)].cards]
    session.act(P1, ActivateAbility("wisdom"))
    session.submit(P1, DecisionResponse(("wisdom",)))
    session.submit(P1, DecisionResponse(("ring1",)))

    after = [c.id for c in session.game.table.decks[DeckKey(P1, Side.FATE)].cards]
    assert session.game.table.cards_by_id["ring1"].shown
    assert set(after) == set(before) - {"ring1"}
    assert after != [c for c in before if c != "ring1"]  # re-ordered, not merely shortened


def test_the_opponents_offer_cannot_be_unwound_by_the_controller():
    """Once the offer has passed to the opponent the window is theirs; P1 has nothing in flight."""
    session = _wisdom_game()
    session.act(P1, ActivateAbility("wisdom"))
    session.submit(P1, DecisionResponse(()))

    assert session.abort(P1) is False


def test_wisdom_gained_replays_to_the_same_state():
    session = _wisdom_game()
    session.act(P1, ActivateAbility("wisdom"))
    session.submit(P1, DecisionResponse(("wisdom",)))
    session.submit(P1, DecisionResponse(("ring1",)))
    assert replay(session.log) == session.game
