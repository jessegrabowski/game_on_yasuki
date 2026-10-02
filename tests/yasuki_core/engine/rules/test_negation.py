from yasuki_core.engine.players import PlayerId, Rulebook
from yasuki_core.engine.rules.effects import (
    Ask,
    Bow,
    DiscardFromHand,
    Effect,
    Negated,
    Straighten,
    Then,
)
from yasuki_core.engine.rules.interrupts import forecast
from yasuki_core.engine.rules.negation import (
    action_provenance,
    negate_committed,
    strips_interrupt,
)
from yasuki_core.engine.rules.rulebook.cycle import CYCLE_PROXY
from yasuki_core.engine.rules.triggers import (
    choice_resolver,
    pay_costs,
    resolve_action_effects,
    resolve_delayed,
    resolve_effects,
)
from yasuki_core.engine.rules.turn.action_sequence import submit
from yasuki_core.engine.rules.turn.sequence import run_stack
from yasuki_core.engine.rules.turn.structure import END_OF_BATTLE, END_OF_TURN
from yasuki_core.engine.rules.vocabulary.decisions import DecisionResponse
from yasuki_core.engine.rules.vocabulary.modifiers import Duration, Negation
from yasuki_core.engine.rules.vocabulary.work import Provenance
from yasuki_core.game_pieces.cards import L5RCard
from yasuki_core.game_pieces.constants import Side
from yasuki_core.engine.table import ZoneKey, ZoneRole
from yasuki_core.game_pieces.prints import ActionPrint, HoldingPrint

from tests.yasuki_core.engine.builders import (
    fate_card,
    holding,
    put_in_play,
    register,
    two_seat_game,
)

FROM_NO_ACTION = Provenance()


def _card(game, print_class, name: str = "Plan") -> L5RCard:
    card = L5RCard.of(
        print_class, id=name, printed_id=name, name=name, side=Side.FATE, owner=PlayerId.P1
    )
    return register(game.table, card)


def _hand(game, seat, count):
    hand = game.table.zones[ZoneKey(seat, ZoneRole.HAND)]
    for index in range(count):
        hand.add(register(game.table, fate_card(f"{seat.name}-held-{index}", seat)))
    return hand


@choice_resolver("test_negation_cost_bow")
def _bow_the_source(game, source_id, chosen, seat):
    return [Bow(source_id)]


def test_an_effect_from_an_action_of_a_named_source_is_negated():
    game = two_seat_game()
    plan = _card(game, ActionPrint)
    game.ongoing.append(Negation("ring", END_OF_TURN, source_kind=ActionPrint))

    committed = negate_committed(game, Bow("farm"), Provenance(acting=plan.id))

    assert committed == Negated(Bow("farm"))


def test_a_source_must_match_every_criterion_the_negation_gives():
    game = two_seat_game()
    plan = _card(game, ActionPrint, "Plan")
    other = _card(game, ActionPrint, "Other")
    farm = _card(game, HoldingPrint, "Farm Plan")
    game.ongoing.append(Negation("ring", END_OF_TURN, source_kind=ActionPrint, source_title="Plan"))

    def committed(card):
        return negate_committed(game, Bow("farm"), Provenance(acting=card.id))

    assert committed(plan) == Negated(Bow("farm"))
    assert committed(other) == Bow("farm")
    assert committed(farm) == Bow("farm")


def test_a_rulebook_proxy_is_never_the_source_a_negation_names():
    game = two_seat_game()
    proxy = register(game.table, L5RCard(printed=CYCLE_PROXY, id="cycle", owner=PlayerId.P1))
    game.ongoing.append(Negation("ring", END_OF_TURN, source_title=CYCLE_PROXY.name))

    committed = negate_committed(game, Bow("farm"), Provenance(acting=proxy.id))

    assert committed == Bow("farm")


def test_a_negation_naming_a_source_leaves_an_effect_from_no_action():
    game = two_seat_game()
    game.ongoing.append(Negation("ring", END_OF_TURN, source_kind=ActionPrint))

    assert negate_committed(game, Bow("farm"), FROM_NO_ACTION) == Bow("farm")


