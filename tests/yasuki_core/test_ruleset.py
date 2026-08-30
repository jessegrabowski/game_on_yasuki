import pytest

from yasuki_core.engine.rules.state import Segment
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
