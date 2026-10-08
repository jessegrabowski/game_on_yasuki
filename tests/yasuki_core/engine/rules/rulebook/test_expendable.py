import pytest

from yasuki_core.engine.players import PlayerId
from yasuki_core.engine.rules.effects import Destroy, Discard
from yasuki_core.engine.rules.stats.keyword_grants import KEYWORD_GRANTS, keyword_grant
from yasuki_core.engine.rules.triggers import resolve_effects
from yasuki_core.engine.rules.turn.action_sequence import submit
from yasuki_core.engine.rules.vocabulary.decisions import ChooseNextTrigger, DecisionResponse
from yasuki_core.engine.rules.vocabulary import keywords
from yasuki_core.engine.session import EngineSession
from yasuki_core.engine.table import DeckKey, ZoneKey, ZoneRole
from yasuki_core.game_pieces.constants import AttachmentType, Side

from tests.yasuki_core.engine.builders import (
    attached,
    attachment,
    fate_card,
    holding,
    personality,
    put_in_play,
    register,
    two_seat_game,
)

P1, P2 = PlayerId.P1, PlayerId.P2


def _expendable_game(*, card_keywords=(keywords.EXPENDABLE,), owner=P1):
    """``fodder`` in play with ``card_keywords``, over a Fate deck deep enough to draw from."""
    game = two_seat_game()
    put_in_play(game, personality("fodder", owner=owner, keywords=card_keywords))
    for seat in (P1, P2):
        game.table.decks[DeckKey(seat, Side.FATE)].cards = [
            register(game.table, fate_card(f"{seat.name}-d{index}", seat)) for index in range(4)
        ]
    return EngineSession.start(game.table, P1)


def _held(session, seat) -> int:
    return len(session.game.table.zones[ZoneKey(seat, ZoneRole.HAND)].cards)


@pytest.mark.parametrize(
    ("card_keywords", "drawn"),
    [((keywords.EXPENDABLE,), 1), ((), 0)],
    ids=["expendable", "ordinary"],
)
def test_only_an_expendable_cards_destruction_draws(card_keywords, drawn):
    session = _expendable_game(card_keywords=card_keywords)
    before = _held(session, P1)

    resolve_effects(session.game, [Destroy("fodder", P2)])

    assert _held(session, P1) == before + drawn


def test_the_draw_goes_to_the_expendable_cards_owner_rather_than_its_destroyer():
    session = _expendable_game(owner=P2)
    mine, theirs = _held(session, P1), _held(session, P2)

    resolve_effects(session.game, [Destroy("fodder", P1)])

    assert _held(session, P2) == theirs + 1
    assert _held(session, P1) == mine


def test_discarding_an_expendable_card_draws_nothing():
    """The keyword pays on a destruction, and a discard is not one (CR, Destroy)."""
    session = _expendable_game()
    before = _held(session, P1)

    resolve_effects(session.game, [Discard("fodder", P1)])

    assert _held(session, P1) == before


def test_an_expendable_follower_dying_with_its_personality_draws_for_itself():
    """A Personality takes his unit with him and each member announces its own destruction, so the
    Follower draws although the Personality carrying it has no keyword."""
    session = _expendable_game(card_keywords=())
    attached(
        session.game,
        attachment(
            "levy", attachment_type=AttachmentType.FOLLOWER, keywords=(keywords.EXPENDABLE,)
        ),
        "fodder",
    )
    before = _held(session, P1)

    resolve_effects(session.game, [Destroy("fodder", P2)])

    assert _held(session, P1) == before + 1


def test_two_expendable_cards_in_one_unit_each_draw_once_in_the_order_chosen():
    """Both answer the one destruction, so the active player orders the two draws before either
    resolves."""
    session = _expendable_game()
    attached(
        session.game,
        attachment(
            "levy", attachment_type=AttachmentType.FOLLOWER, keywords=(keywords.EXPENDABLE,)
        ),
        "fodder",
    )
    before = _held(session, P1)

    resolve_effects(session.game, [Destroy("fodder", P2)])
    asked = session.game.pending
    assert isinstance(asked, ChooseNextTrigger)
    assert set(asked.candidates) == {"fodder", "levy"}
    while session.game.pending is not None:
        submit(session.game, DecisionResponse((session.game.pending.candidates[0],)))

    assert _held(session, P1) == before + 2


def test_a_keyword_another_cards_text_confers_draws_too():
    """ "Your Kolat cards have Expendable" is read off the granting card while it is in play, so it
    still reaches a card that has just left."""
    session = _expendable_game(card_keywords=())
    put_in_play(session.game, holding("patron", printed_id="expendable_grant_probe"))

    @keyword_grant("expendable_grant_probe")
    def _grants_expendable(game, holder, card):
        return (keywords.EXPENDABLE,) if card.id == "fodder" else ()

    before = _held(session, P1)
    try:
        resolve_effects(session.game, [Destroy("fodder", P2)])
    finally:
        KEYWORD_GRANTS.pop("expendable_grant_probe", None)

    assert _held(session, P1) == before + 1


def test_a_card_that_prints_the_keyword_and_is_also_given_it_draws_once():
    """Keywords are a set, so holding Expendable from two sources is holding it once. One trigger
    answers the destruction, and the active player is asked to order nothing."""
    session = _expendable_game()
    put_in_play(session.game, holding("patron", printed_id="expendable_grant_probe"))

    @keyword_grant("expendable_grant_probe")
    def _grants_expendable(game, holder, card):
        return (keywords.EXPENDABLE,) if card.id == "fodder" else ()

    before = _held(session, P1)
    try:
        resolve_effects(session.game, [Destroy("fodder", P2)])
    finally:
        KEYWORD_GRANTS.pop("expendable_grant_probe", None)

    assert session.game.pending is None
    assert _held(session, P1) == before + 1
