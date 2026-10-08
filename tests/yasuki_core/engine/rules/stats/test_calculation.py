import pytest

from yasuki_core.engine import ops
from yasuki_core.engine.players import PlayerId
from yasuki_core.engine.rules.battle.records import AttackPhase, BattlefieldInfo
from yasuki_core.engine.rules.stats.calculation import effective_stat, is_modified, unbounded_stat
from yasuki_core.engine.rules.stats.card_values import (
    effective_chi,
    effective_force,
    effective_personal_honor,
)
from yasuki_core.engine.rules.effects import (
    AdjustCounter,
    Discard,
    GrantModifier,
    GrantStatChangeNegation,
)
from yasuki_core.engine.rules.triggers import reach_moment, resolve_effects
from yasuki_core.engine.rules.turn.structure import END_OF_TURN
from yasuki_core.engine.rules.vocabulary.modifiers import (
    Condition,
    ConditionalModifier,
    Duration,
    Minimum,
    Modifier,
    Stat,
    StatChangeNegation,
    StatChanges,
)
from yasuki_core.engine.rules.state import GameState
from yasuki_core.engine.table import Location, ZoneKey, ZoneRole
from yasuki_core.game_pieces.cards import L5RCard
from yasuki_core.game_pieces.constants import AttachmentType, Side
from yasuki_core.game_pieces.prints import AttachmentPrint, PersonalityPrint

from yasuki_core.game_pieces.counters import MINUS_1F, PLUS_1F

from tests.yasuki_core.engine.builders import (
    attached,
    attachment,
    holding,
    personality,
    put_in_play,
    two_seat_game,
)


def _personality(
    card_id: str = "p", *, force: int = 2, chi: int = 3, personal_honor: int = 2, counters=None
) -> L5RCard:
    return L5RCard.of(
        PersonalityPrint,
        id=card_id,
        printed_id=card_id,
        name=card_id,
        side=Side.DYNASTY,
        owner=PlayerId.P1,
        force=force,
        chi=chi,
        personal_honor=personal_honor,
        counters=counters or {},
    )


def _game(card: L5RCard, modifiers=()) -> GameState:
    game = two_seat_game()
    put_in_play(game, card)
    game.ongoing.extend(modifiers)
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


def _attacked_by(game: GameState, card: L5RCard) -> None:
    """Open a battle at P2's first Province with ``card`` in P1's attacking army."""
    game.attack = AttackPhase(
        attacker=PlayerId.P1,
        defender=PlayerId.P2,
        battlefields=(BattlefieldInfo(province=ZoneKey(PlayerId.P2, ZoneRole.PROVINCE, 0)),),
        current=0,
    )
    ops.set_location(game.table, card, Location.at_battlefield(0))


def test_a_conditional_grant_reaches_a_card_only_while_its_condition_holds():
    samurai = _personality(force=2)
    penalty = ConditionalModifier(
        "src", Condition.ATTACKING, Stat.FORCE, -1, Duration.UNTIL_END_OF_TURN
    )
    game = _game(samurai, [penalty])
    assert effective_force(game, samurai) == 2

    _attacked_by(game, samurai)
    assert effective_force(game, samurai) == 1

    ops.set_location(game.table, samurai, Location.home(PlayerId.P1))
    assert effective_force(game, samurai) == 2


def test_a_conditional_grant_reaches_a_card_that_entered_play_after_it_was_recorded():
    samurai = _personality(force=2)
    penalty = ConditionalModifier(
        "src", Condition.ATTACKING, Stat.FORCE, -1, Duration.UNTIL_END_OF_TURN
    )
    game = _game(samurai, [penalty])
    latecomer = put_in_play(game, _personality("late", force=3))

    _attacked_by(game, latecomer)

    assert effective_force(game, latecomer) == 2


def test_a_while_source_in_play_conditional_grant_drops_when_its_source_leaves():
    samurai = _personality(force=2)
    penalty = ConditionalModifier(
        "gone", Condition.ATTACKING, Stat.FORCE, -1, Duration.WHILE_SOURCE_IN_PLAY
    )
    game = _game(samurai, [penalty])  # "gone" was never put into play
    _attacked_by(game, samurai)

    assert effective_force(game, samurai) == 2


