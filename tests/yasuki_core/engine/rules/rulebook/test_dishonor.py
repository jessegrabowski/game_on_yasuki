from yasuki_core.engine.players import PlayerId, Rulebook
from yasuki_core.engine.rules.effects import Destroy, GrantModifier
from yasuki_core.engine.rules.triggers import resolve_action_effects, resolve_effects

# The engine's dispatcher is what registers the rulebook trigger, so these tests import that rather
# than the module itself: a dropped registration import fails here instead of only in play.
from yasuki_core.engine.rules.turn import action_sequence  # noqa: F401
from yasuki_core.engine.rules.vocabulary.actions import DeclareAttack
from yasuki_core.engine.rules.vocabulary.game_events import HonorChanged
from yasuki_core.engine.rules.vocabulary.modifiers import Duration, Stat

from tests.yasuki_core.engine.builders import holding, personality, put_in_play, two_seat_game
from tests.yasuki_core.engine.rules.test_interrupts import _honor_card

P1 = PlayerId.P1


def test_destroying_a_dishonorable_personality_costs_his_printed_personal_honor():
    game = two_seat_game()
    hero = put_in_play(game, personality("P1-p", personal_honor=2))
    hero.dishonor()

    resolve_effects(game, [Destroy(hero.id, PlayerId.P2)])

    assert game.table.seats[P1].honor == -2
    assert HonorChanged(P1, -2) in game.action_events


def test_an_honorable_personality_dies_for_free():
    game = two_seat_game()
    hero = put_in_play(game, personality("P1-p", personal_honor=2))

    resolve_effects(game, [Destroy(hero.id, PlayerId.P2)])

    assert game.table.seats[P1].honor == 0


def test_the_loss_reads_the_printed_value_not_the_capped_or_modified_one():
    game = two_seat_game()
    hero = put_in_play(game, personality("P1-p", personal_honor=3))
    hero.dishonor()

    resolve_effects(
        game,
        [
            GrantModifier(hero.id, hero.id, Stat.PERSONAL_HONOR, 4, Duration.UNTIL_END_OF_TURN),
            Destroy(hero.id, Rulebook.CHI_DEATH),
        ],
    )

    assert game.table.seats[P1].honor == -3


def test_a_printed_personal_honor_of_zero_raises_no_change():
    game = two_seat_game()
    hero = put_in_play(game, personality("P1-p", personal_honor=0))
    hero.dishonor()

    resolve_effects(game, [Destroy(hero.id, PlayerId.P2)])

    assert game.table.seats[P1].honor == 0
    assert not any(isinstance(event, HonorChanged) for event in game.action_events)


def test_the_loss_is_the_rulebooks_and_opens_no_honor_interrupt():
    # The death loss is a rulebook effect, never one of the action's own, so the Honor Interrupt is
    # not offered against it even when the destruction was the action's effect (CR, Interrupt
    # Actions; ShE datasheet, Honor).
    game = two_seat_game()
    _honor_card(game.table, "P2-honor", PlayerId.P2)
    game.action = DeclareAttack()
    hero = put_in_play(game, personality("P1-p", personal_honor=2))
    hero.dishonor()

    resolve_action_effects(game, [Destroy(hero.id, Rulebook.BATTLE_RESOLUTION)])

    assert game.pending is None
    assert game.table.seats[P1].honor == -2


def test_a_destroyed_holding_is_not_a_death():
    game = two_seat_game()
    farm = put_in_play(game, holding("P1-h"))
    farm.dishonor()

    resolve_effects(game, [Destroy(farm.id, PlayerId.P2)])

    assert game.table.seats[P1].honor == 0
