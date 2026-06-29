# The right-click "Create <token>" path, driven through a real browser. Like test_board_e2e.py, this
# test deals a real deck, so it needs the cards database: the Create-token menu only exists once a
# card carries a `creates` list and the table's `creatable_tokens` are populated, and both come solely
# from the deck-load path, which queries PostgreSQL. So this test loads a real deck into a solo
# (goldfish) table and is skipped when the cards database isn't reachable.

import psycopg
import pytest

from yasuki_core.database import get_connection_string

from conftest import (
    DECK_YAML,
    TOKEN_CARD_ID,
    _token_db_ready,
    create_room,
    send,
    send_intent,
)

pytestmark = pytest.mark.skipif(
    not _token_db_ready(), reason="cards database with creates data not available"
)


def _token_display_name() -> str:
    with psycopg.connect(get_connection_string()) as conn:
        return conn.execute(
            "SELECT name FROM cards WHERE card_id = %s", (TOKEN_CARD_ID,)
        ).fetchone()[0]


def test_create_token_from_a_revealed_province_card(new_player):
    token_name = _token_display_name()
    page = new_player({"width": 1280, "height": 800})
    room_id = create_room(page)

    # Solo goldfish: load a deck, then ready up alone so the server deals a one-seat table.
    send(page, {"type": "LOAD_DECK", "room": room_id, "load_deck": {"yaml": DECK_YAML}})
    send(page, {"type": "READY", "room": room_id, "ready": {"ready": True, "solo": True}})

    # Setup deals every dynasty card face-down into a province (rendered as flow-positioned
    # `.zone-card`, not absolute `.board-card`). Grab one — they're all Weapon Artist.
    page.wait_for_selector('[data-zone="province"] .zone-card[data-card-id]')
    card_id = page.evaluate(
        """() => document
            .querySelector('[data-zone="province"] .zone-card[data-card-id]').dataset.cardId"""
    )

    # Reveal it: a face-up province card carries its `creates` list and offers the "Create" menu item.
    send_intent(page, room_id, {"op": "FLIP", "card_ids": [card_id]})
    page.wait_for_function(
        """(id) => {
            const el = document.querySelector(`[data-card-id="${id}"].zone-card`);
            return !!el && el.dataset.name === 'Weapon Artist' && el.dataset.faceUp === '1'
                && !!el.dataset.creates;
        }""",
        arg=card_id,
    )

    # Right-click the revealed card and pick "Create <token>" from the per-card menu.
    page.click(f'[data-card-id="{card_id}"].zone-card', button="right")
    page.wait_for_selector("ul.board-menu")
    page.click(f"ul.board-menu li:has-text('Create {token_name}')")

    # A fresh public token lands on the battlefield: a spawned token (data-token) named for the token.
    page.wait_for_selector(f'.board-card[data-token="1"][data-name="{token_name}"]')
    token_count = page.evaluate(
        """(name) => document.querySelectorAll(
            `.board-card[data-token="1"][data-name="${name}"]`).length""",
        token_name,
    )
    assert token_count == 1, "exactly one token created from the single menu click"
