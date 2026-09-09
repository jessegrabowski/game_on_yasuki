from yasuki_core.engine.bots.hints import ABILITY_HINTS, optional_cost_answer
from yasuki_core.engine.rules import cards  # noqa: F401
from yasuki_core.engine.rules.triggers import CHOICE_RESOLVERS


def test_every_resolver_a_hint_answers_is_one_a_card_registers():
    """A hint keyed on a misspelled resolver is never consulted and never errors, so the policy
    silently stops answering the cost — the same silent death card_registry guards printed ids
    against."""
    claimed = {
        resolver for hint in ABILITY_HINTS.values() for resolver in hint.optional_cost_answers
    }

    assert claimed  # a subset check against an empty set passes whatever is wrong
    assert claimed <= set(CHOICE_RESOLVERS)


def test_a_resolver_no_hint_claims_has_no_answer():
    # The policy falls through to its paying agent on None, so returning an answer here would have
    # it deciding a cost it has no model for.
    assert optional_cost_answer("cycle") is None
