import json

import pytest

from yasuki_core.engine.players import PlayerId
from yasuki_core.engine.table import (
    TableState,
    ZoneKey,
    ZoneRole,
    DeckKey,
    BoardPos,
    BATTLEFIELD,
    MoveCard,
    SetCardPos,
    SetCardPositions,
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
    FlipDeckTop,
    SearchDeck,
    MoveDeckTop,
    Raise,
    FillProvince,
    DestroyProvince,
    DiscardProvince,
    CreateProvince,
    SetHonor,
    SpawnCard,
    RemoveCard,
    apply_intent,
)
from yasuki_core.game_pieces.constants import Side, Element, Timing
from yasuki_core.game_pieces.dynasty import DynastyCard, DynastyPersonality, DynastyHolding
from yasuki_core.game_pieces.fate import FateCard, FateAction, FateAttachment, FateRing
from yasuki_core.game_pieces.pregame import StrongholdCard
from yasuki_core.engine.zones import ProvinceZone
from yasuki_core.engine.action_log import (
    LogEntry,
    ChatEntry,
    InitialRecord,
    ActionLog,
    apply_and_log,
    build_initial_state,
    action_log_to_dict,
    action_log_from_dict,
    encode_intent,
    decode_intent,
    flush,
)


def _fate_deck(owner: PlayerId) -> list[FateCard]:
    tag = owner.name.lower()
    return [
        FateAction(
            id=f"{tag}_fa1", name="Strike", side=Side.FATE, owner=owner, timings=(Timing.OPEN,)
        ),
        FateAttachment(id=f"{tag}_fa2", name="Katana", side=Side.FATE, owner=owner),
        FateRing(
            id=f"{tag}_fr", name="Ring of Fire", side=Side.FATE, owner=owner, element=Element.FIRE
        ),
        FateCard(id=f"{tag}_f4", name="Spell", side=Side.FATE, owner=owner, focus=3),
        FateCard(id=f"{tag}_f5", name="Ally", side=Side.FATE, owner=owner),
        FateCard(id=f"{tag}_f6", name="Item", side=Side.FATE, owner=owner),
    ]


def _dynasty_deck(owner: PlayerId) -> list[DynastyCard]:
    tag = owner.name.lower()
    return [
        DynastyPersonality(
            id=f"{tag}_dp1", name="Bushi", side=Side.DYNASTY, owner=owner, force=3, chi=2
        ),
        DynastyHolding(
            id=f"{tag}_dh1", name="Mine", side=Side.DYNASTY, owner=owner, gold_production=2
        ),
        DynastyCard(id=f"{tag}_d3", name="Event", side=Side.DYNASTY, owner=owner),
        DynastyPersonality(
            id=f"{tag}_dp2", name="Shugenja", side=Side.DYNASTY, owner=owner, force=1, chi=4
        ),
        DynastyCard(id=f"{tag}_d5", name="Region", side=Side.DYNASTY, owner=owner),
        DynastyHolding(
            id=f"{tag}_dh2", name="Dojo", side=Side.DYNASTY, owner=owner, gold_production=1
        ),
    ]


def _start_state() -> TableState:
    """A loaded-but-undealt two-seat table: both seats named with honor, all four decks filled."""
    state = TableState.empty_two_seat("Ada", "Bao")
    state.seats[PlayerId.P1].honor = 10
    state.seats[PlayerId.P2].honor = 8
    for seat in PlayerId:
        fate, dynasty = _fate_deck(seat), _dynasty_deck(seat)
        state.decks[DeckKey(seat, Side.FATE)].cards = fate
        state.decks[DeckKey(seat, Side.DYNASTY)].cards = dynasty
        for card in (*fate, *dynasty):
            state.cards_by_id[card.id] = card
    state.validate()
    return state


