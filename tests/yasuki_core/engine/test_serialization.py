import json
from dataclasses import dataclass, fields
from pathlib import Path

import pytest

from tests.conftest import _db_available
from tests.yasuki_core.game_pieces.test_factory import RECORDS

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
    _CARD_REGISTRY,
    _PERSISTED_FIELDS,
    encode_zone_key,
    decode_zone_key,
    encode_deck_key,
    decode_deck_key,
    encode_seat,
    decode_seat,
)
from yasuki_core.game_pieces.constants import Side, Element
from yasuki_core.game_pieces.counters import WEALTH
from yasuki_core.decklist import parse_deck_yaml
from yasuki_core.game_pieces.factory import resolve_decklist
from yasuki_core.game_pieces.pregame import StrongholdCard
from yasuki_core.game_pieces.cards import L5RCard
from yasuki_core.game_pieces.prints import (
    HoldingPrint,
    PersonalityPrint,
    RingPrint,
    StrongholdPrint,
)


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
        SpawnCard(
            card_id="tok1",
            card=L5RCard.of(
                PersonalityPrint, id="src", name="Token", side=Side.DYNASTY, force=2, chi=2
            ),
            position=BoardPos(5.0, 6.0),
        ),
        SpawnCard(card_id="tok2", token_id="some_token", position=BoardPos(0.0, 0.0)),
        SpawnCard(card_id="tok3", source_card_id="c1", position=BoardPos(7.0, 8.0)),
        RemoveCard("tok1"),
        Attach("c1", "c2"),
        Attach("c1", ZoneKey(PlayerId.P1, ZoneRole.PROVINCE, 0)),
        Detach("c1"),
        FlipCoin("Heads"),
        FlipCoin("Tails"),
        RollDice(4),
        RollDice(17, sides=20),
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
    personality = L5RCard.of(
        PersonalityPrint, id="dp1", name="Bushi", side=Side.DYNASTY, force=3, chi=2
    )
    ring = L5RCard.of(RingPrint, id="fr", name="Ring of Fire", side=Side.FATE, element=Element.FIRE)

    for card in (personality, ring):
        rebuilt = decode_card(json.loads(json.dumps(encode_card(card))))
        assert rebuilt == card
        assert type(rebuilt) is type(card)  # the concrete subclass, not bare L5RCard


def test_card_counters_survive_a_json_round_trip():
    personality = L5RCard.of(
        PersonalityPrint,
        id="dp2",
        name="Magistrate",
        side=Side.DYNASTY,
        counters={"wealth": 2, "honor": 1},
    )
    rebuilt = decode_card(json.loads(json.dumps(encode_card(personality))))
    assert rebuilt == personality
    assert rebuilt.counters == {"wealth": 2, "honor": 1}


