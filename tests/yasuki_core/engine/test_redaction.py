import random

import pytest

from yasuki_core.engine.players import PlayerId
from yasuki_core.engine.table import TableState, ZoneKey, ZoneRole, DeckKey, BoardPos
from yasuki_core.engine.zones import ProvinceZone
from yasuki_core.engine.redaction import HiddenCard, redact
from yasuki_core.game_pieces.cards import L5RCard
from yasuki_core.game_pieces.constants import Side

P1, P2 = PlayerId.P1, PlayerId.P2


def _card(card_id, side=Side.FATE, owner=P1, face_up=False, shown=False, peekers=frozenset()):
    return L5RCard(
        id=card_id,
        name=f"name-{card_id}",
        side=side,
        owner=owner,
        face_up=face_up,
        shown=shown,
        peekers=peekers,
        text="secret",
    )


def _opponent(seat):
    return P2 if seat is P1 else P1


def _view_in_zone(role, card, viewer, owner=P1):
    """Place one card in an owner's zone and return how ``viewer`` sees it."""
    table = TableState.empty_two_seat()
    key = ZoneKey(owner, role, 0) if role is ZoneRole.PROVINCE else ZoneKey(owner, role)
    if role is ZoneRole.PROVINCE:
        table.zones[key] = ProvinceZone(owner=owner)
    table.zones[key].cards.append(card)
    table.cards_by_id[card.id] = card
    return redact(table, viewer).zones[key].cards[0]


def _view_on_battlefield(card, viewer):
    table = TableState.empty_two_seat()
    table.battlefield.cards.append(card)
    table.positions[card.id] = BoardPos(1.0, 2.0)
    table.cards_by_id[card.id] = card
    return redact(table, viewer).battlefield[0].card


def _hidden(view) -> bool:
    return isinstance(view, HiddenCard)


def test_hidden_card_exposes_no_identity():
    stub = HiddenCard(card_id="f1", side=Side.FATE)
    assert (stub.card_id, stub.side, stub.face) == ("f1", Side.FATE, "back")
    for identity_field in ("name", "text", "image_front", "image_back"):
        assert not hasattr(stub, identity_field)


def test_owner_sees_own_hand_opponent_sees_backs():
    card = _card("f1", owner=P1)
    assert not _hidden(_view_in_zone(ZoneRole.HAND, card, P1))
    assert _hidden(_view_in_zone(ZoneRole.HAND, card, P2))


def test_hidden_stub_carries_its_public_owner():
    card = _card("f1", owner=P1)
    stub = _view_in_zone(ZoneRole.HAND, card, P2)
    assert isinstance(stub, HiddenCard)
    assert stub.owner == P1


def test_shown_hand_card_is_visible_to_opponent():
    # A fate card the owner already reads, shown to the opponent, becomes public to both.
    card = _card("f1", owner=P1, shown=True)
    assert not _hidden(_view_in_zone(ZoneRole.HAND, card, P1))
    assert not _hidden(_view_in_zone(ZoneRole.HAND, card, P2))


def test_hand_visibility_ignores_face_up():
    # A drawn fate card is face_up in the model, but the hand stays private to its owner.
    card = _card("f1", owner=P1, face_up=True)
    assert _hidden(_view_in_zone(ZoneRole.HAND, card, P2))


@pytest.mark.parametrize("viewer", [P1, P2])
def test_face_down_battlefield_is_a_back_to_everyone(viewer):
    card = _card("d1", side=Side.DYNASTY, owner=P1, face_up=False)
    assert _hidden(_view_on_battlefield(card, viewer))


@pytest.mark.parametrize("viewer", [P1, P2])
def test_face_up_battlefield_is_visible_to_everyone(viewer):
    card = _card("d1", side=Side.DYNASTY, owner=P1, face_up=True)
    assert not _hidden(_view_on_battlefield(card, viewer))


def test_shown_face_down_battlefield_is_visible_to_opponent_only():
    # A face-down card the owner shows: the opponent gains sight, the owner still sees a back.
    card = _card("d1", side=Side.DYNASTY, owner=P1, face_up=False, shown=True)
    assert _hidden(_view_on_battlefield(card, P1))
    assert not _hidden(_view_on_battlefield(card, P2))