def _script(state: TableState, log: ActionLog) -> None:
    """Drive a small but varied game through the recording hook."""
    ts = 1000.0
    moves = [
        (PlayerId.P1, CreateProvince()),
        (PlayerId.P1, CreateProvince()),
        (PlayerId.P1, Shuffle(DeckKey(PlayerId.P1, Side.FATE), seed=42)),
        (PlayerId.P1, Shuffle(DeckKey(PlayerId.P1, Side.DYNASTY), seed=7)),
        (PlayerId.P1, FillProvince(ZoneKey(PlayerId.P1, ZoneRole.PROVINCE, 0))),
        (PlayerId.P1, Draw(DeckKey(PlayerId.P1, Side.DYNASTY))),  # routes to the empty province 1
        (PlayerId.P1, Draw(DeckKey(PlayerId.P1, Side.FATE))),
        (PlayerId.P1, Draw(DeckKey(PlayerId.P1, Side.FATE))),
        (PlayerId.P1, SearchDeck(DeckKey(PlayerId.P1, Side.FATE))),  # read-only, still recorded
        (PlayerId.P2, Shuffle(DeckKey(PlayerId.P2, Side.DYNASTY), seed=99)),
        (PlayerId.P2, Draw(DeckKey(PlayerId.P2, Side.DYNASTY))),  # no province → battlefield
        (PlayerId.P1, SetHonor(delta=-2)),
        (PlayerId.P2, SetHonor(value=5)),
        (PlayerId.P1, DiscardProvince(ZoneKey(PlayerId.P1, ZoneRole.PROVINCE, 0))),
    ]
    for seat, intent in moves:
        apply_and_log(state, log, seat, intent, ts)
        ts += 1.0
    # A hand card to the battlefield, then mutate it there.
    hand = state.zones[ZoneKey(PlayerId.P1, ZoneRole.HAND)].cards
    assert hand, "the opening draw should have put fate cards in hand"
    card_id = hand[0].id
    apply_and_log(state, log, PlayerId.P1, MoveCard(card_id, BATTLEFIELD, BoardPos(12.0, 34.0)), ts)
    apply_and_log(state, log, PlayerId.P1, Bow((card_id,)), ts + 1.0)
    apply_and_log(state, log, PlayerId.P1, Flip((card_id,)), ts + 2.0)
    apply_and_log(state, log, PlayerId.P1, SetCardPos(card_id, 40.0, 50.0), ts + 3.0)


def test_append_preserves_order_and_holds_initial_at_head():
    initial = InitialRecord.from_state(_start_state())
    log = ActionLog(initial=initial)
    entries = [
        LogEntry(seq=1, ts=1.0, seat=PlayerId.P1, intent=CreateProvince()),
        LogEntry(seq=2, ts=2.0, seat=PlayerId.P2, intent=CreateProvince()),
        LogEntry(
            seq=2, ts=3.0, seat=PlayerId.P1, intent=SearchDeck(DeckKey(PlayerId.P1, Side.FATE))
        ),
    ]
    for entry in entries:
        log.append(entry)

    assert log.initial is initial
    assert log.entries == entries
    assert [e.seq for e in log.entries] == [1, 2, 2]  # monotonic non-decreasing


def test_append_rejects_seq_regression():
    log = ActionLog(initial=InitialRecord.from_state(_start_state()))
    log.append(LogEntry(seq=5, ts=1.0, seat=PlayerId.P1, intent=CreateProvince()))
    with pytest.raises(ValueError, match="seq regressed"):
        log.append(LogEntry(seq=4, ts=2.0, seat=PlayerId.P1, intent=CreateProvince()))


def test_apply_and_log_records_only_accepted_intents():
    state = _start_state()
    log = ActionLog(initial=InitialRecord.from_state(state))

    accepted = apply_and_log(state, log, PlayerId.P1, CreateProvince(), ts=1.0)
    # P2 cannot shuffle P1's deck → rejected, nothing recorded, seq unchanged.
    seq_before = state.seq
    rejected = apply_and_log(
        state, log, PlayerId.P2, Shuffle(DeckKey(PlayerId.P1, Side.FATE), seed=1), ts=2.0
    )

    assert accepted and not rejected
    assert state.seq == seq_before
    assert len(log.entries) == 1
    assert log.entries[0].intent == CreateProvince()
    assert log.entries[0].rng_seed is None  # only SHUFFLE carries a seed


def test_apply_and_log_entry_fields_match_application():
    state = _start_state()
    log = ActionLog(initial=InitialRecord.from_state(state))
    intent = Shuffle(DeckKey(PlayerId.P1, Side.FATE), seed=123)

    apply_and_log(state, log, PlayerId.P1, intent, ts=1717.5)

    entry = log.entries[0]
    assert entry.seq == state.seq
    assert entry.ts == 1717.5
    assert entry.seat is PlayerId.P1
    assert entry.intent is intent
    assert entry.rng_seed == 123  # surfaced from the SHUFFLE intent


def test_apply_and_log_entries_match_the_full_run():
    state = _start_state()
    log = ActionLog(initial=InitialRecord.from_state(state))
    _script(state, log)

    assert [e.seq for e in log.entries] == sorted(e.seq for e in log.entries)
    assert log.entries[-1].seq == state.seq
    # SEARCH_DECK is accepted but read-only: it produced an entry without advancing seq.
    search = [e for e in log.entries if isinstance(e.intent, SearchDeck)]
    assert len(search) == 1


def test_build_initial_state_round_trips_the_start():
    start = _start_state()
    rebuilt = build_initial_state(InitialRecord.from_state(start))
    assert rebuilt == start


