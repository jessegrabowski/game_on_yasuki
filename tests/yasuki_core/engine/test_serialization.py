import json

import pytest

from yasuki_core.engine.players import PlayerId
from yasuki_core.engine.table import ZoneKey, ZoneRole, DeckKey, BoardPos, BATTLEFIELD, SeatInfo
from yasuki_core.engine.intents import (
    MoveCard,
    SetCardPos,
    SetCardPositions,
    ReorderHand,
    ReorderPile,
    Bow,
    Unbow,
    Flip,
    FlipFace,
    Invert,
    Show,
    Unshow,
    Peek,
    Unpeek,
    Draw,
    Shuffle,
    FlipCoin,
    RollDice,
    FlipDeckTop,
    SearchDeck,
    MoveDeckTop,
    Raise,
    FillProvince,
    DestroyProvince,
    DiscardProvince,
    CreateProvince,
    SetHonor,
    SetNote,
    AdjustCounter,
    GiveControl,
    SpawnCard,
    RemoveCard,
    Attach,
    Detach,
)
from yasuki_core.engine.serialization import (
    encode_intent,
    decode_intent,
    encode_card,
    decode_card,
    encode_zone_key,
    decode_zone_key,
    encode_deck_key,
    decode_deck_key,
    encode_seat,
    decode_seat,
)
from yasuki_core.game_pieces.constants import Side, Element
from yasuki_core.game_pieces.counters import WEALTH
from yasuki_core.game_pieces.dynasty import DynastyPersonality
from yasuki_core.game_pieces.fate import FateRing
from yasuki_core.game_pieces.pregame import StrongholdCard


@pytest.mark.parametrize(
    "intent",
    [
        MoveCard("c1", BATTLEFIELD, BoardPos(1.0, 2.0)),
        MoveCard("c1", BATTLEFIELD, BoardPos(1.0, 2.0), face_down=True),
        MoveCard("c1", BATTLEFIELD, None),
        MoveCard("c1", DeckKey(PlayerId.P1, Side.FATE)),
        MoveCard("c1", DeckKey(PlayerId.P1, Side.FATE), to_bottom=True),
        MoveCard("c1", ZoneKey(PlayerId.P1, ZoneRole.HAND)),
        MoveCard("c1", ZoneKey(PlayerId.P1, ZoneRole.HAND), index=2),
        MoveCard("c1", ZoneKey(PlayerId.P1, ZoneRole.PROVINCE, 0)),
        SetCardPos("c1", 3.0, 4.0),
        SetCardPositions((("c1", 3.0, 4.0), ("c2", 5.0, 6.0))),
        ReorderHand("c1", 2),
        ReorderPile(DeckKey(PlayerId.P1, Side.FATE), "c1", 0),
        ReorderPile(ZoneKey(PlayerId.P1, ZoneRole.FATE_DISCARD), "c1", 2),
        Bow(("a", "b")),
        Unbow(("a",)),
        Flip(("a",)),
        FlipFace(("a",)),
        Invert(("a",)),
        Show("a"),
        Unshow("a"),
        Peek("a"),
        Unpeek("a"),
        Draw(DeckKey(PlayerId.P1, Side.DYNASTY)),
        Shuffle(DeckKey(PlayerId.P1, Side.FATE), seed=5),
        FlipDeckTop(DeckKey(PlayerId.P1, Side.FATE)),
        SearchDeck(DeckKey(PlayerId.P2, Side.FATE)),
        SearchDeck(DeckKey(PlayerId.P1, Side.DYNASTY), limit=5),
        MoveDeckTop(DeckKey(PlayerId.P1, Side.FATE), BATTLEFIELD, BoardPos(1.0, 2.0)),
        MoveDeckTop(DeckKey(PlayerId.P1, Side.DYNASTY), ZoneKey(PlayerId.P1, ZoneRole.PROVINCE, 0)),
        MoveDeckTop(DeckKey(PlayerId.P2, Side.FATE), DeckKey(PlayerId.P2, Side.DYNASTY)),
        Raise("c1"),
        SetNote("c1", "dead"),
        SetNote("c1", None),
        AdjustCounter("c1", WEALTH, 2),
        AdjustCounter("c1", WEALTH, -1),
        GiveControl("c1"),
        FillProvince(ZoneKey(PlayerId.P1, ZoneRole.PROVINCE, 1)),
        DestroyProvince(ZoneKey(PlayerId.P2, ZoneRole.PROVINCE, 2)),
        DiscardProvince(ZoneKey(PlayerId.P1, ZoneRole.PROVINCE, 0)),
        CreateProvince(),
        SetHonor(delta=3),
        SetHonor(value=-1),
        SpawnCard("tok1", "Token", Side.DYNASTY, "sets/x/a.jpg", BoardPos(5.0, 6.0)),
        SpawnCard("tok2", "Token", Side.FATE, None, BoardPos(0.0, 0.0)),
        RemoveCard("tok1"),
        Attach("c1", "c2"),
        Attach("c1", ZoneKey(PlayerId.P1, ZoneRole.PROVINCE, 0)),
        Detach("c1"),
        FlipCoin(seed=5),
        RollDice(seed=7),
        RollDice(seed=7, sides=20),
    ],
)
def test_each_intent_survives_a_json_round_trip(intent):
    assert decode_intent(json.loads(json.dumps(encode_intent(intent)))) == intent


