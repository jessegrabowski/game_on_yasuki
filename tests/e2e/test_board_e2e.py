# Two-client board integration, driven through real browsers. Run with `pixi run test-e2e`
# (needs `pixi run e2e-setup` once for the browser). These pin the invariants the diff-engine
# rewrite must preserve: the local player always at the bottom with the opponent mirrored, and
# hidden information never reaching the wrong client. The tests seed a public, owner-less token to
# carry those invariants, but a token id only resolves once the table's creatable tokens are loaded,
# which happens via deck-load — so they deal a real two-seat deck and need the cards database.

import pytest

from conftest import (
    DECK_YAML,
    TOKEN_CARD_ID,
    _token_db_ready,
    create_room,
    join_room,
    send,
    send_intent,
)

pytestmark = pytest.mark.skipif(
    not _token_db_ready(), reason="cards database with creates data not available"
)

MIRROR_TOL = (
    0.12  # card size + grab offset shift the centre a little; a half-board flip clears this
)


def _card(page, card_id):
    return page.evaluate(
        """(cardId) => {
            const el = document.querySelector(`.board-card[data-card-id="${cardId}"]`);
            if (!el) return null;
            const d = el.dataset;
            return { name: d.name || '', hidden: d.hidden || '', bowed: d.bowed || '',
                     peeked: d.peeked || '' };
        }""",
        card_id,
    )


_FRACTION_JS = """(cardId) => {
  const board = document.getElementById('battlefield');
  const el = board && board.querySelector(`.board-card[data-card-id="${cardId}"]`);
  if (!el) return null;
  const b = board.getBoundingClientRect();
  const c = el.getBoundingClientRect();
  return { fx: (c.left + c.width / 2 - b.left) / b.width,
           fy: (c.top + c.height / 2 - b.top) / b.height };
}"""


def _fraction(page, card_id):
    return page.evaluate(_FRACTION_JS, card_id)


def _drag_to_fraction(page, card_id, fx, fy):
    target = page.evaluate(
        """({ cardId, fx, fy }) => {
            const board = document.getElementById('battlefield');
            const el = board.querySelector(`.board-card[data-card-id="${cardId}"]`);
            const b = board.getBoundingClientRect();
            const c = el.getBoundingClientRect();
            return { cx: c.left + c.width / 2, cy: c.top + c.height / 2,
                     tx: b.left + fx * b.width, ty: b.top + fy * b.height };
        }""",
        {"cardId": card_id, "fx": fx, "fy": fy},
    )
    page.mouse.move(target["cx"], target["cy"])
    page.mouse.down()
    page.mouse.move(target["tx"], target["ty"], steps=20)
    page.mouse.up()


def _wait_until_moved(observer, card_id, baseline_fy, timeout=5000):
    observer.wait_for_function(
        """([cardId, baseFy]) => {
            const board = document.getElementById('battlefield');
            const el = board && board.querySelector(`.board-card[data-card-id="${cardId}"]`);
            if (!el) return false;
            const b = board.getBoundingClientRect();
            const c = el.getBoundingClientRect();
            const fy = (c.top + c.height / 2 - b.top) / b.height;
            return Math.abs(fy - baseFy) > 0.02;
        }""",
        arg=[card_id, baseline_fy],
        timeout=timeout,
    )


def _wait_for_card(page, card_id, predicate, timeout=5000):
    # `predicate` is a JS expression over a card element `el` (e.g. "el.dataset.hidden === '1'").
    page.wait_for_function(
        '(id) => { const el = document.querySelector(`.board-card[data-card-id="${id}"]`);'
        f" return !!el && ({predicate}); }}",
        arg=card_id,
        timeout=timeout,
    )


def _open_two_players(new_player, p1_view=None, p2_view=None):
    p1 = new_player(p1_view or {"width": 1280, "height": 800})
    room_id = create_room(p1)
    p2 = new_player(p2_view or {"width": 1280, "height": 800})
    join_room(p2, room_id)
    assert p1.get_attribute("#boardStage", "data-viewer-seat") == "P1"
    assert p2.get_attribute("#boardStage", "data-viewer-seat") == "P2"
    return p1, p2, room_id


def _deal_two_players(new_player, p1_view=None, p2_view=None):
    # Seat two players and deal a real two-seat table: each loads the same minimal deck and readies
    # (not solo), so the server deals once both seats are ready and populates the creatable tokens.
    p1, p2, room_id = _open_two_players(new_player, p1_view, p2_view)
    for page in (p1, p2):
        send(page, {"type": "LOAD_DECK", "room": room_id, "load_deck": {"yaml": DECK_YAML}})
        send(page, {"type": "READY", "room": room_id, "ready": {"ready": True}})
    for page in (p1, p2):
        page.wait_for_selector('[data-zone="province"] .zone-card[data-card-id]')
    return p1, p2, room_id