def _post_setup_state() -> TableState:
    """A start state plus a filled province and a face-up battlefield permanent with a position."""
    state = _start_state()
    province = ZoneKey(PlayerId.P1, ZoneRole.PROVINCE, 0)
    holding = DynastyCard(
        id="prov0", name="Mine", side=Side.DYNASTY, owner=PlayerId.P1, face_up=False
    )
    state.zones[province] = ProvinceZone(owner=PlayerId.P1, cards=[holding])
    stronghold = StrongholdCard(id="sh", name="Kyuden", side=Side.STRONGHOLD, owner=PlayerId.P1)
    state.battlefield.cards.append(stronghold)
    state.positions["sh"] = BoardPos(5.0, 6.0)
    state.cards_by_id.update({"prov0": holding, "sh": stronghold})
    state.validate()
    return state


def test_full_snapshot_round_trips_provinces_battlefield_and_positions():
    state = _post_setup_state()
    assert build_initial_state(InitialRecord.from_state(state)) == state


def test_full_snapshot_survives_serialization():
    state = _post_setup_state()
    log = ActionLog(initial=InitialRecord.from_state(state))
    restored = action_log_from_dict(json.loads(json.dumps(action_log_to_dict(log))))
    assert restored.replay() == state


def test_replay_reproduces_live_state_bit_for_bit():
    state = _start_state()
    initial = InitialRecord.from_state(state)
    log = ActionLog(initial=initial)
    _script(state, log)

    rebuilt = log.replay()

    assert rebuilt == state
    # Deck order in particular survives the replay.
    for key in state.decks:
        assert [c.id for c in rebuilt.decks[key].cards] == [c.id for c in state.decks[key].cards]


def test_replay_reproduces_spawned_and_removed_cards():
    state = _start_state()
    log = ActionLog(initial=InitialRecord.from_state(state))
    apply_and_log(
        state,
        log,
        PlayerId.P1,
        SpawnCard("t1", "A", Side.FATE, "a.jpg", BoardPos(1.0, 2.0)),
        ts=1.0,
    )
    apply_and_log(
        state,
        log,
        PlayerId.P2,
        SpawnCard("t2", "B", Side.DYNASTY, None, BoardPos(3.0, 4.0)),
        ts=2.0,
    )
    apply_and_log(state, log, PlayerId.P1, RemoveCard("t1"), ts=3.0)

    rebuilt = log.replay()

    assert rebuilt == state
    assert "t1" not in rebuilt.cards_by_id
    assert rebuilt.cards_by_id["t2"].name == "B"


def test_replay_is_independent_of_the_live_table():
    state = _start_state()
    initial = InitialRecord.from_state(state)
    log = ActionLog(initial=initial)
    _script(state, log)
    rebuilt = log.replay()

    # Mutating the live table after the fact must not bleed into the replay's start record.
    apply_intent(state, PlayerId.P1, SetHonor(value=0))
    assert log.replay() == rebuilt


def test_serialized_log_is_json_safe():
    state = _start_state()
    log = ActionLog(initial=InitialRecord.from_state(state))
    _script(state, log)

    text = json.dumps(action_log_to_dict(log))
    assert json.loads(text) == action_log_to_dict(log)


def test_round_trip_serialize_then_replay_matches():
    state = _start_state()
    log = ActionLog(initial=InitialRecord.from_state(state))
    _script(state, log)

    restored = action_log_from_dict(json.loads(json.dumps(action_log_to_dict(log))))

    assert restored.replay() == state
    assert restored.entries == log.entries


@pytest.mark.parametrize(
    "intent",
    [
        MoveCard("c1", BATTLEFIELD, BoardPos(1.0, 2.0)),
        MoveCard("c1", BATTLEFIELD, None),
        MoveCard("c1", DeckKey(PlayerId.P1, Side.FATE)),
        MoveCard("c1", DeckKey(PlayerId.P1, Side.FATE), to_bottom=True),
        MoveCard("c1", ZoneKey(PlayerId.P1, ZoneRole.HAND)),
        MoveCard("c1", ZoneKey(PlayerId.P1, ZoneRole.PROVINCE, 0)),
        SetCardPos("c1", 3.0, 4.0),
        SetCardPositions((("c1", 3.0, 4.0), ("c2", 5.0, 6.0))),
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
        FillProvince(ZoneKey(PlayerId.P1, ZoneRole.PROVINCE, 1)),
        DestroyProvince(ZoneKey(PlayerId.P2, ZoneRole.PROVINCE, 2)),
        DiscardProvince(ZoneKey(PlayerId.P1, ZoneRole.PROVINCE, 0)),
        CreateProvince(),
        SetHonor(delta=3),
        SetHonor(value=-1),
        SpawnCard("tok1", "Token", Side.DYNASTY, "sets/x/a.jpg", BoardPos(5.0, 6.0)),
        SpawnCard("tok2", "Token", Side.FATE, None, BoardPos(0.0, 0.0)),
        RemoveCard("tok1"),
    ],
)
def test_each_intent_survives_a_serialization_round_trip(intent):
    log = ActionLog(initial=InitialRecord.from_state(_start_state()))
    log.append(LogEntry(seq=1, ts=1.0, seat=PlayerId.P1, intent=intent))

    restored = action_log_from_dict(json.loads(json.dumps(action_log_to_dict(log))))

    assert restored.entries[0].intent == intent


