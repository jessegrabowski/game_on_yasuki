from yasuki_core.engine.players import PlayerId
from yasuki_core.engine.rules.effects import Ask, Bow, Negated, Straighten
from yasuki_core.engine.rules.negation import negate_committed, negate_from
from yasuki_core.engine.rules.rulebook.cycle import CYCLE_PROXY
from yasuki_core.engine.rules.triggers import (
    choice_resolver,
    pay_costs,
    resolve_action_effects,
    resolve_delayed,
    resolve_effects,
)
from yasuki_core.engine.rules.turn.action_sequence import submit
from yasuki_core.engine.rules.turn.structure import END_OF_BATTLE, END_OF_TURN
from yasuki_core.engine.rules.vocabulary.decisions import DecisionResponse
from yasuki_core.engine.rules.vocabulary.modifiers import Duration, Negation
from yasuki_core.game_pieces.cards import L5RCard
from yasuki_core.game_pieces.constants import Side
from yasuki_core.game_pieces.prints import ActionPrint, HoldingPrint

from tests.yasuki_core.engine.builders import holding, put_in_play, two_seat_game


def _card(print_class, name: str = "Plan") -> L5RCard:
    return L5RCard.of(print_class, id=name, name=name, side=Side.FATE, owner=PlayerId.P1)


@choice_resolver("test_negation_cost_bow")
def _bow_the_source(game, source_id, chosen, seat):
    return [Bow(source_id)]


def test_effects_from_a_named_source_are_negated_as_they_are_handed_over():
    game = two_seat_game()
    game.ongoing.append(Negation("ring", END_OF_TURN, source_kind=ActionPrint))

    assert negate_from(game, _card(ActionPrint), [Bow("farm")]) == [Negated(Bow("farm"))]


def test_a_source_must_match_every_criterion_the_negation_gives():
    game = two_seat_game()
    game.ongoing.append(Negation("ring", END_OF_TURN, source_kind=ActionPrint, source_title="Plan"))

    assert negate_from(game, _card(ActionPrint, "Plan"), [Bow("farm")]) == [Negated(Bow("farm"))]
    assert negate_from(game, _card(ActionPrint, "Other"), [Bow("farm")]) == [Bow("farm")]
    assert negate_from(game, _card(HoldingPrint, "Plan"), [Bow("farm")]) == [Bow("farm")]


def test_a_rulebook_proxy_is_never_the_source_a_negation_names():
    game = two_seat_game()
    game.ongoing.append(Negation("ring", END_OF_TURN, source_title=CYCLE_PROXY.name))
    proxy = L5RCard(printed=CYCLE_PROXY, id="cycle", owner=PlayerId.P1)

    assert negate_from(game, proxy, [Bow("farm")]) == [Bow("farm")]


def test_a_negation_naming_a_source_does_not_negate_an_effect_as_it_commits():
    game = two_seat_game()
    game.ongoing.append(Negation("ring", END_OF_TURN, source_kind=ActionPrint))

    assert negate_committed(game, Bow("farm")) == Bow("farm")


def test_an_effect_must_be_of_the_kind_and_act_on_the_card_the_negation_names():
    game = two_seat_game()
    game.ongoing.append(Negation("ring", END_OF_TURN, effect_kind=Bow, subject_id="farm"))

    assert negate_committed(game, Bow("farm")) == Negated(Bow("farm"))
    assert negate_committed(game, Bow("other")) == Bow("other")
    assert negate_committed(game, Straighten("farm")) == Straighten("farm")


def test_a_once_negation_is_spent_by_the_first_effect_it_negates():
    game = two_seat_game()
    game.ongoing.append(Negation("ring", END_OF_BATTLE, effect_kind=Bow, once=True))

    assert negate_committed(game, Bow("farm")) == Negated(Bow("farm"))
    assert negate_committed(game, Bow("farm")) == Bow("farm")


def test_a_while_source_in_play_negation_ends_with_its_source():
    game = two_seat_game()
    game.ongoing.append(Negation("gone", Duration.WHILE_SOURCE_IN_PLAY, effect_kind=Bow))

    assert negate_committed(game, Bow("farm")) == Bow("farm")


def test_a_bow_is_negated_whatever_produces_it():
    game = two_seat_game()
    farm = put_in_play(game, holding("farm"))
    game.ongoing.append(Negation("ring", END_OF_TURN, effect_kind=Bow, subject_id="farm"))
    game.delayed = [(END_OF_BATTLE, Bow("farm"))]

    resolve_action_effects(game, [Bow("farm")])
    resolve_effects(game, [Bow("farm")])
    resolve_delayed(game, END_OF_BATTLE)

    assert not farm.bowed


def test_a_bow_paid_as_a_cost_is_no_effect_and_is_not_negated():
    game = two_seat_game()
    farm = put_in_play(game, holding("farm"))
    game.ongoing.append(Negation("ring", END_OF_TURN, effect_kind=Bow, subject_id="farm"))

    pay_costs(game, [Bow("farm")])

    assert farm.bowed


def test_a_cost_that_pauses_on_a_question_is_still_a_cost_once_answered():
    game = two_seat_game()
    farm = put_in_play(game, holding("farm"))
    game.ongoing.append(Negation("ring", END_OF_TURN, effect_kind=Bow, subject_id="farm"))

    pay_costs(game, [Ask(PlayerId.P1, "Pay?", "test_negation_cost_bow", source_id="farm")])
    submit(game, DecisionResponse(()))

    assert farm.bowed
