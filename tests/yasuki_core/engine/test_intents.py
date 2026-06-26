import pytest

from yasuki_core.engine.players import PlayerId
from yasuki_core.engine.table import (
    ZoneKey,
    ZoneRole,
    DeckKey,
    IntentOp,
    MoveCard,
    SetCardPos,
    SetCardPositions,
    Bow,
    Unbow,
    Flip,
    Invert,
    Show,
    Unshow,
    Peek,
    Unpeek,
    Draw,
    Shuffle,
    SearchDeck,
    FillProvince,
    DestroyProvince,
    DiscardProvince,
    CreateProvince,
    SetHonor,
)
from yasuki_core.game_pieces.constants import Side


@pytest.mark.parametrize(
    "intent, expected_op",
    [
        (MoveCard(card_id="d1", to=ZoneKey(PlayerId.P1, ZoneRole.HAND)), IntentOp.MOVE_CARD),
        (SetCardPos(card_id="d1", x=1.0, y=2.0), IntentOp.SET_CARD_POS),
        (SetCardPositions(moves=(("d1", 1.0, 2.0),)), IntentOp.SET_CARD_POSITIONS),
        (Bow(card_ids=("a",)), IntentOp.BOW),
        (Unbow(card_ids=("a",)), IntentOp.UNBOW),
        (Flip(card_ids=("a",)), IntentOp.FLIP),
        (Invert(card_ids=("a",)), IntentOp.INVERT),
        (Show(card_id="a"), IntentOp.SHOW),
        (Unshow(card_id="a"), IntentOp.UNSHOW),
        (Peek(card_id="a"), IntentOp.PEEK),
        (Unpeek(card_id="a"), IntentOp.UNPEEK),
        (Draw(deck=DeckKey(PlayerId.P1, Side.FATE)), IntentOp.DRAW),
        (Shuffle(deck=DeckKey(PlayerId.P1, Side.FATE), seed=1), IntentOp.SHUFFLE),
        (SearchDeck(deck=DeckKey(PlayerId.P1, Side.FATE)), IntentOp.SEARCH_DECK),
        (FillProvince(zone=ZoneKey(PlayerId.P1, ZoneRole.PROVINCE, 0)), IntentOp.FILL_PROVINCE),
        (
            DestroyProvince(zone=ZoneKey(PlayerId.P1, ZoneRole.PROVINCE, 0)),
            IntentOp.DESTROY_PROVINCE,
        ),
        (
            DiscardProvince(zone=ZoneKey(PlayerId.P1, ZoneRole.PROVINCE, 0)),
            IntentOp.DISCARD_PROVINCE,
        ),
        (CreateProvince(), IntentOp.CREATE_PROVINCE),
        (SetHonor(value=5), IntentOp.SET_HONOR),
    ],
)
def test_every_intent_carries_its_wire_op(intent, expected_op):
    # The op discriminator is the wire-serialization key (PR07); a mis-wired class would route to
    # the wrong handler. apply_intent covers this behaviorally, but pinning it here documents the
    # full vocabulary and fails fast and legibly.
    assert intent.op is expected_op


def test_card_flag_intent_normalizes_ids_to_tuple():
    assert Bow(card_ids=["a", "b"]).card_ids == ("a", "b")


def test_set_honor_requires_exactly_one_target():
    with pytest.raises(ValueError, match="exactly one"):
        SetHonor()
    with pytest.raises(ValueError, match="exactly one"):
        SetHonor(delta=1, value=1)