def test_setup_seeds_survive_serialization():
    initial = InitialRecord.from_state(_start_state(), setup_seeds={"opening_shuffle": 99})

    restored = action_log_from_dict(action_log_to_dict(ActionLog(initial=initial)))

    assert restored.initial.setup_seeds == {"opening_shuffle": 99}


def test_card_subclass_fields_survive_serialization():
    state = _start_state()
    log = ActionLog(initial=InitialRecord.from_state(state))

    restored = action_log_from_dict(action_log_to_dict(log))

    original = {c.id: c for cards in log.initial.decklists.values() for c in cards}
    rebuilt = {c.id: c for cards in restored.initial.decklists.values() for c in cards}
    assert rebuilt == original
    bushi = rebuilt["p1_dp1"]
    assert isinstance(bushi, DynastyPersonality) and bushi.force == 3 and bushi.chi == 2
    ring = rebuilt["p1_fr"]
    assert isinstance(ring, FateRing) and ring.element is Element.FIRE


def test_nested_back_face_survives_serialization():
    back = StrongholdCard(id="kk__back", name="Defiled", side=Side.STRONGHOLD, starting_honor=8)
    front = StrongholdCard(
        id="kk", name="Kyuden Kuni", side=Side.STRONGHOLD, back_card_id="kk__back", back=back
    )
    key = DeckKey(PlayerId.P1, Side.DYNASTY)
    log = ActionLog(initial=InitialRecord(seats={}, decklists={key: [front]}))

    restored = action_log_from_dict(json.loads(json.dumps(action_log_to_dict(log))))

    rebuilt = restored.initial.decklists[key][0]
    assert rebuilt == front  # dataclass eq compares the nested back face recursively


def test_public_intent_codec_round_trips():
    intent = MoveCard("c1", DeckKey(PlayerId.P1, Side.FATE))
    assert decode_intent(json.loads(json.dumps(encode_intent(intent)))) == intent


def test_chat_interleaves_with_intents_in_send_order():
    state = _start_state()
    log = ActionLog(initial=InitialRecord.from_state(state))

    apply_and_log(state, log, PlayerId.P1, CreateProvince(), ts=1.0)
    log.append(ChatEntry(ts=1.5, sender="Ada", text="nice"))
    apply_and_log(state, log, PlayerId.P2, CreateProvince(), ts=2.0)

    is_chat = [isinstance(entry, ChatEntry) for entry in log.entries]
    assert is_chat == [False, True, False]
    assert log.entries[1].text == "nice"


def test_replay_skips_chat_but_reproduces_state():
    state = _start_state()
    log = ActionLog(initial=InitialRecord.from_state(state))
    _script(state, log)
    # Drop a chat line into the middle of the tape.
    log.entries.insert(len(log.entries) // 2, ChatEntry(ts=0.5, sender="Kenji", text="gg"))

    assert log.replay() == state  # chat does not perturb the folded state


def test_chat_does_not_break_intent_seq_monotonicity():
    log = ActionLog(initial=InitialRecord.from_state(_start_state()))
    log.append(LogEntry(seq=5, ts=1.0, seat=PlayerId.P1, intent=CreateProvince()))
    log.append(ChatEntry(ts=1.5, sender="Ada", text="hi"))
    # A regression is still caught across an interposed chat entry.
    with pytest.raises(ValueError, match="seq regressed"):
        log.append(LogEntry(seq=4, ts=2.0, seat=PlayerId.P1, intent=CreateProvince()))


def test_chat_survives_serialization_round_trip():
    state = _start_state()
    log = ActionLog(initial=InitialRecord.from_state(state))
    apply_and_log(state, log, PlayerId.P1, CreateProvince(), ts=1.0)
    log.append(ChatEntry(ts=1.5, sender="Ada", text="hello <there>"))

    restored = action_log_from_dict(json.loads(json.dumps(action_log_to_dict(log))))

    assert restored.entries == log.entries
    assert restored.entries[1] == ChatEntry(ts=1.5, sender="Ada", text="hello <there>")
    assert restored.replay() == state


def test_flush_hands_serialized_payload_to_sink():
    state = _start_state()
    log = ActionLog(initial=InitialRecord.from_state(state))
    _script(state, log)

    captured = []

    class CapturingSink:
        def write(self, payload: dict) -> None:
            captured.append(payload)

    flush(log, CapturingSink())

    assert captured == [action_log_to_dict(log)]
    assert action_log_from_dict(captured[0]).replay() == state
