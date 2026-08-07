import pytest

from yasuki_core.engine.players import PlayerId
from yasuki_core.engine.rules.agents import AGENTS, AutoAgent, make_agent
from yasuki_core.engine.rules.decisions import DiscardToHandSize


def test_auto_agent_answers_with_the_shortest_accepting_prefix():
    request = DiscardToHandSize(PlayerId.P1, ("a", "b", "c"), count=2)
    response = AutoAgent().decide(request, view=None)
    assert request.accepts(response)
    assert response.choices == ("a", "b")


def test_auto_agent_handles_a_zero_count():
    request = DiscardToHandSize(PlayerId.P1, ("a", "b"), count=0)
    response = AutoAgent().decide(request, view=None)
    assert response.choices == ()
    assert request.accepts(response)


def test_every_agent_reports_a_name():
    """A run is named by its policy and its agent together, so the registry key and the agent's own
    name have to agree or a report would name a different agent than the one that played."""
    assert {name: make_agent(name).name for name in AGENTS} == {n: n for n in AGENTS}


def test_the_registry_covers_the_agents_that_ship():
    assert set(AGENTS) == {"auto", "paying"}


def test_an_agent_built_by_name_answers():
    request = DiscardToHandSize(PlayerId.P1, ("a", "b", "c"), count=2)

    response = make_agent("paying").decide(request, view=None)

    assert request.accepts(response)
    assert response.choices == ("a", "b")


def test_an_unknown_agent_name_says_what_is_available():
    with pytest.raises(KeyError, match="paying"):
        make_agent("clever")