def test_peeked_card_is_visible_to_the_peeker_only():
    card = _card("d1", side=Side.DYNASTY, owner=P1, face_up=False, peekers=frozenset({P2}))
    # Only the peeker (P2) may identify it; the owner still sees a face-down back.
    assert not _hidden(_view_on_battlefield(card, P2))
    assert _hidden(_view_on_battlefield(card, P1))


def test_peek_records_the_id_only_for_the_peeker():
    card = _card("d1", side=Side.DYNASTY, owner=P1, face_up=False, peekers=frozenset({P2}))
    table = TableState.empty_two_seat()
    table.battlefield.cards.append(card)
    table.positions[card.id] = BoardPos(1.0, 2.0)
    table.cards_by_id[card.id] = card

    assert redact(table, P2).peeked_ids == frozenset({"d1"})
    assert redact(table, P1).peeked_ids == frozenset()


def test_a_card_seen_by_default_is_not_flagged_peeked():
    # A face-up card the viewer already sees, also in their peekers, is not "peeked-only".
    card = _card("d1", side=Side.DYNASTY, owner=P1, face_up=True, peekers=frozenset({P1}))
    table = TableState.empty_two_seat()
    table.battlefield.cards.append(card)
    table.positions[card.id] = BoardPos(0.0, 0.0)
    table.cards_by_id[card.id] = card

    assert redact(table, P1).peeked_ids == frozenset()


@pytest.mark.parametrize("viewer", [P1, P2])
def test_face_down_province_is_a_back_to_everyone_including_owner(viewer):
    card = _card("d1", side=Side.DYNASTY, owner=P1, face_up=False)
    assert _hidden(_view_in_zone(ZoneRole.PROVINCE, card, viewer))


@pytest.mark.parametrize("viewer", [P1, P2])
def test_face_up_province_is_visible_to_everyone(viewer):
    card = _card("d1", side=Side.DYNASTY, owner=P1, face_up=True)
    assert not _hidden(_view_in_zone(ZoneRole.PROVINCE, card, viewer))


@pytest.mark.parametrize(
    "role", [ZoneRole.FATE_DISCARD, ZoneRole.DYNASTY_DISCARD, ZoneRole.FATE_BANISH]
)
@pytest.mark.parametrize("viewer", [P1, P2])
def test_discards_and_banishes_are_public_even_face_down(role, viewer):
    side = Side.DYNASTY if role is ZoneRole.DYNASTY_DISCARD else Side.FATE
    card = _card("c1", side=side, owner=P1, face_up=False)
    assert not _hidden(_view_in_zone(role, card, viewer))


def test_seats_are_public_to_both_viewers():
    table = TableState.empty_two_seat("Ada", "Kenji")
    table.seats[P1].honor = 12
    table.seats[P2].ready = True
    snap = redact(table, P2)
    assert snap.seats[P1].name == "Ada"
    assert snap.seats[P1].honor == 12
    assert snap.seats[P2].ready is True


def test_deck_shows_count_only_when_top_is_face_down():
    table = TableState.empty_two_seat()
    deck = table.decks[DeckKey(P1, Side.FATE)]
    for i in range(3):
        deck.cards.append(_card(f"f{i}", owner=P1, face_up=False))
    view = redact(table, P1).decks[DeckKey(P1, Side.FATE)]
    assert view.count == 3
    assert view.top is None


def test_deck_exposes_a_flipped_top_card():
    table = TableState.empty_two_seat()
    deck = table.decks[DeckKey(P1, Side.FATE)]
    deck.cards.append(_card("buried", owner=P1, face_up=False))
    deck.cards.append(_card("top", owner=P1, face_up=True))
    view = redact(table, P2).decks[DeckKey(P1, Side.FATE)]
    assert view.count == 2
    assert view.top is not None and view.top.id == "top"


