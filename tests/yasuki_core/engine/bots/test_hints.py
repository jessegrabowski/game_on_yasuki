import pytest

from yasuki_core.engine.bots.hints import (
    ABILITY_HINTS,
    AbilityHint,
    optional_cost_answer,
    register_ability_hint,
)
from yasuki_core.engine.rules import cards  # noqa: F401
from yasuki_core.engine.rules.triggers import CHOICE_RESOLVERS


def test_every_resolver_a_hint_answers_is_one_a_card_registers():
    """A hint keyed on a misspelled resolver is never consulted and never errors, so the policy
    silently stops answering the cost — the same silent death registration_audit guards printed
    ids against."""
    claimed = {
        resolver for hint in ABILITY_HINTS.values() for resolver in hint.optional_cost_answers
    }

    assert claimed  # a subset check against an empty set passes whatever is wrong
    assert claimed <= set(CHOICE_RESOLVERS)


def test_a_resolver_no_hint_claims_has_no_answer():
    # The policy falls through to its paying agent on None, so returning an answer here would have
    # it deciding a cost it has no model for.
    assert optional_cost_answer("cycle") is None


def test_a_second_card_claiming_a_resolver_is_refused():
    """One resolver names one card's optional cost, so a second claim is a typo in one of them.
    Silently answering the first card's cost for the second is the failure being prevented."""
    hint = AbilityHint(
        worth_activating=lambda view, card: False,
        optional_cost_answers={"modest_farm_straighten": lambda view, request: False},
    )

    with pytest.raises(ValueError, match="already has an optional cost answer"):
        register_ability_hint("a_second_farm", hint)

    assert "a_second_farm" not in ABILITY_HINTS  # a refused registration records neither half
