import pytest

from yasuki_core.engine.rules.state import BattleSegment, Segment
from yasuki_core.ruleset import Ruleset, SHATTERED_EMPIRE, normalize_clan


def test_normalize_clan_folds_case_suffix_and_surrounding_whitespace():
    for variant in ("Crab", "crab", "Crab Clan", "  Crab Clan  ", "CRAB CLAN"):
        assert normalize_clan(variant) == "crab"


def test_alignment_resolves_variants_and_the_naga_akasha_alias():
    assert SHATTERED_EMPIRE.alignment("Crane Clan ") == "crane"
    assert SHATTERED_EMPIRE.alignment("Naga") == "akasha"
    assert SHATTERED_EMPIRE.alignment("Akasha") == "akasha"


def test_alignment_is_none_for_a_non_alignment_clan():
    assert SHATTERED_EMPIRE.alignment("Fox") is None
    assert SHATTERED_EMPIRE.alignment("Unaligned") is None


def test_the_live_ruleset_names_every_segment_it_walks():
    """The sequence and the names are separate fields on one arc, so they can disagree. An arc that
    walks a segment it cannot name reaches the prompt box and raises there instead."""
    live = SHATTERED_EMPIRE

    assert set(live.attack_segments) == set(live.segment_names)
    assert all(live.segment_name(segment) for segment in live.attack_segments)
    assert set(live.battle_segments) == set(live.battle_segment_names)
    assert all(live.battle_segment_name(segment) for segment in live.battle_segments)


def test_the_live_ruleset_walks_the_crs_whole_battle_sequence():
    """The CR's Battle Sequence has four entries and only the first two are Action Rounds, so the
    sequence cannot be read off what opens a round — a player shown the battle's shape has to be
    shown the two it passes through without being asked anything."""
    assert SHATTERED_EMPIRE.battle_segments == (
        BattleSegment.ENGAGE,
        BattleSegment.COMBAT,
        BattleSegment.RESOLUTION,
        BattleSegment.AFTER_RESOLUTION,
    )


def test_an_arc_names_its_own_battle_segments():
    """A battle's own sequence is arc config like the Attack Phase's, so an arc that walks only one
    of them names only that one and raises on the other."""
    arc = Ruleset(
        clan_alignments=frozenset(),
        battle_segments=(BattleSegment.COMBAT,),
        battle_segment_names={BattleSegment.COMBAT: "Melee"},
    )

    assert arc.battle_segment_name(BattleSegment.COMBAT) == "Melee"
    with pytest.raises(KeyError):
        arc.battle_segment_name(BattleSegment.ENGAGE)


def test_an_arc_walks_its_own_sequence_rather_than_the_enums_order():
    """The seam an older arc's Cavalry Maneuvers segment goes through: the order comes off the
    ruleset, so adding a member to `Segment` does not silently put it in every arc's sequence."""
    arc = Ruleset(
        clan_alignments=frozenset(),
        attack_segments=(Segment.DECLARATION, Segment.FIGHT),
        segment_names={Segment.DECLARATION: "Declaration", Segment.FIGHT: "Battles"},
    )

    assert arc.attack_segments == (Segment.DECLARATION, Segment.FIGHT)
    assert arc.segment_name(Segment.FIGHT) == "Battles"
    with pytest.raises(KeyError):
        arc.segment_name(Segment.MANEUVERS)
