import pytest

from yasuki_core.engine.rules.turn.structure import Boundary, Moment, Phase, Turn
from yasuki_core.engine.rules.vocabulary.segments import Segment


@pytest.mark.parametrize(
    "moment, worded",
    [
        (Moment(Turn.CURRENT, Boundary.END), "at the end of the turn"),
        (Moment(Phase.ACTION, Boundary.BEGINNING), "at the beginning of the Action Phase"),
        (Moment(Segment.FIGHT, Boundary.END), "at the end of the Fight Segment"),
    ],
)
def test_a_moment_is_worded_the_way_a_card_prints_it(moment, worded):
    assert moment.describe() == worded


def test_a_moment_naming_a_stage_it_cannot_word_raises():
    """Every delayed effect renders through this, so a stage with no wording has to fail loudly
    rather than putting "None" in front of a player."""
    with pytest.raises(ValueError, match="no name for the stage"):
        Moment("dusk", Boundary.END).describe()
