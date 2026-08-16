from yasuki_core.engine.players import PlayerId
from yasuki_core.engine.rules.economy import effective_chi, effective_force, effective_stat
from yasuki_core.engine.rules.modifiers import Duration, Modifier, Stat
from yasuki_core.engine.rules.state import GameState
from yasuki_core.game_pieces.cards import L5RCard
from yasuki_core.game_pieces.constants import AttachmentType, Side
from yasuki_core.game_pieces.prints import AttachmentPrint, PersonalityPrint

from tests.yasuki_core.engine.builders import holding, put_in_play, two_seat_game


def _personality(card_id: str = "p", *, force: int = 2, chi: int = 3, counters=None) -> L5RCard:
    return L5RCard.of(
        PersonalityPrint,
        id=card_id,
        name=card_id,
        side=Side.DYNASTY,
        owner=PlayerId.P1,
        force=force,
        chi=chi,
        counters=counters or {},
    )


def _game(card: L5RCard, modifiers=()) -> GameState:
    game = two_seat_game()
    put_in_play(game, card)
    game.modifiers.extend(modifiers)
    return game


def test_a_personality_with_nothing_on_it_reads_its_printed_stats():
    samurai = _personality(force=2, chi=3)
    game = _game(samurai)

    assert effective_force(game, samurai) == 2
    assert effective_chi(game, samurai) == 3


def test_a_counter_grants_its_per_count_delta_to_both_stats():
    """The counter catalogue already declares Force and Chi deltas, and its field names are the
    ``Stat`` values, so an Aura token reaches the total the moment the stats exist."""
    blessed = _personality(force=2, chi=3, counters={"aura": 2})
    game = _game(blessed)

    assert effective_force(game, blessed) == 2 + 2  # +1F per Aura
    assert effective_chi(game, blessed) == 3 + 2


def test_a_recorded_grant_reaches_the_total():
    samurai = _personality(force=2)
    granted = Modifier("src", samurai.id, Stat.FORCE, 3, Duration.UNTIL_END_OF_TURN)
    game = _game(samurai, [granted])

    assert effective_force(game, samurai) == 5


def test_counters_and_recorded_grants_compose():
    blessed = _personality(force=2, counters={"aura": 1})
    granted = Modifier("src", blessed.id, Stat.FORCE, 3, Duration.UNTIL_END_OF_TURN)
    game = _game(blessed, [granted])

    assert effective_force(game, blessed) == 2 + 1 + 3


def test_a_while_source_in_play_grant_drops_when_its_source_leaves():
    samurai = _personality(force=2)
    granted = Modifier("gone", samurai.id, Stat.FORCE, 3, Duration.WHILE_SOURCE_IN_PLAY)
    game = _game(samurai, [granted])  # "gone" was never put into play

    assert effective_force(game, samurai) == 2


def test_the_minimum_applies_to_the_total_rather_than_to_each_step():
    """The CR's own example (Calculating Stats): a 2F card penalised -3F and then given +2F has 1
    Force, not 2. Flooring each modifier as it lands would read 2, and flooring nothing would read
    1 by luck while reading -1 for the penalty alone."""
    samurai = _personality(force=2)
    penalty = Modifier("src", samurai.id, Stat.FORCE, -3, Duration.UNTIL_END_OF_TURN)
    bonus = Modifier("src", samurai.id, Stat.FORCE, 2, Duration.UNTIL_END_OF_TURN)
    game = _game(samurai, [penalty, bonus])

    assert effective_force(game, samurai) == 1


def test_force_floors_at_zero_rather_than_going_negative():
    samurai = _personality(force=2)
    penalty = Modifier("src", samurai.id, Stat.FORCE, -3, Duration.UNTIL_END_OF_TURN)
    game = _game(samurai, [penalty])

    assert effective_force(game, samurai) == 0  # "zero for all purposes, not -1"


def test_chi_penalised_past_zero_reads_zero_which_is_what_kills_a_personality():
    """The Chi Death Rule destroys a Personality whose Chi "is ever zero", so the floor is what
    makes an over-penalised Personality register as dead. An unfloored -1 would slip past the rule
    the reading exists to feed."""
    samurai = _personality(chi=2)
    penalty = Modifier("src", samurai.id, Stat.CHI, -5, Duration.UNTIL_END_OF_TURN)
    game = _game(samurai, [penalty])

    assert effective_chi(game, samurai) == 0


def test_a_card_type_that_prints_no_such_stat_reads_zero():
    farm = holding("f", gold_production=2)
    game = _game(farm)

    assert effective_force(game, farm) == 0
    assert effective_chi(game, farm) == 0


def test_an_absent_stat_takes_no_modifiers_at_all():
    """ "Absent values cannot receive bonuses, penalties or modifiers" — a Holding handed a Force
    grant stays at zero rather than becoming a 3-Force Holding."""
    farm = holding("f", gold_production=2)
    granted = Modifier("src", farm.id, Stat.FORCE, 3, Duration.UNTIL_END_OF_TURN)
    game = _game(farm, [granted])

    assert effective_force(game, farm) == 0


def test_an_attachments_printed_force_is_readable():
    """Followers and Items carry Force and Chi of their own — the stats a unit will total. Without
    them on the print there is nothing for an attachment to contribute."""
    bow = L5RCard.of(
        AttachmentPrint,
        id="bow",
        name="Bow",
        side=Side.FATE,
        owner=PlayerId.P1,
        attachment_type=AttachmentType.ITEM,
        force=2,
    )
    game = _game(bow)

    assert effective_force(game, bow) == 2
    assert effective_chi(game, bow) == 0


def test_a_stat_printed_as_a_dash_reads_zero_and_takes_no_modifiers():
    """A dash is an absent value, not a zero that can be bonused: a Holding printed with no Gold
    Cost stays free however many Gold Cost modifiers land on it."""
    free = holding("free", gold_cost=None)
    surcharge = Modifier("src", free.id, Stat.GOLD_COST, 2, Duration.PERMANENT)
    game = _game(free, [surcharge])

    assert effective_stat(game, free, Stat.GOLD_COST) == 0