def _spawn_token(page, room_id, position=(0.4, 0.6)):
    # A spawned token lands as a public, face-up, owner-less battlefield card tagged data-token="1";
    # the server mints its `spawn-N` id. The dealt table also carries stronghold/pregame board-cards,
    # so the token must be selected by data-token, not "the first board-card".
    send_intent(
        page, room_id, {"op": "SPAWN_CARD", "token_id": TOKEN_CARD_ID, "position": list(position)}
    )
    page.wait_for_selector('.board-card[data-token="1"][data-card-id]')
    return page.get_attribute('.board-card[data-token="1"]', "data-card-id")


def _wait_for_token(page, card_id, timeout=5000):
    page.wait_for_selector(f'.board-card[data-card-id="{card_id}"]', timeout=timeout)


def test_each_player_sees_own_cards_low_and_the_opponent_mirrored(new_player):
    # Deliberately different window sizes, so the assertions can only pass if positions are stored in
    # a size-independent canonical frame and flipped per viewer.
    p1, p2, room_id = _deal_two_players(
        new_player, {"width": 1400, "height": 900}, {"width": 1000, "height": 1280}
    )
    card_id = _spawn_token(p1, room_id)
    _wait_for_token(p2, card_id)

    # P1 drags the card into its own lower half, kept clear of the province row that lines the bottom
    # edge of the dealt table (a drop onto a province is a zone move the server rejects, not a slide).
    p2_seed = _fraction(p2, card_id)
    _drag_to_fraction(p1, card_id, 0.4, 0.72)
    _wait_until_moved(p2, card_id, p2_seed["fy"])

    p1_view = _fraction(p1, card_id)
    p2_view = _fraction(p2, card_id)
    assert p1_view["fy"] > 0.5, "placer sees its own card on its own (bottom) side"
    assert p2_view["fy"] < 0.5, "opponent sees the same card on the opposite (top) side"
    assert abs(p2_view["fx"] - (1 - p1_view["fx"])) < MIRROR_TOL
    assert abs(p2_view["fy"] - (1 - p1_view["fy"])) < MIRROR_TOL

    # P2 drags it to ITS own lower half — exercises P2's view→canonical send transform.
    p1_seed = _fraction(p1, card_id)
    _drag_to_fraction(p2, card_id, 0.3, 0.72)
    _wait_until_moved(p1, card_id, p1_seed["fy"])

    p1_view = _fraction(p1, card_id)
    p2_view = _fraction(p2, card_id)
    assert p2_view["fy"] > 0.5, "mover sees its own card on its own (bottom) side"
    assert p1_view["fy"] < 0.5, "opponent sees the same card on the opposite (top) side"
    assert abs(p1_view["fx"] - (1 - p2_view["fx"])) < MIRROR_TOL
    assert abs(p1_view["fy"] - (1 - p2_view["fy"])) < MIRROR_TOL


def test_a_face_down_card_is_hidden_from_the_opponent_until_its_owner_peeks(new_player):
    p1, p2, room_id = _deal_two_players(new_player)
    card_id = _spawn_token(p1, room_id)
    _wait_for_token(p2, card_id)

    # Spawned face-up: both players read its identity.
    token_name = _card(p1, card_id)["name"]
    assert token_name, "the public token spawns face-up with a readable name"
    assert _card(p2, card_id)["name"] == token_name

    # Flipped face-down, the identity vanishes from BOTH views (face-down is symmetric) and the name
    # never reaches the opponent's bytes at all.
    send_intent(p1, room_id, {"op": "FLIP", "card_ids": [card_id]})
    _wait_for_card(p2, card_id, "el.dataset.hidden === '1'")
    assert _card(p1, card_id)["name"] == ""
    assert _card(p2, card_id)["name"] == ""
    assert token_name not in p2.inner_html("#battlefield")

    # The owner peeks: the front returns for the peeker only; the opponent stays blind.
    send_intent(p1, room_id, {"op": "PEEK", "card_id": card_id})
    _wait_for_card(p1, card_id, f"el.dataset.name === '{token_name}'")
    assert _card(p1, card_id)["peeked"] == "1"
    assert _card(p2, card_id)["name"] == ""
    assert token_name not in p2.inner_html("#battlefield")


def test_a_flag_change_propagates_to_the_opponents_view(new_player):
    p1, p2, room_id = _deal_two_players(new_player)
    card_id = _spawn_token(p1, room_id)
    _wait_for_token(p2, card_id)

    send_intent(p1, room_id, {"op": "BOW", "card_ids": [card_id]})
    _wait_for_card(p2, card_id, "el.classList.contains('bowed')")
    assert _card(p2, card_id)["bowed"] == "1"


