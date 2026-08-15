import pytest

from yasuki_core.engine.players import PlayerId
from yasuki_core.engine.rules.actions import ActivateAbility
from yasuki_core.engine.rules.decisions import ChooseCards, DecisionResponse
from yasuki_core.engine.rules.log import replay
from yasuki_core.engine.session import EngineSession
from yasuki_core.engine.table import DeckKey, TableState, ZoneKey, ZoneRole
from yasuki_core.game_pieces.cards import L5RCard
from yasuki_core.game_pieces.constants import AttachmentType, Side
from yasuki_core.game_pieces.prints import AttachmentPrint, FatePrint

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
