import pytest

from yasuki_core.accounts import decks
from yasuki_core.accounts.decks import DeckCard

# Card records shaped like get_cards_by_names output — the contract the serializer resolves against.
RECORDS = [
    {"card_id": "kyuden_hida", "name": "Kyuden Hida", "types": ["Stronghold"], "clans": ["Crab"]},
    {
        "card_id": "hida_kisada",
        "name": "Hida Kisada",
        "extended_title": "Hida Kisada - Experienced",
        "types": ["Personality"],
        "clans": ["Crab"],
    },
    {"card_id": "kisada_alt", "name": "Kisada Alt", "types": ["Personality"], "clans": ["Crab"]},
    {"card_id": "ambush", "name": "Ambush", "types": ["Strategy"], "clans": []},
]
NAME_INDEX = decks.build_name_index(RECORDS)
RECORDS_BY_ID = {record["card_id"]: record for record in RECORDS}
KNOWN_IDS = set(RECORDS_BY_ID)

DECK_YAML = """\
name: Crab Beats
Pre-Game:
  - Kyuden Hida
Dynasty:
  - 3x Hida Kisada [Pearl Edition] {art: Kisada Alt [Gold]}
Fate:
  - 2x Ambush
"""


def test_name_index_keys_on_both_name_and_extended_title():
    assert NAME_INDEX["hida kisada"]["card_id"] == "hida_kisada"
    assert NAME_INDEX["hida kisada - experienced"]["card_id"] == "hida_kisada"


def test_resolve_assigns_ids_sides_and_denormalized_names():
    cards = decks.deck_from_yaml(DECK_YAML, NAME_INDEX)
    assert cards == [
        DeckCard("kyuden_hida", "Kyuden Hida", "pre_game", 1),
        DeckCard(
            "hida_kisada",
            "Hida Kisada - Experienced",  # extended title wins as the denormalized handle
            "dynasty",
            3,
            set_name="Pearl Edition",
            art_donor_card_id="kisada_alt",
            art_donor_set="Gold",
        ),
        DeckCard("ambush", "Ambush", "fate", 2),
    ]


def test_resolve_sums_identical_entries_into_one_row():
    yaml = "Dynasty:\n  - 2x Hida Kisada [Pearl Edition]\n  - 1x Hida Kisada [Pearl Edition]\n"
    cards = decks.deck_from_yaml(yaml, NAME_INDEX)
    assert cards == [
        DeckCard("hida_kisada", "Hida Kisada - Experienced", "dynasty", 3, set_name="Pearl Edition")
    ]


def test_resolve_keeps_an_art_swap_distinct_from_the_plain_card():
    yaml = "Dynasty:\n  - Hida Kisada\n  - Hida Kisada {art: Kisada Alt}\n"
    cards = decks.deck_from_yaml(yaml, NAME_INDEX)
    assert len(cards) == 2
    assert {card.art_donor_card_id for card in cards} == {None, "kisada_alt"}


def test_resolve_rejects_unknown_cards_and_donors_together():
    yaml = "Dynasty:\n  - Nonexistent Card\nFate:\n  - Ambush {art: Ghost Donor}\n"
    with pytest.raises(decks.UnknownCardError) as raised:
        decks.deck_from_yaml(yaml, NAME_INDEX)
    assert raised.value.unknown == ["Nonexistent Card", "Ghost Donor"]


def test_assert_card_ids_known_rejects_a_bogus_card_or_donor():
    decks.assert_card_ids_known(decks.deck_from_yaml(DECK_YAML, NAME_INDEX), KNOWN_IDS)
    with pytest.raises(decks.UnknownCardError) as raised:
        decks.assert_card_ids_known(
            [DeckCard("hida_kisada", "Hida Kisada", "dynasty", 1, art_donor_card_id="ghost")],
            KNOWN_IDS,
        )
    assert raised.value.unknown == ["ghost"]