# One stack-offset (ATTACH_STACK_OFFSET in board.js): the pixels a province-attached card fans inboard
# of its slot.
_ATTACH_OFFSET = 24

_PROVINCE_ANCHOR_JS = """(cardId) => {
  const card = document.querySelector(`.board-card[data-card-id="${cardId}"]`);
  const slot = document.querySelector('#selfTableau .province[data-idx="0"]');
  if (!card || !slot) return null;
  const c = card.getBoundingClientRect();
  const s = slot.getBoundingClientRect();
  return { cardTop: c.top, cardLeft: c.left, cardCx: c.left + c.width / 2,
           slotTop: s.top, slotLeft: s.left, slotCx: s.left + s.width / 2 };
}"""


def test_a_card_attached_to_a_province_anchors_on_its_slot(new_player):
    # Province attachment must actually reposition the card onto its province slot — behind it, fanned
    # inboard so its title reads — not merely record the relationship.
    p1, _p2, room_id = _open_two_players(new_player)
    _send_intent(p1, room_id, {"op": "CREATE_PROVINCE"})
    p1.wait_for_selector('#selfTableau .province[data-idx="0"]')
    # Spawn well away from the province so a successful anchor can only be the attach repositioning it.
    _spawn_card(p1, room_id, name="Fortification", position=(0.3, 0.3))
    card_id = _first_card_id(p1)

    _send_intent(
        p1,
        room_id,
        {
            "op": "ATTACH",
            "card_id": card_id,
            "to": {"kind": "zone", "zone": {"owner": "P1", "role": "province", "idx": 0}},
        },
    )

    # The card re-anchors: its horizontal centre lands on the province slot's column.
    p1.wait_for_function(
        """(cardId) => {
            const card = document.querySelector(`.board-card[data-card-id="${cardId}"]`);
            const slot = document.querySelector('#selfTableau .province[data-idx="0"]');
            if (!card || !slot) return false;
            const c = card.getBoundingClientRect();
            const s = slot.getBoundingClientRect();
            return Math.abs((c.left + c.width / 2) - (s.left + s.width / 2)) < 3;
        }""",
        arg=card_id,
        timeout=5000,
    )

    r = p1.evaluate(_PROVINCE_ANCHOR_JS, card_id)
    # Same column as the slot, one stack-offset above it (a bottom-lining own province fans up), so the
    # card draws behind the province with its title clear.
    assert abs(r["cardLeft"] - r["slotLeft"]) < 3
    assert abs(r["cardTop"] - (r["slotTop"] - _ATTACH_OFFSET)) < 3
    assert p1.get_attribute(f'.board-card[data-card-id="{card_id}"]', "data-attached") == "1"


def _card_id_by_name(page, name):
    return page.evaluate(
        """(name) => {
            const el = [...document.querySelectorAll('.board-card')].find((e) => e.dataset.name === name);
            return el ? el.dataset.cardId : null;
        }""",
        name,
    )


def test_a_branched_attachment_tower_gives_every_card_its_own_rung(new_player):
    # Host with two items, one of which carries a follower: the four cards must occupy four distinct
    # rungs. The old per-parent offset put the follower and the second item on the same rung.
    p1, _p2, room_id = _open_two_players(new_player)
    for name in ("Host", "ItemA", "ItemB", "Follower"):
        _spawn_card(p1, room_id, name=name, position=(0.5, 0.5))
    p1.wait_for_function(
        "() => document.querySelectorAll('.board-card[data-card-id]').length === 4"
    )

    host = _card_id_by_name(p1, "Host")
    item_a = _card_id_by_name(p1, "ItemA")
    item_b = _card_id_by_name(p1, "ItemB")
    follower = _card_id_by_name(p1, "Follower")

    def attach(child, parent):
        _send_intent(
            p1,
            room_id,
            {"op": "ATTACH", "card_id": child, "to": {"kind": "card", "card_id": parent}},
        )

    attach(item_a, host)
    attach(item_b, host)
    attach(follower, item_a)

    ids = [host, item_a, item_b, follower]
    tops_js = """(ids) => ids.map((id) => {
        const el = document.querySelector(`.board-card[data-card-id="${id}"]`);
        return el ? Math.round(el.getBoundingClientRect().top) : null;
    })"""
    # Wait for the tower to settle (the three attaches each round-trip a snapshot), then assert the
    # rungs explicitly so the success criterion is a check, not just the wait not timing out.
    p1.wait_for_function(
        f"(ids) => {{ const t = ({tops_js})(ids);"
        " return t.every((v) => v !== null) && new Set(t).size === ids.length; }",
        arg=ids,
        timeout=5000,
    )
    tops = p1.evaluate(tops_js, ids)
    assert len(set(tops)) == len(ids), f"every card sits on its own rung, got {tops}"