def test_a_named_source_negates_what_its_action_defers():
    game = two_seat_game()
    plan = _card(game, ActionPrint)
    farm = put_in_play(game, holding("farm"))
    game.ongoing.append(Negation("ring", END_OF_TURN, source_kind=ActionPrint))

    resolve_action_effects(
        game, [Then((Bow(farm.id),))], provenance=action_provenance(game, plan.id)
    )
    run_stack(game)

    assert not game.stack
    assert not farm.bowed


def test_a_named_source_negates_what_an_answer_in_its_action_produces():
    game = two_seat_game()
    plan = _card(game, ActionPrint)
    farm = put_in_play(game, holding("farm"))
    game.ongoing.append(Negation("ring", END_OF_TURN, source_kind=ActionPrint))

    asked = Ask(PlayerId.P1, "Bow it?", "test_negation_cost_bow", source_id=farm.id)
    resolve_action_effects(game, [asked], provenance=action_provenance(game, plan.id))
    submit(game, DecisionResponse(()))

    assert not farm.bowed


def test_the_interrupt_step_does_not_offer_an_effect_a_negation_will_negate():
    game = two_seat_game()
    plan = _card(game, ActionPrint)
    game.ongoing.append(Negation("ring", END_OF_TURN, source_kind=ActionPrint))

    assert forecast(game, (Bow("farm"),), Provenance(acting=plan.id)) == ()
    assert forecast(game, (Bow("farm"),)) == (Bow("farm"),)


def test_an_effect_must_be_of_the_kind_and_act_on_the_card_the_negation_names():
    game = two_seat_game()
    game.ongoing.append(Negation("ring", END_OF_TURN, effect_kind=Bow, subject_id="farm"))

    assert negate_committed(game, Bow("farm"), FROM_NO_ACTION) == Negated(Bow("farm"))
    assert negate_committed(game, Bow("other"), FROM_NO_ACTION) == Bow("other")
    assert negate_committed(game, Straighten("farm"), FROM_NO_ACTION) == Straighten("farm")


def test_a_once_negation_is_spent_by_the_first_effect_it_negates():
    game = two_seat_game()
    put_in_play(game, holding("farm"))
    game.ongoing.append(Negation("ring", END_OF_BATTLE, effect_kind=Bow, once=True))

    assert negate_committed(game, Bow("farm"), FROM_NO_ACTION) == Negated(Bow("farm"))
    assert negate_committed(game, Bow("farm"), FROM_NO_ACTION) == Bow("farm")


def test_a_once_negation_naming_a_source_negates_all_of_that_sources_first_action():
    game = two_seat_game()
    plan = _card(game, ActionPrint)
    farm = put_in_play(game, holding("farm"))
    mine = put_in_play(game, holding("mine"))
    game.ongoing.append(Negation("ring", END_OF_TURN, source_kind=ActionPrint, once=True))

    first = action_provenance(game, plan.id)
    resolve_action_effects(game, [Bow(farm.id), Bow(mine.id)], provenance=first)
    assert not farm.bowed
    assert not mine.bowed

    game.interrupts_offered = False
    second = action_provenance(game, plan.id)
    resolve_action_effects(game, [Bow(farm.id)], provenance=second)
    assert farm.bowed


def test_a_once_negation_an_action_spent_negates_what_that_action_defers():
    game = two_seat_game()
    plan = _card(game, ActionPrint)
    farm = put_in_play(game, holding("farm"))
    game.ongoing.append(Negation("ring", END_OF_TURN, source_kind=ActionPrint, once=True))

    provenance = action_provenance(game, plan.id)
    resolve_action_effects(game, [Then((Bow(farm.id),))], provenance=provenance)
    run_stack(game)

    assert not game.stack
    assert not farm.bowed


def test_the_interrupt_step_offers_the_effects_a_once_negation_will_not_reach():
    game = two_seat_game()
    game.ongoing.append(Negation("ring", END_OF_TURN, effect_kind=Bow, once=True))
    put_in_play(game, holding("farm"))
    put_in_play(game, holding("mine"))

    assert forecast(game, (Bow("farm"), Bow("mine"))) == (Bow("mine"),)
    assert len(game.ongoing) == 1


def test_an_effect_already_negated_spends_no_once_negation():
    game = two_seat_game()
    negation = Negation("ring", END_OF_TURN, effect_kind=Effect, once=True)
    game.ongoing.append(negation)

    committed = negate_committed(game, Negated(Bow("farm")), FROM_NO_ACTION)

    assert committed == Negated(Bow("farm"))
    assert game.ongoing == [negation]


