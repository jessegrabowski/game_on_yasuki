import psycopg
import pytest

from yasuki_core.database import get_connection_string
from yasuki_core.decklist import parse_deck_yaml
from yasuki_core.game_pieces.factory import resolve_decklist
from yasuki_core.engine.players import PlayerId
from yasuki_core.game_pieces.dynasty import DynastyPersonality
from yasuki_core.game_pieces.fate import FateAction, FateAncestor
from yasuki_core.game_pieces.pregame import StrongholdCard, SenseiCard, WindCard
from yasuki_core.game_pieces.constants import Side, AttachmentType

# Records shaped like database.get_cards_by_names output: a card row plus an ordered `prints` list.
RECORDS = [
    {
        "card_id": "kuni_yori",
        "name": "Kuni Yori",
        "extended_title": "Kuni Yori",
        "types": ["Personality"],
        "decks": ["Dynasty"],
        "clans": ["Crab"],
        "keywords": ["Shadowlands", "Berserker"],
        "text": "Tainted.",
        "is_unique": True,
        "force": 4,
        "chi": 3,
        "personal_honor": 1,
        "honor_requirement": 2,
        "gold_cost": 8,
        "prints": [
            {"print_id": 1, "set_name": "Imperial Edition", "image_path": "sets/ie/kuni_yori.png"},
            {"print_id": 2, "set_name": "Pearl Edition", "image_path": "sets/pe/kuni_yori.png"},
        ],
    },
    {
        "card_id": "ambush",
        "name": "Ambush",
        "extended_title": "Ambush",
        "types": ["Strategy"],
        "decks": ["Fate"],
        "prints": [
            {"print_id": 10, "set_name": "Lotus Edition", "image_path": "sets/le/ambush.png"}
        ],
    },
    {
        "card_id": "kyuden_hida",
        "name": "Kyuden Hida",
        "extended_title": "Kyuden Hida",
        "types": ["Stronghold"],
        "decks": ["Pre-Game"],
        "starting_honor": 10,
        "gold_production": 8,
        "province_strength": 5,
        "prints": [
            {"print_id": 20, "set_name": "Imperial Edition", "image_path": "sets/ie/kh.png"}
        ],
    },
    {
        "card_id": "hida_sensei",
        "name": "Hida Sensei",
        "extended_title": "Hida Sensei",
        "types": ["Sensei"],
        "decks": ["Pre-Game"],
        "starting_honor": 5,
        "gold_production": -1,
        "province_strength": 1,
        "prints": [
            {"print_id": 30, "set_name": "Hidden Emperor", "image_path": "sets/he/sensei.png"}
        ],
    },
    {
        "card_id": "egg_of_pan_ku",
        "name": "The Egg of P'an Ku",
        "extended_title": "The Egg of P'an Ku",
        "types": ["Item"],
        "decks": ["Fate"],
        "focus": 2,
        "gold_cost": 7,
        "prints": [{"print_id": 60, "set_name": "Gold Edition", "image_path": "sets/ge/egg.png"}],
    },
    {
        "card_id": "ancestral_blade",
        "name": "Ancestral Blade",
        "extended_title": "Ancestral Blade",
        "types": ["Ancestor"],
        "decks": ["Fate"],
        "prints": [{"print_id": 50, "set_name": "Gold Edition", "image_path": "sets/ge/blade.png"}],
    },
    {
        "card_id": "the_wind_of_honor",
        "name": "The Wind of Honor",
        "extended_title": "The Wind of Honor",
        "types": ["Wind"],
        "decks": ["Pre-Game"],
        "prints": [
            {"print_id": 40, "set_name": "Hidden Emperor", "image_path": "sets/he/wind.png"}
        ],
    },
]

# A double-faced (flip) stronghold: the front links its back, which is a separate non-returned row.
FLIP_FRONT = {
    "card_id": "kyuden_kuni",
    "name": "Kyuden Kuni",
    "extended_title": "Kyuden Kuni",
    "types": ["Stronghold"],
    "decks": ["Pre-Game"],
    "starting_honor": 12,
    "back_card_id": "kyuden_kuni__back",
    "prints": [{"print_id": 70, "set_name": "Gates of Chaos", "image_path": "sets/goc/kk_a.png"}],
}
FLIP_BACK = {
    "card_id": "kyuden_kuni__back",
    "name": "Kyuden Kuni, Defiled",
    "extended_title": "Kyuden Kuni, Defiled",
    "types": ["Stronghold"],
    "decks": ["Pre-Game"],
    "starting_honor": 8,
    "prints": [{"print_id": 71, "set_name": "Gates of Chaos", "image_path": "sets/goc/kk_b.png"}],
}

