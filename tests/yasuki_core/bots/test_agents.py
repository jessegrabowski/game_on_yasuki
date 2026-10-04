import pytest

from yasuki_core.engine.players import PlayerId, Rulebook
from yasuki_core.bots.agents import AGENTS, AutoAgent, make_agent
from yasuki_core.engine.rules.vocabulary.decisions import (
    ChooseAbilityTarget,
    ArrangeCards,
    ChooseDiscard,
    ChooseDistribution,
    OneGroup,
    TotalAtMost,
)


def test_auto_agent_answers_with_the_shortest_accepting_prefix():
    request = ChooseDiscard(
        PlayerId.P1, ("a", "b", "c"), count=2, holder=PlayerId.P1, cause=Rulebook.MAXIMUM_HAND_SIZE
    )
    response = AutoAgent().decide(request, view=None)
    assert request.accepts(response)
    assert response.choices == ("a", "b")


def test_auto_agent_takes_as_many_targets_as_the_choice_asks():
    request = ChooseAbilityTarget(PlayerId.P1, ("a", "b", "c"), "spell", minimum=2, maximum=2)

    assert AutoAgent().decide(request, view=None).choices == ("a", "b")


def test_auto_agent_grows_an_answer_a_limit_narrows():
    # A prefix search would have offered ("a", "b"), which the total refuses. Growing through
    # selectable stops at the first set the request accepts.
    request = ChooseAbilityTarget(
        PlayerId.P1,
        ("a", "b", "c"),
        "spell",
        minimum=1,
        maximum=2,
        limits=(TotalAtMost((("a", 3), ("b", 3), ("c", 1)), 4),),
    )

    response = AutoAgent().decide(request, view=None)

    assert response.choices == ("a",)
    assert request.accepts(response)


def test_auto_agent_finds_a_pair_the_first_card_rules_out():
    # The heaviest card is offered first and reaches nothing: ("b", "c") is the only legal pair, so
    # an answer grown from "a" and never turned back would strand the bot.
    request = ChooseAbilityTarget(
        PlayerId.P1,
        ("a", "b", "c"),
        "spell",
        minimum=2,
        maximum=2,
        limits=(TotalAtMost((("a", 4), ("b", 2), ("c", 2)), 5),),
    )

    assert AutoAgent().decide(request, view=None).choices == ("b", "c")


def test_auto_agent_finds_a_pair_inside_one_group():
    request = ChooseAbilityTarget(
        PlayerId.P1,
        ("a", "b", "c"),
        "spell",
        minimum=2,
        maximum=2,
        limits=(OneGroup((("a",), ("b", "c"))),),
    )

    assert AutoAgent().decide(request, view=None).choices == ("b", "c")


def test_auto_agent_raises_only_when_no_set_satisfies_the_limits():
    # Two parts of one card each cannot seat a pair, so there is nothing to find and raising is the
    # answer. The engine withholds such a question; this covers the bot meeting one anyway.
    request = ChooseAbilityTarget(
        PlayerId.P1,
        ("a", "b"),
        "spell",
        minimum=2,
        maximum=2,
        limits=(OneGroup((("a",), ("b",))),),
    )

    with pytest.raises(ValueError, match="no auto-answer"):
        AutoAgent().decide(request, view=None)


def test_auto_agent_handles_a_zero_count():
    request = ChooseDiscard(
        PlayerId.P1, ("a", "b"), count=0, holder=PlayerId.P1, cause=Rulebook.MAXIMUM_HAND_SIZE
    )
    response = AutoAgent().decide(request, view=None)
    assert response.choices == ()
    assert request.accepts(response)


def test_auto_agent_heaps_a_division_onto_one_candidate():
    """A prefix of distinct candidates cannot name one twice, so a division of three among two would
    have no prefix that answers it. The agent would raise on a decision a player answers easily."""
    request = ChooseDistribution(
        PlayerId.P1, ("a", "b"), count=3, resolver="split", source_id="source"
    )

    response = AutoAgent().decide(request, view=None)

    assert request.accepts(response)
    assert response.choices == ("a", "a", "a")


def test_every_agent_reports_a_name():
    """A run is named by its policy and its agent together, so the registry key and the agent's own
    name have to agree or a report would name a different agent than the one that played."""
    assert {name: make_agent(name).name for name in AGENTS} == {n: n for n in AGENTS}


def test_the_registry_covers_the_agents_that_ship():
    assert set(AGENTS) == {"auto", "paying", "legacy"}


def test_an_agent_built_by_name_answers():
    request = ChooseDiscard(
        PlayerId.P1, ("a", "b", "c"), count=2, holder=PlayerId.P1, cause=Rulebook.MAXIMUM_HAND_SIZE
    )

    response = make_agent("paying").decide(request, view=None)

    assert request.accepts(response)
    assert response.choices == ("a", "b")


def test_an_unknown_agent_name_says_what_is_available():
    with pytest.raises(KeyError, match="paying"):
        make_agent("clever")


def test_auto_agent_keeps_the_order_it_was_shown():
    """The whole list as a prefix would place the cards back reversed, so an ordering is answered
    with the order they already had."""
    request = ArrangeCards(PlayerId.P1, ("top", "mid", "low"), "r", None, to_bottom=False)
    response = AutoAgent().decide(request, view=None)
    assert request.accepts(response)
    assert response.choices == ("low", "mid", "top")