def test_card_ids_survive_redaction_in_both_views():
    card = _card("f1", owner=P1, face_up=False)
    table = TableState.empty_two_seat()
    key = ZoneKey(P1, ZoneRole.HAND)
    table.zones[key].cards.append(card)
    table.cards_by_id[card.id] = card

    owner_view = redact(table, P1).zones[key].cards[0]
    opp_view = redact(table, P2).zones[key].cards[0]

    assert owner_view.id == "f1"  # owner gets the full card
    assert _hidden(opp_view) and opp_view.card_id == "f1"  # opponent gets a stub with the same id


def _random_table(rng):
    table = TableState.empty_two_seat()
    for owner in (P1, P2):
        for idx in range(2):
            table.zones[ZoneKey(owner, ZoneRole.PROVINCE, idx)] = ProvinceZone(owner=owner)
    zone_keys = list(table.zones)
    deck_keys = list(table.decks)
    originals = {}
    placements = {}  # card_id -> ("zone", ZoneKey) | ("battlefield", None) | ("deck", DeckKey)

    for i in range(rng.randint(0, 18)):
        peekers = frozenset(s for s in (P1, P2) if rng.random() < 0.3)
        card = _card(
            f"c{i}",
            side=rng.choice([Side.FATE, Side.DYNASTY]),
            owner=rng.choice([P1, P2, None]),
            face_up=rng.random() < 0.5,
            shown=rng.random() < 0.3,
            peekers=peekers,
        )
        originals[card.id] = card
        table.cards_by_id[card.id] = card
        dest = rng.choice(["zone", "battlefield", "deck"])
        if dest == "zone":
            key = rng.choice(zone_keys)
            table.zones[key].cards.append(card)
            placements[card.id] = ("zone", key)
        elif dest == "battlefield":
            table.battlefield.cards.append(card)
            table.positions[card.id] = BoardPos(
                float(rng.randint(0, 300)), float(rng.randint(0, 300))
            )
            placements[card.id] = ("battlefield", None)
        else:
            key = rng.choice(deck_keys)
            table.decks[key].cards.append(card)
            placements[card.id] = ("deck", key)
    return table, originals, placements


def _expected_visible(card, viewer, location):
    kind, key = location
    if kind == "battlefield":
        default = card.face_up
    elif key.role in (
        ZoneRole.FATE_DISCARD,
        ZoneRole.FATE_BANISH,
        ZoneRole.DYNASTY_DISCARD,
        ZoneRole.DYNASTY_BANISH,
    ):
        default = True
    elif key.role is ZoneRole.HAND:
        default = card.owner == viewer
    else:
        default = card.face_up
    shown_to_opponent = card.shown and card.owner is not None and viewer == _opponent(card.owner)
    return default or shown_to_opponent or viewer in card.peekers


def _assert_projection(view, original, expected):
    if expected:
        assert view is original, "a visible card must pass through with full identity"
    else:
        assert isinstance(view, HiddenCard)
        assert view.card_id == original.id
        assert not hasattr(view, "name")


def test_no_identity_leaks_across_random_tables():
    rng = random.Random(20260624)
    for _ in range(400):
        table, originals, placements = _random_table(rng)
        for viewer in (P1, P2):
            snap = redact(table, viewer)

            for key, zone_view in snap.zones.items():
                for view in zone_view.cards:
                    card_id = view.id if isinstance(view, L5RCard) else view.card_id
                    original = originals[card_id]
                    expected = _expected_visible(original, viewer, ("zone", key))
                    _assert_projection(view, original, expected)

            for bview in snap.battlefield:
                view = bview.card
                card_id = view.id if isinstance(view, L5RCard) else view.card_id
                original = originals[card_id]
                expected = _expected_visible(original, viewer, ("battlefield", None))
                _assert_projection(view, original, expected)

            for key, deck_view in snap.decks.items():
                placed = [cid for cid, loc in placements.items() if loc == ("deck", key)]
                assert deck_view.count == len(placed)
                if deck_view.top is not None:
                    # only an exposed top is ever a full card, and only when flipped face up
                    assert deck_view.top.face_up