DECK = """\
name: Crab
Pre-Game:
  - Kyuden Hida [Imperial Edition]
  - Hida Sensei
  - The Wind of Honor
Dynasty:
  - 2x Kuni Yori [Pearl Edition]
Fate:
  - Ambush
"""


def _resolve(yaml=DECK, owner=PlayerId.P1):
    return resolve_decklist(parse_deck_yaml(yaml), RECORDS, owner)


def test_each_section_resolves_to_the_right_subclass():
    r = _resolve()
    assert [type(c) for c in r.pre_game] == [StrongholdCard, SenseiCard, WindCard]
    assert all(isinstance(c, DynastyPersonality) for c in r.dynasty)
    assert all(isinstance(c, FateAction) for c in r.fate)


def test_ancestor_in_the_fate_section_resolves_to_a_fate_ancestor():
    r = resolve_decklist(
        parse_deck_yaml("name: T\nFate:\n  - Ancestral Blade"), RECORDS, PlayerId.P1
    )
    assert isinstance(r.fate[0], FateAncestor)
    assert r.fate[0].side is Side.FATE


def test_card_sides_follow_their_section():
    r = _resolve()
    assert r.dynasty[0].side is Side.DYNASTY
    assert r.fate[0].side is Side.FATE
    assert r.pre_game[0].side is Side.STRONGHOLD


def test_stronghold_and_sensei_carry_starting_honor_but_wind_does_not():
    stronghold, sensei, wind = _resolve().pre_game
    assert stronghold.starting_honor == 10
    assert sensei.starting_honor == 5
    assert not hasattr(wind, "starting_honor")


def test_personality_carries_its_combat_and_honor_stats():
    personality = _resolve().dynasty[0]
    assert (personality.force, personality.chi) == (4, 3)
    assert personality.personal_honor == 1
    assert personality.honor_requirement == 2
    assert personality.gold_cost == 8


def test_stronghold_carries_gold_production_and_province_strength():
    stronghold = _resolve().pre_game[0]
    assert stronghold.gold_production == 8
    assert stronghold.province_strength == 5


def test_sensei_carries_its_stat_modifiers():
    sensei = _resolve().pre_game[1]
    assert sensei.gold_production == -1
    assert sensei.province_strength == 1


def test_resolved_cards_carry_their_printed_id():
    resolved = _resolve()
    assert [c.printed_id for c in resolved.pre_game] == [
        "kyuden_hida",
        "hida_sensei",
        "the_wind_of_honor",
    ]
    assert resolved.dynasty[0].printed_id == "kuni_yori"
    assert resolved.fate[0].printed_id == "ambush"


def test_base_identity_and_unique_flag_are_carried():
    personality = _resolve().dynasty[0]
    assert personality.clan == "Crab"
    assert personality.keywords == ("Shadowlands", "Berserker")
    assert personality.text == "Tainted."
    assert personality.is_unique is True


def test_attachment_type_is_derived_from_the_card_type():
    r = resolve_decklist(
        parse_deck_yaml("name: T\nFate:\n  - The Egg of P'an Ku"), RECORDS, PlayerId.P1
    )
    assert r.fate[0].attachment_type is AttachmentType.ITEM


def test_count_expands_to_distinct_instances():
    dynasty = _resolve().dynasty
    assert len(dynasty) == 2
    assert dynasty[0].id != dynasty[1].id
    assert all(c.owner is PlayerId.P1 for c in dynasty)


def test_set_name_selects_the_matching_print():
    # The Pearl Edition entry, not the first (Imperial) print.
    assert _resolve().dynasty[0].image_front.as_posix() == "sets/pe/kuni_yori.png"


def test_entry_without_a_set_uses_the_first_print():
    r = resolve_decklist(parse_deck_yaml("name: T\nDynasty:\n  - Kuni Yori"), RECORDS, PlayerId.P1)
    assert r.dynasty[0].image_front.as_posix() == "sets/ie/kuni_yori.png"


def _db_available():
    try:
        conn = psycopg.connect(get_connection_string())
        conn.close()
        return True
    except psycopg.OperationalError:
        return False


@pytest.mark.skipif(not _db_available(), reason="PostgreSQL not available")
def test_art_swap_carries_the_donor_print_and_both_frames():
    # Building the swap classifies both prints' eras, which reads set release dates from the database.
    yaml = "name: T\nDynasty:\n  - Kuni Yori [Pearl Edition] {art: Ambush [Lotus Edition]}"
    card = resolve_decklist(parse_deck_yaml(yaml), RECORDS, PlayerId.P1).dynasty[0]
    # The recipient still renders its own printing; the swap rides alongside for the browser canvas.
    assert card.image_front.as_posix() == "sets/pe/kuni_yori.png"
    swap = card.art_swap
    assert swap["donor_img"] == "sets/le/ambush.png"
    assert swap["layout"] == "Personality"
    assert swap["donor_layout"] == "Strategy"
    assert swap["keywords"] == ["Shadowlands", "Berserker"]
    assert swap["era"] and swap["donor_era"]