def test_decoding_an_unknown_counter_is_rejected():
    # The counter vocabulary is closed, so a malformed envelope naming an unregistered counter
    # raises rather than minting a novel counter — the caller treats the raise as a rejected intent.
    with pytest.raises(KeyError):
        decode_intent({"op": "ADJUST_COUNTER", "card_id": "c1", "name": "bogus", "delta": 1})


def test_card_subclass_and_typed_fields_survive_round_trip():
    personality = DynastyPersonality(id="dp1", name="Bushi", side=Side.DYNASTY, force=3, chi=2)
    ring = FateRing(id="fr", name="Ring of Fire", side=Side.FATE, element=Element.FIRE)

    for card in (personality, ring):
        rebuilt = decode_card(json.loads(json.dumps(encode_card(card))))
        assert rebuilt == card
        assert type(rebuilt) is type(card)  # the concrete subclass, not bare L5RCard


def test_card_counters_survive_a_json_round_trip():
    personality = DynastyPersonality(
        id="dp2", name="Magistrate", side=Side.DYNASTY, counters={"wealth": 2, "honor": 1}
    )
    rebuilt = decode_card(json.loads(json.dumps(encode_card(personality))))
    assert rebuilt == personality
    assert rebuilt.counters == {"wealth": 2, "honor": 1}


def test_nested_back_face_survives_round_trip():
    back = StrongholdCard(id="kk__back", name="Defiled", side=Side.STRONGHOLD, starting_honor=8)
    front = StrongholdCard(
        id="kk", name="Kyuden Kuni", side=Side.STRONGHOLD, back_card_id="kk__back", back=back
    )

    rebuilt = decode_card(json.loads(json.dumps(encode_card(front))))

    assert rebuilt == front  # dataclass eq compares the nested back face recursively
    assert isinstance(rebuilt.back, StrongholdCard)


@pytest.mark.parametrize(
    "key",
    [
        ZoneKey(PlayerId.P1, ZoneRole.HAND),
        ZoneKey(PlayerId.P2, ZoneRole.PROVINCE, 3),  # PROVINCE carries an idx; others do not
    ],
)
def test_zone_key_round_trips(key):
    assert decode_zone_key(encode_zone_key(key)) == key


@pytest.mark.parametrize(
    "key",
    [DeckKey(PlayerId.P1, Side.FATE), DeckKey(PlayerId.P2, Side.DYNASTY)],
)
def test_deck_key_round_trips(key):
    assert decode_deck_key(encode_deck_key(key)) == key


def test_seat_round_trips():
    info = SeatInfo(name="Ada", honor=7, ready=True, connected=True)
    assert decode_seat(encode_seat(info)) == info
