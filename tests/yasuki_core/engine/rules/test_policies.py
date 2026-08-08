import numpy as np
from numpy.random import default_rng

import pytest

from yasuki_core.engine.players import PlayerId
from yasuki_core.engine.rules.actions import DynastyDiscard, Legacy, Pass
from yasuki_core.engine.rules.policies import (
    POLICIES,
    PassPolicy,
    RandomPolicy,
    make_policy,
)
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
    policy = RandomPolicy(default_rng(7))
    view = _view()

    assert all(policy.choose(view, ACTIONS) in ACTIONS for _ in range(50))


def test_random_policy_with_the_same_seed_makes_the_same_choices():
    # The determinism the whole simulation harness rests on: same seed, same game.
    view = _view()
    # One policy drawing twenty times, not twenty policies drawing once — otherwise every draw is
    # the rng's first and the comparison holds for the wrong reason.
    first = _draws(RandomPolicy(default_rng(3)), view, 20)
    second = _draws(RandomPolicy(default_rng(3)), view, 20)

    assert first == second
    assert len(set(first)) > 1


def test_random_policy_with_different_seeds_diverges():
    # Guards against a policy that ignores its rng and looks deterministic for the wrong reason.
    view = _view()
    one = _draws(RandomPolicy(default_rng(1)), view, 20)
    two = _draws(RandomPolicy(default_rng(2)), view, 20)

    assert one != two


@pytest.mark.parametrize("rng", [default_rng(5), None], ids=["given", "self-seeded"])
def test_random_policy_does_not_disturb_the_global_random_stream(rng):
    # A policy reaching for a module-level generator would make every other seeded thing in the
    # process depend on how many choices it happened to make. The self-seeded case is the one a
    # policy built by name takes, where reaching for the global stream is the tempting shortcut.
    np.random.seed(99)
    expected = [float(np.random.random()) for _ in range(3)]
    np.random.seed(99)
    policy = RandomPolicy(rng)
    for _ in range(10):
        policy.choose(_view(), ACTIONS)

    assert [float(np.random.random()) for _ in range(3)] == expected


@pytest.mark.parametrize("policy", [PassPolicy(), RandomPolicy(default_rng(0))])
def test_a_policy_never_invents_an_action(policy):
    view = _view()

    assert policy.choose(view, ACTIONS) in ACTIONS


def test_every_policy_reports_a_name():
    """A run's numbers describe a deck under a policy, so a result quoted without one cannot be
    compared. The registry key and the policy's own name have to agree, or a report would name a
    different policy than the one that played."""
    assert {name: make_policy(name).name for name in POLICIES} == {n: n for n in POLICIES}


def test_the_registry_covers_the_policies_that_ship():
    assert set(POLICIES) == {"pass", "random", "economic", "economic-legacy"}


def test_a_policy_built_by_name_chooses():
    assert make_policy("pass").choose(_view(), ACTIONS) == Pass()


def test_a_random_policy_seeds_itself_when_given_no_rng():
    """Built by name it has no run to draw from, so it must still choose rather than fail. Such a
    run is not reproducible — that needs the rng passed to the constructor."""
    view = _view()

    assert all(action in ACTIONS for action in _draws(RandomPolicy(), view, 20))


def test_an_unknown_policy_name_says_what_is_available():
    # A dashboard passing a stale name should read the fix off the error.
    with pytest.raises(KeyError, match="economic"):
        make_policy("greedy")
