import pytest

from yasuki_core.engine.rules.board.counts_as import RULEBOOK, Asking
from yasuki_core.engine.rules.stats.checked import CONSIDERED_STATS, checked_stat
from yasuki_core.engine.rules.vocabulary import keywords
from yasuki_core.engine.rules.vocabulary.modifiers import Stat

from tests.yasuki_core.engine.builders import personality, put_in_play, two_seat_game

KIHO = frozenset({keywords.KIHO})


def _three_chi_for_a_kiho(game, card, stat, asking):
    if stat is Stat.CHI and keywords.KIHO in asking.keywords:
        return 3
    return None


@pytest.fixture
def game():
    CONSIDERED_STATS.make_register()("considered_probe", _three_chi_for_a_kiho)
    yield two_seat_game()
    CONSIDERED_STATS.pop("considered_probe")


def test_a_kiho_checking_chi_reads_the_considered_value(game):
    monk = put_in_play(game, personality("monk", printed_id="considered_probe", chi=0))
    strategy = put_in_play(game, personality("strategy"))

    assert checked_stat(game, monk, Stat.CHI, Asking.action(strategy, KIHO)) == 3


@pytest.mark.parametrize(
    ("stat", "asking_keywords", "printed"),
    [(Stat.CHI, frozenset(), 0), (Stat.FORCE, KIHO, 2)],
    ids=["chi for another action", "force for a kiho"],
)
def test_any_other_check_reads_the_effective_value(game, stat, asking_keywords, printed):
    monk = put_in_play(game, personality("monk", printed_id="considered_probe", force=2, chi=0))
    strategy = put_in_play(game, personality("strategy"))

    assert checked_stat(game, monk, stat, Asking.action(strategy, asking_keywords)) == printed


def test_the_rulebook_reads_the_effective_value(game):
    monk = put_in_play(game, personality("monk", printed_id="considered_probe", chi=0))

    assert checked_stat(game, monk, Stat.CHI, RULEBOOK) == 0