def test_nested_back_face_survives_round_trip():
    back = L5RCard.of(
        StrongholdPrint, id="kk__back", name="Defiled", side=Side.STRONGHOLD, starting_honor=8
    )
    front = L5RCard.of(
        StrongholdPrint,
        id="kk",
        name="Kyuden Kuni",
        side=Side.STRONGHOLD,
        back_card_id="kk__back",
        back=back,
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


# --- the persisted card format ---------------------------------------------------------------------


def test_persisted_fields_match_the_classes():
    """The pinned lists are the format; the dataclasses happen to agree today. Adding a field to a
    card class fails here until someone decides whether it belongs on disk, which is the whole
    reason the lists exist rather than being derived."""
    mismatched = {
        name: (tuple(f.name for f in fields(cls)), _PERSISTED_FIELDS.get(name))
        for name, cls in _CARD_REGISTRY.items()
        if tuple(f.name for f in fields(cls)) != _PERSISTED_FIELDS.get(name)
    }

    assert mismatched == {}


def test_no_persisted_field_list_outlives_its_class():
    """The test above already fails for a class with no list. This is the other direction: a list
    left behind after its class was renamed or dropped, which would otherwise sit there forever
    describing a format nothing writes."""
    assert set(_PERSISTED_FIELDS) - set(_CARD_REGISTRY) == set()


def test_encoding_a_card_class_with_no_list_says_so():
    """A card class that can be built but not saved fails at the save, far from the cause. Naming
    it here is the difference between a one-line fix and an afternoon."""

    @dataclass(frozen=True, slots=True)
    class UnknownCard(L5RCard):
        pass

    with pytest.raises(KeyError, match="UnknownCard has no persisted-field list"):
        encode_card(UnknownCard(id="u", name="U", side=Side.DYNASTY))


def test_a_payload_carries_exactly_the_pinned_fields():
    holding = L5RCard.of(HoldingPrint, id="h", name="Farm", side=Side.DYNASTY, gold_production=2)

    payload = encode_card(holding)

    assert set(payload) == {"__type__", *_PERSISTED_FIELDS["DynastyHolding"]}


GOLDEN = Path(__file__).parent / "golden" / "cards.json"


def _golden_cards() -> dict[str, L5RCard]:
    """Two cards reaching every branch of ``_encode_value``: enum, tuple, list, frozenset, dict,
    Path, None, and a nested card. Two rather than fifteen because the classes differ only in extra
    scalars, and the value encoding they share is what a golden payload is for.

    Every image path is set explicitly, including the ones the card classes default. Those defaults
    are absolute and derived from the install location, so leaving them would bake this machine's
    filesystem into the checked-in bytes.
    """
    holding = L5RCard.of(
        HoldingPrint,
        id="P1-7",
        name="Modest Farm",
        side=Side.DYNASTY,
        printed_id="modest_farm",
        clan="crab",
        clans=("crab", "crane"),
        keywords=("Farm",),
        card_type="Holding",
        creates=("token_a",),
        text="Open: bow.",
        is_unique=True,
        bowed=True,
        face_up=False,
        inverted=True,
        counters={"wealth": 2},
        image_front=Path("sets/roj/farm.png"),
        image_back=Path("backs/dynasty.jpg"),
        owner=PlayerId.P1,
        shown=True,
        peekers=frozenset({PlayerId.P2}),
        is_token=True,
        art_swap={"rect": [1, 2, 3, 4]},
        note="a note",
        gold_cost=1,
        gold_production=2,
    )
    back = L5RCard.of(
        StrongholdPrint,
        id="sh__back",
        name="Kyuden",
        side=Side.STRONGHOLD,
        starting_honor=8,
        image_front=Path("sets/she/kyuden_back.png"),
        image_back=Path("backs/stronghold.jpg"),
    )
    front = L5RCard.of(
        StrongholdPrint,
        id="P1-sh",
        name="Kyuden",
        side=Side.STRONGHOLD,
        back_card_id="sh__back",
        back=back,
        showing_back=True,
        starting_honor=6,
        image_front=Path("sets/she/kyuden.png"),
        image_back=Path("backs/stronghold.jpg"),
    )
    return {"holding": holding, "flip_stronghold": front}


def test_the_encoded_bytes_are_what_was_checked_in():
    """The only check that does not derive its expectation from the code under test. A change to
    how any value type encodes shows up here as a diff rather than as a log nobody can replay."""
    encoded = {name: encode_card(card) for name, card in _golden_cards().items()}

    assert encoded == json.loads(GOLDEN.read_text())


def test_the_checked_in_payloads_decode_to_the_cards_they_came_from():
    stored = json.loads(GOLDEN.read_text())

    for name, card in _golden_cards().items():
        assert decode_card(stored[name]) == card


def test_a_cards_art_swap_survives_the_round_trip():
    """A card borrowing another printing's art carries the payload ``factory._art_swap`` builds,
    whose keywords are a list — the one place a card field holds one."""
    swapped = L5RCard.of(
        HoldingPrint,
        id="h",
        name="Repairing the Ruins",
        side=Side.DYNASTY,
        art_swap={
            "donor_img": "sets/se/wall.png",
            "donor_era": "samurai",
            "donor_layout": "wide",
            "era": "ivory",
            "layout": "tall",
            "keywords": ["Farm", "Temple"],
        },
    )

    rebuilt = decode_card(json.loads(json.dumps(encode_card(swapped))))

    assert rebuilt.art_swap == swapped.art_swap
    assert rebuilt.art_swap["keywords"] == ["Farm", "Temple"]  # a list, not a tuple


def test_a_list_stays_a_list_and_a_tuple_stays_a_tuple():
    # The two encode differently on purpose; collapsing them would round-trip art_swap's keywords
    # into a tuple and quietly change what the browser receives.
    holding = L5RCard.of(
        HoldingPrint,
        id="h2",
        name="X",
        side=Side.DYNASTY,
        keywords=("Farm",),
        art_swap={"keywords": ["Farm"]},
    )

    rebuilt = decode_card(json.loads(json.dumps(encode_card(holding))))

    assert isinstance(rebuilt.keywords, tuple)
    assert isinstance(rebuilt.art_swap["keywords"], list)


def test_the_pinned_list_is_the_format_not_the_dataclass():
    """The two agree today and `test_persisted_fields_match_the_classes` keeps them that way, so
    nothing else can tell which one `encode_card` reads. This forces the list out of step for one
    call to prove the format follows it — that is the property the whole pin exists for, and the
    one that matters on the day a field moves off the card."""
    original = _PERSISTED_FIELDS["DynastyHolding"]
    holding = L5RCard.of(HoldingPrint, id="h", name="Farm", side=Side.DYNASTY, gold_production=2)
    _PERSISTED_FIELDS["DynastyHolding"] = ("id", "name", "side")
    try:
        payload = encode_card(holding)
    finally:
        _PERSISTED_FIELDS["DynastyHolding"] = original

    assert set(payload) == {"__type__", "id", "name", "side"}


def test_decoding_an_unknown_card_type_says_which():
    """The mirror of the encode guard. A payload written by a newer build names a class this one
    has never heard of, and the failure should name it rather than surfacing as a bare key."""
    with pytest.raises(KeyError, match="MysteryCard"):
        decode_card({"__type__": "MysteryCard", "id": "x", "name": "X"})


def test_re_encoding_a_decoded_payload_reproduces_it():
    """Encoding is idempotent through a decode, which is the property that lets a log written by one
    build be read, replayed and written again by another without drifting."""
    stored = json.loads(GOLDEN.read_text())

    assert {name: encode_card(decode_card(p)) for name, p in stored.items()} == stored


@pytest.mark.skipif(not _db_available(), reason="PostgreSQL not available")
def test_a_card_the_factory_built_encodes():
    """The hand-built art-swap case above pins a shape this test proves is the real one — the codec
    could not encode a factory-built card at all until the list branch landed, and no test held the
    two together because none of them ever encoded a card the factory made."""
    yaml = "name: T\nDynasty:\n  - Kuni Yori [Pearl Edition] {art: Ambush [Lotus Edition]}"
    card = resolve_decklist(parse_deck_yaml(yaml), RECORDS, PlayerId.P1).dynasty[0]

    assert card.art_swap is not None  # the shape under test, not an incidental None
    assert decode_card(json.loads(json.dumps(encode_card(card)))) == card


def test_no_checked_in_path_is_absolute():
    """A card's image paths default to the install location, so a golden built without overriding
    them bakes one machine's filesystem into the repository and fails everywhere else."""

    def paths(node):
        if isinstance(node, dict):
            if "__path__" in node:
                yield node["__path__"]
            else:
                for value in node.values():
                    yield from paths(value)
        elif isinstance(node, list):
            for value in node:
                yield from paths(value)

    absolute = [p for p in paths(json.loads(GOLDEN.read_text())) if p.startswith("/")]

    assert absolute == []