def test_a_conditional_grant_adjusts_only_the_stat_it_names():
    samurai = _personality(force=2, chi=3)
    penalty = ConditionalModifier(
        "src", Condition.ATTACKING, Stat.FORCE, -1, Duration.UNTIL_END_OF_TURN
    )
    game = _game(samurai, [penalty])
    _attacked_by(game, samurai)

    assert effective_chi(game, samurai) == 3


def test_is_modified_answers_for_a_modifier_on_any_stat():
    plain = _personality("plain")
    blessed = _personality("blessed", counters={"aura": 1})
    honored = _personality("honored")
    kensai = L5RCard.of(
        PersonalityPrint,
        id="kensai",
        printed_id="kensai",
        name="kensai",
        side=Side.DYNASTY,
        owner=PlayerId.P1,
        force=2,
        chi=3,
        keywords=("Kensai",),
    )
    game = _game(
        plain, [Modifier("src", honored.id, Stat.PERSONAL_HONOR, 1, Duration.UNTIL_END_OF_TURN)]
    )
    for card in (blessed, honored, kensai):
        put_in_play(game, card)

    assert not is_modified(game, plain)
    assert is_modified(game, blessed)
    assert is_modified(game, honored)
    assert is_modified(game, kensai)


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


def test_the_unbounded_stat_reads_past_the_floor():
    samurai = _personality(force=2)
    penalty = Modifier("src", samurai.id, Stat.FORCE, -3, Duration.UNTIL_END_OF_TURN)
    game = _game(samurai, [penalty])

    assert unbounded_stat(game, samurai, Stat.FORCE) == -1


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
    """ "Absent values cannot receive bonuses, penalties or modifiers": a Holding handed a Force
    grant stays at zero rather than becoming a 3-Force Holding."""
    farm = holding("f", gold_production=2)
    granted = Modifier("src", farm.id, Stat.FORCE, 3, Duration.UNTIL_END_OF_TURN)
    game = _game(farm, [granted])

    assert effective_force(game, farm) == 0


def test_an_items_force_is_the_bonus_it_prints():
    bow = L5RCard.of(
        AttachmentPrint,
        id="bow",
        printed_id="bow",
        name="Bow",
        side=Side.FATE,
        owner=PlayerId.P1,
        attachment_type=AttachmentType.ITEM,
        force_modifier=2,
    )
    game = _game(bow)

    assert effective_force(game, bow) == 2
    assert effective_chi(game, bow) == 0


@pytest.mark.parametrize("attachment_type", [AttachmentType.ITEM, AttachmentType.SPELL])
def test_a_token_on_an_item_or_spell_raises_its_force_and_its_bearers(attachment_type):
    hero = _personality(force=2)
    game = _game(hero)
    club = attachment("club", attachment_type=attachment_type, force_modifier=1)
    attached(game, club, hero.id)
    resolve_effects(game, [AdjustCounter(club.id, PLUS_1F, 2)])

    assert effective_force(game, club) == 3
    assert effective_force(game, hero) == 5


def test_a_token_on_a_follower_raises_the_follower_and_not_its_personality():
    hero = _personality(force=2)
    game = _game(hero)
    ashigaru = attachment("ashigaru", attachment_type=AttachmentType.FOLLOWER, force=1)
    attached(game, ashigaru, hero.id)
    resolve_effects(game, [AdjustCounter(ashigaru.id, PLUS_1F, 2)])

    assert effective_force(game, ashigaru) == 3
    assert effective_force(game, hero) == 2


def test_a_stat_printed_as_a_dash_reads_zero_and_takes_no_modifiers():
    """A dash is an absent value, not a zero that can be bonused: a Holding printed with no Gold
    Cost stays free however many Gold Cost modifiers land on it."""
    free = holding("free", gold_cost=None)
    surcharge = Modifier("src", free.id, Stat.GOLD_COST, 2, Duration.PERMANENT)
    game = _game(free, [surcharge])

    assert effective_stat(game, free, Stat.GOLD_COST) == 0


def test_a_granted_minimum_floors_the_stat_above_zero():
    """CR, Minimums and Maximums: an effect may give a stat a minimum value, applied on top of the
    penalties rather than among them."""
    samurai = _personality(chi=2)
    game = _game(
        samurai,
        [
            Minimum("uncertainty", samurai.id, Stat.CHI, 1, Duration.UNTIL_END_OF_TURN),
            Modifier("uncertainty", samurai.id, Stat.CHI, -5, Duration.UNTIL_END_OF_TURN),
        ],
    )

    assert effective_chi(game, samurai) == 1


