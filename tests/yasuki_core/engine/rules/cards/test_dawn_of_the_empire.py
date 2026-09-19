from yasuki_core.engine.players import PlayerId
from yasuki_core.engine.rules.vocabulary.actions import ActivateAbility
from yasuki_core.engine.rules.vocabulary.decisions import (
    ChooseCards,
    ChooseOption,
    DecisionResponse,
)
from yasuki_core.engine.session import EngineSession
from yasuki_core.engine.table import DeckKey, TableState, ZoneKey, ZoneRole
from yasuki_core.game_pieces.constants import AttachmentType, Side

from tests.yasuki_core.engine.builders import attachment, fate_card, holding, put_in_play, register

P1 = PlayerId.P1
FATE = DeckKey(P1, Side.FATE)


def _temples_game() -> EngineSession:
    """P1's Temples in play over a Fate deck reading, from the top: a Spell, a Follower, a plain
    card, an Item, and one more card below the look."""
    state = TableState.empty_two_seat()
    put_in_play(state, holding("temples", printed_id="temples_of_gisei_toshi", gold_production=2))
    deck = [
        attachment("spell", attachment_type=AttachmentType.SPELL),
        attachment("follower", attachment_type=AttachmentType.FOLLOWER),
        fate_card("plain", P1),
        attachment("item", attachment_type=AttachmentType.ITEM),
        fate_card("deep", P1),
    ]
    state.decks[FATE].cards = [register(state, card) for card in reversed(deck)]
    return EngineSession.start(state, P1)


def _name(session: EngineSession, named: str) -> None:
    session.act(P1, ActivateAbility("temples"))
    pending = session.game.pending
    assert isinstance(pending, ChooseOption) and pending.candidates == ("Follower", "Item", "Spell")
    session.submit(P1, DecisionResponse((named,)))


def test_temples_offers_only_the_named_type_among_the_four_looked_at():
    session = _temples_game()

    _name(session, "Follower")

    pending = session.game.pending
    assert isinstance(pending, ChooseCards) and pending.candidates == ("follower",)
    assert session.game.look.card_ids == ("spell", "follower", "plain", "item")
    assert pending.decline_label == "Decline"


def test_temples_shows_the_taken_card_and_leaves_the_rest_where_they_were():
    session = _temples_game()
    _name(session, "Follower")

    session.submit(P1, DecisionResponse(("follower",)))

    taken = session.game.table.cards_by_id["follower"]
    assert taken in session.game.table.zones[ZoneKey(P1, ZoneRole.HAND)].cards
    assert taken.shown
    assert [card.id for card in reversed(session.game.table.decks[FATE].cards)] == [
        "spell",
        "plain",
        "item",
        "deep",
    ]
    assert session.game.look is None
    assert session.log.replay() == session.game


def test_temples_may_take_nothing_and_leave_the_deck_as_it_was():
    session = _temples_game()
    _name(session, "Follower")

    session.submit(P1, DecisionResponse(()))

    assert [card.id for card in reversed(session.game.table.decks[FATE].cards)] == [
        "spell",
        "follower",
        "plain",
        "item",
        "deep",
    ]
    assert session.game.table.zones[ZoneKey(P1, ZoneRole.HAND)].cards == []
    assert session.game.look is None


def test_temples_still_shows_the_look_when_none_is_of_the_named_type():
    """The seat has read the cards either way, so the look is shown with nothing to pick."""
    session = _temples_game()
    session.game.table.decks[FATE].cards = [
        register(session.game.table, fate_card(card_id, P1)) for card_id in ("d", "c", "b", "a")
    ]

    _name(session, "Spell")

    pending = session.game.pending
    assert isinstance(pending, ChooseCards) and pending.candidates == ()
    assert session.game.look.card_ids == ("a", "b", "c", "d")
    session.submit(P1, DecisionResponse(()))
    assert session.game.look is None
