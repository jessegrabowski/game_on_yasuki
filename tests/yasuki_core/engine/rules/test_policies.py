import random

import pytest

from yasuki_core.engine.players import PlayerId
from yasuki_core.engine.rules.actions import DynastyDiscard, Legacy, Pass
from yasuki_core.engine.rules.policies import PassPolicy, RandomPolicy
from yasuki_core.engine.session import EngineSession

from tests.yasuki_core.engine.builders import dealt_table

ACTIONS = [Legacy(), Pass(), DynastyDiscard("card-1")]


def _draws(policy, view, count):
    return [policy.choose(view, ACTIONS) for _ in range(count)]


def _view():
    session = EngineSession.start(dealt_table(), PlayerId.P1, seed=1)
    return session.project(PlayerId.P1)


def test_pass_policy_passes_even_when_offered_more():
    assert PassPolicy().choose(_view(), ACTIONS) == Pass()


def test_pass_policy_takes_what_it_can_when_passing_is_not_offered():
    # legal_actions withholds Pass in states where it is illegal; a policy that returned None or
    # raised there would stall the driver rather than the game.
    only = [DynastyDiscard("card-1")]

    assert PassPolicy().choose(_view(), only) == DynastyDiscard("card-1")


def test_random_policy_only_ever_returns_an_offered_action():
    policy = RandomPolicy(random.Random(7))
    view = _view()

    assert all(policy.choose(view, ACTIONS) in ACTIONS for _ in range(50))


def test_random_policy_with_the_same_seed_makes_the_same_choices():
    # The determinism the whole simulation harness rests on: same seed, same game.
    view = _view()
    # One policy drawing twenty times, not twenty policies drawing once — otherwise every draw is
    # the rng's first and the comparison holds for the wrong reason.
    first = _draws(RandomPolicy(random.Random(3)), view, 20)
    second = _draws(RandomPolicy(random.Random(3)), view, 20)

    assert first == second
    assert len(set(first)) > 1


def test_random_policy_with_different_seeds_diverges():
    # Guards against a policy that ignores its rng and looks deterministic for the wrong reason.
    view = _view()
    one = _draws(RandomPolicy(random.Random(1)), view, 20)
    two = _draws(RandomPolicy(random.Random(2)), view, 20)

    assert one != two


def test_random_policy_does_not_disturb_the_global_random_stream():
    # A policy reaching for the module-level rng would make every other seeded thing in the process
    # depend on how many choices it happened to make.
    random.seed(99)
    expected = [random.random() for _ in range(3)]
    random.seed(99)
    policy = RandomPolicy(random.Random(5))
    for _ in range(10):
        policy.choose(_view(), ACTIONS)

    assert [random.random() for _ in range(3)] == expected


@pytest.mark.parametrize("policy", [PassPolicy(), RandomPolicy(random.Random(0))])
def test_a_policy_never_invents_an_action(policy):
    view = _view()

    assert policy.choose(view, ACTIONS) in ACTIONS