def test_the_most_restrictive_minimum_is_the_one_that_applies():
    """CR, Minimums and Maximums: "a minimum of 1 overrides a minimum of 0"."""
    samurai = _personality(chi=2)
    game = _game(
        samurai,
        [
            Minimum("low", samurai.id, Stat.CHI, 1, Duration.UNTIL_END_OF_TURN),
            Minimum("high", samurai.id, Stat.CHI, 3, Duration.UNTIL_END_OF_TURN),
            Modifier("penalty", samurai.id, Stat.CHI, -5, Duration.UNTIL_END_OF_TURN),
        ],
    )

    assert effective_chi(game, samurai) == 3


def test_a_minimum_never_raises_a_stat_that_already_clears_it():
    samurai = _personality(chi=4)
    game = _game(samurai, [Minimum("src", samurai.id, Stat.CHI, 1, Duration.UNTIL_END_OF_TURN)])

    assert effective_chi(game, samurai) == 4


def test_a_minimum_floors_only_the_stat_it_names():
    samurai = _personality(force=3, chi=2)
    game = _game(
        samurai,
        [
            Minimum("src", samurai.id, Stat.CHI, 2, Duration.UNTIL_END_OF_TURN),
            Modifier("src", samurai.id, Stat.FORCE, -5, Duration.UNTIL_END_OF_TURN),
        ],
    )

    assert effective_chi(game, samurai) == 2
    assert effective_force(game, samurai) == 0


def test_a_minimum_floors_only_the_card_it_names():
    samurai = _personality("a", chi=2)
    other = _personality("b", chi=2)
    game = _game(samurai, [Minimum("src", samurai.id, Stat.CHI, 1, Duration.UNTIL_END_OF_TURN)])
    put_in_play(game, other)
    game.ongoing.append(Modifier("src", other.id, Stat.CHI, -5, Duration.UNTIL_END_OF_TURN))

    assert effective_chi(game, other) == 0


def test_a_while_source_in_play_minimum_drops_when_its_source_leaves():
    samurai = _personality(chi=2)
    game = _game(
        samurai,
        [
            Minimum("gone", samurai.id, Stat.CHI, 2, Duration.WHILE_SOURCE_IN_PLAY),
            Modifier("penalty", samurai.id, Stat.CHI, -5, Duration.UNTIL_END_OF_TURN),
        ],
    )  # "gone" was never put into play

    assert effective_chi(game, samurai) == 0


def test_a_dishonorable_personality_has_a_maximum_personal_honor_of_zero():
    """CR, Honorable and Dishonorable. The cap applies to the total, so a bonus cannot lift it, and
    rehonoring restores the printed value."""
    samurai = _personality(personal_honor=3)
    game = _game(
        samurai,
        [Modifier("blessing", samurai.id, Stat.PERSONAL_HONOR, 2, Duration.UNTIL_END_OF_TURN)],
    )
    samurai.dishonor()

    assert effective_personal_honor(game, samurai) == 0

    samurai.rehonor()
    assert effective_personal_honor(game, samurai) == 5


def test_the_cap_binds_only_personal_honor():
    samurai = _personality(force=2, chi=3)
    game = _game(samurai)
    samurai.dishonor()

    assert effective_force(game, samurai) == 2
    assert effective_chi(game, samurai) == 3


def test_a_minimum_above_the_maximum_cancels_both():
    """CR, Minimums and Maximums: "the minimum and maximum cancel each other out; neither one is
    applied until the other one ends." Only the basic floor of zero remains."""
    samurai = _personality(personal_honor=3)
    game = _game(
        samurai,
        [
            Minimum("vow", samurai.id, Stat.PERSONAL_HONOR, 1, Duration.UNTIL_END_OF_TURN),
            Modifier("slander", samurai.id, Stat.PERSONAL_HONOR, -5, Duration.UNTIL_END_OF_TURN),
        ],
    )
    samurai.dishonor()

    assert effective_personal_honor(game, samurai) == 0

    game.ongoing.pop()
    assert effective_personal_honor(game, samurai) == 3


def _negate(game: GameState, *cards: L5RCard, changes: StatChanges, reaches_new=False) -> None:
    negation = GrantStatChangeNegation(
        "negator",
        frozenset(card.id for card in cards),
        Stat.FORCE,
        changes,
        Duration.UNTIL_END_OF_TURN,
        reaches_new=reaches_new,
    )
    resolve_effects(game, [negation])


