from yasuki_core.engine.players import PlayerId
from yasuki_core.engine.rules.agents import AutoAgent
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