def test_summarize_finds_stronghold_clan_and_side_counts():
    summary = decks.summarize(decks.deck_from_yaml(DECK_YAML, NAME_INDEX), RECORDS_BY_ID)
    assert summary == decks.DeckSummary(
        stronghold_card_id="kyuden_hida", clan="Crab", dynasty_count=3, fate_count=2
    )


def test_summarize_leaves_stronghold_and_clan_unset_without_one():
    cards = [DeckCard("ambush", "Ambush", "fate", 2)]
    summary = decks.summarize(cards, RECORDS_BY_ID)
    assert summary.stronghold_card_id is None and summary.clan is None


def test_rows_round_trip_preserves_every_field():
    cards = decks.deck_from_yaml(DECK_YAML, NAME_INDEX)
    rows = decks.to_rows(cards, deck_id=42)
    assert all(row["deck_id"] == 42 for row in rows)
    assert decks.from_rows(rows) == cards


def test_to_rows_persists_through_the_real_schema(accounts_conn):
    # Anchor the row dict's keys to the live deck_cards columns: the named-param insert raises if a
    # key drifts, which the in-memory round-trip above cannot catch.
    cards = decks.deck_from_yaml(DECK_YAML, NAME_INDEX)
    deck_id = _seed_deck(accounts_conn)
    with accounts_conn.cursor() as cur:
        for row in decks.to_rows(cards, deck_id):
            cur.execute(
                "INSERT INTO deck_cards (deck_id, card_id, card_name, set_name, side, quantity, "
                "art_donor_card_id, art_donor_set) VALUES (%(deck_id)s, %(card_id)s, %(card_name)s, "
                "%(set_name)s, %(side)s, %(quantity)s, %(art_donor_card_id)s, %(art_donor_set)s)",
                row,
            )
        cur.execute(
            "SELECT card_id, card_name, set_name, side, quantity, art_donor_card_id, art_donor_set "
            "FROM deck_cards WHERE deck_id = %s ORDER BY id",
            (deck_id,),
        )
        loaded = decks.from_rows(cur.fetchall())
    assert set(loaded) == set(cards)


def test_yaml_round_trip_preserves_cards_and_art_swaps():
    cards = decks.deck_from_yaml(DECK_YAML, NAME_INDEX)
    donor_names = {"kisada_alt": "Kisada Alt"}
    reparsed = decks.deck_from_yaml(decks.to_yaml(cards, donor_names=donor_names), NAME_INDEX)
    assert set(reparsed) == set(cards)


def test_orphan_card_ids_is_the_stored_minus_known_difference():
    assert decks.orphan_card_ids({"a", "b", "ghost"}, {"a", "b", "c"}) == {"ghost"}


def test_audit_flags_a_deliberately_orphaned_stored_card(accounts_conn):
    deck_id = _seed_deck(accounts_conn)
    _insert_card(accounts_conn, deck_id, "hida_kisada", "Hida Kisada")
    _insert_card(accounts_conn, deck_id, "ghost_card", "Forgotten Name")
    _insert_card(accounts_conn, deck_id, "ambush", "Ambush", art_donor="ghost_donor")

    stored = decks.stored_card_ids(accounts_conn)
    assert {"ghost_card", "ghost_donor"} <= stored
    assert decks.orphan_card_ids(stored, {"hida_kisada", "ambush"}) == {"ghost_card", "ghost_donor"}


def _seed_deck(conn) -> int:
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO users (google_sub, email_hmac, email_verified, display_name) "
            "VALUES ('g', %s, true, 'Ada') RETURNING id",
            (b"\x01" * 32,),
        )
        user_id = cur.fetchone()["id"]
        cur.execute(
            "INSERT INTO decks (slug, owner_id, name) VALUES ('crab', %s, 'Crab Beats') RETURNING id",
            (user_id,),
        )
        return cur.fetchone()["id"]


def _insert_card(conn, deck_id, card_id, card_name, *, art_donor=None):
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO deck_cards (deck_id, card_id, card_name, side, quantity, art_donor_card_id) "
            "VALUES (%s, %s, %s, 'dynasty', 1, %s)",
            (deck_id, card_id, card_name, art_donor),
        )
