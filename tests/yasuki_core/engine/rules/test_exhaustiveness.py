import ast
import inspect
import textwrap
import typing

import pytest

from yasuki_core.engine.rules import flow, log
from yasuki_core.engine.rules.actions import Action
from yasuki_core.engine.rules.decisions import DecisionRequest
from yasuki_core.engine.rules.log import GameInput
from yasuki_core.engine.rules.work import WorkItem


def _union_members(union) -> set[str]:
    """The concrete member names of a closed union, whether written as ``A | B`` or as an ABC with
    one subclass per member."""
    args = typing.get_args(union)
    if args:
        return {arg.__name__ for arg in args}
    return {subclass.__name__ for subclass in union.__subclasses__()}


def _dispatched_names(dispatcher) -> set[str]:
    """The class names a function's ``match`` statement has a ``case`` pattern for.

    Reads the source rather than calling the dispatcher with one instance per member: these
    dispatchers commit real engine work — recruiting a card, advancing a phase — so exercising them
    would need a bespoke fixture per member and would assert far more than coverage.
    """
    tree = ast.parse(textwrap.dedent(inspect.getsource(dispatcher)))
    return {
        # last segment, so `case work.ResolveRecruit()` reads the same as `case ResolveRecruit()`
        ast.unparse(node.pattern.cls).rsplit(".", 1)[-1]
        for node in ast.walk(tree)
        if isinstance(node, ast.match_case) and isinstance(node.pattern, ast.MatchClass)
    }


# The dispatchers that are exhaustive *by contract* — every member of their union must have a case
# — paired with the union they dispatch. Two match statements are deliberately absent:
#
#   flow.cancel     partial by design. Only ChoosePayment and ChooseInvestAmount are cancellable;
#                   every other decision must raise. Adding it here would assert the opposite.
#   log._decode_action  dispatches on a string kind rather than a type, so there is no case pattern
#                   to read. The round-trip test in test_log.py covers it end to end.
DISPATCH_SITES = [
    pytest.param(WorkItem, flow._resolve, id="WorkItem/_resolve"),
    pytest.param(DecisionRequest, flow.submit, id="DecisionRequest/submit"),
    pytest.param(Action, flow.perform, id="Action/perform"),
    pytest.param(Action, log._encode_action, id="Action/_encode_action"),
    pytest.param(GameInput, log._apply, id="GameInput/_apply"),
]


@pytest.mark.parametrize("union, dispatcher", DISPATCH_SITES)
def test_dispatch_handles_every_union_member(union, dispatcher):
    assert _union_members(union) - _dispatched_names(dispatcher) == set()


@pytest.mark.parametrize("union, dispatcher", DISPATCH_SITES)
def test_dispatch_names_no_type_outside_its_union(union, dispatcher):
    # A case for a type the union no longer contains is dead code the linter cannot see.
    assert _dispatched_names(dispatcher) - _union_members(union) == set()


def test_the_helper_notices_a_missing_case():
    # Guards the two tests above: a helper that silently found nothing would pass them vacuously.
    def _incomplete(entry: GameInput) -> None:
        match entry:
            case log.Act():
                pass

    assert _union_members(GameInput) - _dispatched_names(_incomplete) == {"Answer", "Cancel"}