def test_entry_without_art_has_no_art_swap():
    assert _resolve().dynasty[0].art_swap is None


def test_art_swap_is_dropped_when_the_donor_card_is_unknown():
    yaml = "name: T\nDynasty:\n  - Kuni Yori {art: Phantom Card}"
    card = resolve_decklist(parse_deck_yaml(yaml), RECORDS, PlayerId.P1).dynasty[0]
    assert card.art_swap is None


def test_art_swap_is_dropped_when_the_donor_print_has_no_image():
    records = [
        {
            "card_id": "recipient",
            "name": "Recipient",
            "extended_title": "Recipient",
            "types": ["Strategy"],
            "decks": ["Fate"],
            "prints": [{"print_id": 1, "set_name": "S", "image_path": "sets/r.png"}],
        },
        {
            "card_id": "donor",
            "name": "Donor",
            "extended_title": "Donor",
            "types": ["Strategy"],
            "decks": ["Fate"],
            "prints": [{"print_id": 2, "set_name": "S", "image_path": None}],
        },
    ]
    card = resolve_decklist(
        parse_deck_yaml("name: T\nFate:\n  - Recipient {art: Donor}"), records, PlayerId.P1
    ).fate[0]
    assert card.art_swap is None


def test_a_print_without_art_yields_no_front_image():
    record = {
        "card_id": "no_art",
        "name": "No Art",
        "extended_title": "No Art",
        "types": ["Strategy"],
        "decks": ["Fate"],
        "prints": [{"print_id": 1, "set_name": "S", "image_path": None}],
    }
    r = resolve_decklist(parse_deck_yaml("name: T\nFate:\n  - No Art"), [record], PlayerId.P1)
    assert r.fate[0].image_front is None


def test_unknown_name_is_reported_and_not_built():
    r = resolve_decklist(parse_deck_yaml("name: T\nFate:\n  - Ghost Card"), RECORDS, PlayerId.P1)
    assert r.unresolved == ["Ghost Card"]
    assert r.fate == []


def test_double_faced_card_nests_its_back_when_the_record_is_present():
    deck = parse_deck_yaml("name: T\nPre-Game:\n  - Kyuden Kuni")
    sh = resolve_decklist(deck, [FLIP_FRONT, FLIP_BACK], PlayerId.P1).pre_game[0]
    assert sh.back_card_id == "kyuden_kuni__back"
    assert isinstance(sh.back, StrongholdCard)
    # Each face is a distinct card, so it carries its own printed_id — the back dispatches to its own
    # effect handler, not the front's.
    assert sh.printed_id == "kyuden_kuni"
    assert sh.back.printed_id == "kyuden_kuni__back"
    assert sh.back.starting_honor == 8
    assert sh.back.image_front.as_posix() == "sets/goc/kk_b.png"
    assert sh.back.back is None  # the back face carries no further face


def test_double_faced_card_keeps_only_the_link_when_back_record_is_absent():
    deck = parse_deck_yaml("name: T\nPre-Game:\n  - Kyuden Kuni")
    sh = resolve_decklist(deck, [FLIP_FRONT], PlayerId.P1).pre_game[0]
    assert sh.back_card_id == "kyuden_kuni__back"
    assert sh.back is None


def test_double_faced_card_synthesises_its_back_from_the_front_print_back_art():
    front = {
        **FLIP_FRONT,
        "prints": [
            {
                "print_id": 70,
                "set_name": "Gates of Chaos",
                "image_path": "sets/goc/kk_a.png",
                "back_image_path": "sets/goc/kk_b.png",
            }
        ],
    }
    deck = parse_deck_yaml("name: T\nPre-Game:\n  - Kyuden Kuni")
    sh = resolve_decklist(deck, [front], PlayerId.P1).pre_game[0]
    assert sh.back is not None
    assert sh.back.id == "kyuden_kuni__back"
    assert sh.back.image_front.as_posix() == "sets/goc/kk_b.png"
    assert sh.back.back is None
    sh.flip_face()
    assert sh.active_face.image_front.as_posix() == "sets/goc/kk_b.png"


def test_two_seats_get_disjoint_card_ids():
    p1 = _resolve(owner=PlayerId.P1)
    p2 = _resolve(owner=PlayerId.P2)
    p1_ids = {c.id for c in p1.pre_game + p1.dynasty + p1.fate}
    p2_ids = {c.id for c in p2.pre_game + p2.dynasty + p2.fate}
    assert p1_ids.isdisjoint(p2_ids)
