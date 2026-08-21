import pathlib
import re

from tests.yasuki_core.engine.rules.card_modules import card_modules

# Anchored on this file rather than the working directory, so the suite reads the guide wherever
# pytest is run from.
GUIDE = pathlib.Path(__file__).parents[4] / "docs" / "contributing" / "adding_a_card.md"
PYTHON_FENCE = re.compile(r"^```python\n(.*?)^```", re.M | re.S)
# Lines a sample may carry that are not meant to be found in the tree: blank lines, whole-line
# comments, and any line carrying a "..." elision.
ELIDED = re.compile(r"^\s*(#|$)|\.\.\.")


def sample_lines() -> list[str]:
    return [
        line.rstrip()
        for block in PYTHON_FENCE.findall(GUIDE.read_text(encoding="utf-8"))
        for line in block.splitlines()
        if not ELIDED.search(line)
    ]


def test_every_code_sample_is_real_card_code():
    # A guide whose examples drift is worse than no guide: the reader copies something that no longer
    # compiles or no longer means what it says. Every non-elided line is quoted from a card module,
    # so a rename in the engine breaks this test rather than the reader's day.
    source = "\n".join(module.read_text(encoding="utf-8") for module in card_modules())
    invented = [line for line in sample_lines() if line.strip() not in source]

    assert invented == []


def test_the_guide_has_samples_to_check():
    # Guards the test above: a regex that matched nothing would pass it vacuously.
    assert len(sample_lines()) > 10