def test_a_once_negation_stripping_an_interrupt_is_spent():
    game = two_seat_game()
    plan = _card(game, ActionPrint)
    put_in_play(game, holding("farm"))
    game.ongoing.append(
        Negation("ring", END_OF_TURN, source_kind=ActionPrint, effect_kind=Bow, once=True)
    )
    provenance = action_provenance(game, plan.id)

    assert strips_interrupt(game, Bow("farm"), provenance)
    assert not strips_interrupt(game, Bow("farm"), provenance)


def test_a_once_negation_of_bowing_waits_for_a_bow_that_would_happen():
    game = two_seat_game()
    farm = put_in_play(game, holding("farm"))
    farm.bow()
    negation = Negation("ring", END_OF_TURN, effect_kind=Bow, subject_id="farm", once=True)
    game.ongoing.append(negation)

    resolve_effects(game, [Bow("farm")])
    assert game.ongoing == [negation]

    farm.unbow()
    resolve_effects(game, [Bow("farm")])
    assert not farm.bowed
    assert game.ongoing == []


def test_a_once_negation_of_straightening_waits_for_a_straighten_that_would_happen():
    game = two_seat_game()
    farm = put_in_play(game, holding("farm"))
    negation = Negation("ring", END_OF_TURN, effect_kind=Straighten, subject_id="farm", once=True)
    game.ongoing.append(negation)

    resolve_effects(game, [Straighten("farm")])
    assert game.ongoing == [negation]

    farm.bow()
    resolve_effects(game, [Straighten("farm")])
    assert farm.bowed
    assert game.ongoing == []


def test_a_while_source_in_play_negation_ends_with_its_source():
    game = two_seat_game()
    game.ongoing.append(Negation("gone", Duration.WHILE_SOURCE_IN_PLAY, effect_kind=Bow))

    assert negate_committed(game, Bow("farm"), FROM_NO_ACTION) == Bow("farm")


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


def test_a_negated_discard_asks_nothing_and_discards_nothing():
    game = two_seat_game()
    hand = _hand(game, PlayerId.P1, 3)
    game.ongoing.append(Negation("any", END_OF_TURN, effect_kind=DiscardFromHand))

    resolve_effects(
        game, [DiscardFromHand(PlayerId.P1, 1, Rulebook.MAXIMUM_HAND_SIZE, PlayerId.P1)]
    )

    assert game.pending is None
    assert len(hand.cards) == 3


def test_a_strategys_random_discard_is_negated_with_its_other_effects():
    game = two_seat_game()
    plan = _card(game, ActionPrint)
    hand = _hand(game, PlayerId.P2, 3)
    game.ongoing.append(Negation("ring", END_OF_TURN, source_kind=ActionPrint))

    discard = DiscardFromHand(PlayerId.P2, 1, PlayerId.P1, None)
    resolve_action_effects(game, [discard], provenance=action_provenance(game, plan.id))

    assert len(hand.cards) == 3


def test_a_question_in_a_negated_action_is_still_asked():
    game = two_seat_game()
    plan = _card(game, ActionPrint)
    farm = put_in_play(game, holding("farm"))
    game.ongoing.append(Negation("ring", END_OF_TURN, source_kind=ActionPrint))

    asked = Ask(PlayerId.P1, "Bow it?", "test_negation_cost_bow", source_id=farm.id)
    resolve_action_effects(game, [asked], provenance=action_provenance(game, plan.id))

    assert game.pending is not None


def test_a_discard_paid_as_a_cost_is_not_negated():
    game = two_seat_game()
    hand = _hand(game, PlayerId.P1, 1)
    game.ongoing.append(Negation("any", END_OF_TURN, effect_kind=DiscardFromHand))

    pay_costs(game, [DiscardFromHand(PlayerId.P1, 1, PlayerId.P1, PlayerId.P1)])

    assert not hand.cards


def test_a_once_negation_of_discarding_waits_for_a_discard_that_would_happen():
    game = two_seat_game()
    negation = Negation("any", END_OF_TURN, effect_kind=DiscardFromHand, once=True)
    game.ongoing.append(negation)

    resolve_effects(game, [DiscardFromHand(PlayerId.P1, 1, PlayerId.P1, None)])

    assert game.ongoing == [negation]
