import ast
import pathlib

import pytest

from yasuki_core.engine.rules.turn import structure
from yasuki_core.engine.rules.turn.structure import Boundary, Moment, Phase, Segment, Turn


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


def test_the_turn_vocabulary_is_a_leaf():
    # Everything that reads a Phase or a Moment imports this, including modules the turn machine
    # imports in turn. One edge back into the rules layer closes that loop, and it is what lets
    # ruleset.py name a segment without pulling in numpy and TableState.
    source = pathlib.Path(structure.__file__).read_text(encoding="utf-8")
    imported = {
        node.module
        for node in ast.walk(ast.parse(source))
        if isinstance(node, ast.ImportFrom) and node.module and ".rules." in f"{node.module}."
    }

    assert imported == {"yasuki_core.engine.rules.vocabulary.actions"}