def _give_force(game: GameState, card: L5RCard, amount: int) -> None:
    resolve_effects(
        game, [GrantModifier("src", card.id, Stat.FORCE, amount, Duration.UNTIL_END_OF_TURN)]
    )


def _adjust_minus_one_force(game: GameState, card: L5RCard, delta: int) -> None:
    resolve_effects(game, [AdjustCounter(card.id, MINUS_1F, delta)])


def test_negating_current_penalties_spares_the_bonuses_and_every_penalty_given_later():
    hero = _personality(force=6)
    game = _game(hero)
    _adjust_minus_one_force(game, hero, 1)
    _give_force(game, hero, -1)
    _give_force(game, hero, 2)

    _negate(game, hero, changes=StatChanges.PENALTIES)
    assert effective_force(game, hero) == 8

    _give_force(game, hero, -1)
    _adjust_minus_one_force(game, hero, 1)
    assert effective_force(game, hero) == 6


def test_a_token_removed_and_added_again_is_a_new_penalty():
    hero = _personality(force=6)
    game = _game(hero)
    _adjust_minus_one_force(game, hero, 2)
    _negate(game, hero, changes=StatChanges.PENALTIES)

    _adjust_minus_one_force(game, hero, -1)
    _adjust_minus_one_force(game, hero, 1)

    assert effective_force(game, hero) == 5


def test_negating_current_and_new_penalties_reaches_the_later_ones_too():
    hero = _personality(force=4)
    game = _game(hero)
    _give_force(game, hero, -1)

    _negate(game, hero, changes=StatChanges.PENALTIES, reaches_new=True)
    _give_force(game, hero, -2)

    assert effective_force(game, hero) == 4


@pytest.mark.parametrize(
    ("attachment_type", "force"),
    [(AttachmentType.ITEM, 3), (AttachmentType.SPELL, 4), (AttachmentType.FOLLOWER, 4)],
)
def test_only_an_items_printed_modifier_is_no_penalty_to_negate(attachment_type, force):
    hero = _personality(force=4)
    game = _game(hero)
    cursed = attachment("cursed", attachment_type=attachment_type, force_modifier=-1)
    attached(game, cursed, hero.id)

    _negate(game, hero, changes=StatChanges.BOTH)

    assert effective_force(game, hero) == force


@pytest.mark.parametrize(
    ("changes", "force"), [(StatChanges.PENALTIES, 5), (StatChanges.BONUSES, 2)]
)
def test_lonely_battlefield_gives_a_lone_commander_a_penalty_and_a_bonus_apart(changes, force):
    commander = personality("commander", force=4, keywords=("Commander",))
    game = _game(commander)
    put_in_play(game, holding("lonely", printed_id="lonely_battlefield"))
    assert effective_force(game, commander) == 3

    _negate(game, commander, changes=changes)

    assert effective_force(game, commander) == force


def test_a_text_penalty_that_starts_on_a_second_subject_later_is_new(granting):
    granting(
        "curse_probe",
        lambda game, source, card, stat: (-1,) if stat is Stat.FORCE and card.bowed else (),
    )
    first = _personality("first", force=4)
    second = _personality("second", force=4)
    game = _game(first)
    put_in_play(game, second)
    put_in_play(game, holding("curse", printed_id="curse_probe"))
    first.bow()

    _negate(game, first, second, changes=StatChanges.PENALTIES)
    second.bow()

    assert effective_force(game, first) == 4
    assert effective_force(game, second) == 3


def test_a_negation_forgets_each_subject_that_leaves_and_ends_with_its_last():
    first = _personality("first", force=4)
    second = _personality("second", force=4)
    game = _game(first)
    put_in_play(game, second)
    _negate(game, first, second, changes=StatChanges.PENALTIES)

    resolve_effects(game, [Discard(first.id, PlayerId.P1)])
    [negation] = [held for held in game.ongoing if isinstance(held, StatChangeNegation)]
    assert negation.subjects == {second.id}

    resolve_effects(game, [Discard(second.id, PlayerId.P1)])
    assert not any(isinstance(held, StatChangeNegation) for held in game.ongoing)


def test_a_negation_lapses_at_the_end_of_the_turn():
    hero = _personality(force=4)
    game = _game(hero)
    _give_force(game, hero, -1)
    _negate(game, hero, changes=StatChanges.PENALTIES)

    reach_moment(game, END_OF_TURN)

    assert not any(isinstance(held, StatChangeNegation) for held in game.ongoing)
