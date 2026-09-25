import inspect
from dataclasses import FrozenInstanceError, dataclass, replace

import pytest

from yasuki_core.engine.players import PlayerId
from yasuki_core.engine.rules import effects
from yasuki_core.engine.rules.vocabulary.decisions import ChooseCards, DecisionResponse
from yasuki_core.engine.rules.turn.action_sequence import submit
from yasuki_core.engine.rules.turn.sequence import run_stack
from yasuki_core.engine.rules.triggers import choice_resolver, resolve_effects
from yasuki_core.engine.rules.effects import (
    AdjustCounter,
    AskDistribution,
    Banish,
    BanishTopFate,
    CreateToken,
    Bow,
    Choose,
    Destroy,
    Fear,
    Discard,
    DiscardFavor,
    Dishonor,
    Evaluate,
    GainHonor,
    PlaceInProvince,
    Effect,
    Rehonor,
    RevokeGrants,
    seppuku,
    TakeFavor,
    InterruptingEffect,
    Unpayable,
)
from yasuki_core.engine.rules.vocabulary.game_events import (
    CardDiscarded,
    Dishonored,
    FavorDiscarded,
    HonorChanged,
    Rehonored,
)
from yasuki_core.engine.rules.state import GameState
from yasuki_core.engine.rules.vocabulary.modifiers import (
    AbilityGrant,
    Duration,
    Modifier,
    SeatAbilityGrant,
    Stat,
)
from yasuki_core.engine.table import DeckKey, TableState, ZoneKey, ZoneRole
from yasuki_core.game_pieces.constants import AttachmentType, Side
from yasuki_core.game_pieces.prints import AttachmentPrint
from yasuki_core.game_pieces.counters import WEALTH

from tests.yasuki_core.engine.builders import (
    fate_card,
    holding,
    personality,
    province_card,
    put_in_play,
    two_seat_game,
)


def _effect_types():
    """Every concrete Effect the module defines. Discovered rather than listed, so a new effect is
    covered by these tests the moment it is written. Abstract bases are excluded."""
    return [
        value
        for value in vars(effects).values()
        if inspect.isclass(value) and issubclass(value, Effect) and not inspect.isabstract(value)
    ]


def test_every_effect_implements_perform():
    missing = [
        cls.__name__
        for cls in _effect_types()
        if getattr(cls.perform, "__isabstractmethod__", False)
    ]
    assert missing == []


def test_effect_discovery_finds_concrete_effects_and_excludes_the_base():
    # Guards the discovery above: if it silently found nothing, the other tests would pass
    # vacuously.
    assert Bow in _effect_types()
    assert Effect not in _effect_types()
    assert InterruptingEffect not in _effect_types()


def test_effects_stay_frozen_hashable_and_slotted():
    # Replay compares rebuilt effects by value and stashes them on the work stack, so an effect that
    # lost frozen-ness or value equality would break resumption silently.
    bow = Bow("card")
    assert bow == Bow("card") and hash(bow) == hash(Bow("card"))
    assert not hasattr(bow, "__dict__")
    with pytest.raises(FrozenInstanceError):
        bow.card_id = "other"


def test_is_payable_defaults_to_true():
    game = two_seat_game()
    assert effects.DrawCard(PlayerId.P1).is_payable(game) is True


def test_bow_is_not_payable_for_an_already_bowed_card():
    game = two_seat_game()
    card = put_in_play(game, holding("P1-h"))
    assert Bow(card.id).is_payable(game) is True
    card.bow()
    assert Bow(card.id).is_payable(game) is False


def test_bow_is_not_payable_for_a_card_that_is_not_there():
    assert Bow("nonexistent").is_payable(two_seat_game()) is False


def test_dishonor_turns_a_personality_once_and_announces_it():
    game = two_seat_game()
    hero = put_in_play(game, personality("P1-p"))

    assert Dishonor(hero.id, PlayerId.P2).perform(game) == [Dishonored(hero.id, PlayerId.P2)]
    assert hero.dishonorable is True
    assert Dishonor(hero.id, PlayerId.P2).perform(game) == []


def test_rehonor_restores_a_dishonorable_personality_once():
    game = two_seat_game()
    hero = put_in_play(game, personality("P1-p"))
    hero.dishonor()

    assert Rehonor(hero.id).perform(game) == [Rehonored(hero.id)]
    assert hero.dishonorable is False
    assert Rehonor(hero.id).perform(game) == []


def test_only_a_personality_can_be_dishonored():
    game = two_seat_game()
    farm = put_in_play(game, holding("P1-h"))

    assert Dishonor(farm.id, PlayerId.P1).perform(game) == []
    assert farm.dishonorable is False
    assert Dishonor(farm.id, PlayerId.P1).is_payable(game) is False


def test_seppuku_rehonors_and_then_destroys(reacting):
    # The Personality's own "after this Personality is rehonored" fires before he dies: the
    # destruction is deferred until the rehonoring's cascade has drained.
    game = two_seat_game()
    hero = put_in_play(game, personality("P1-p", printed_id="seppuku_probe"))
    hero.dishonor()
    seen: list[bool] = []
    reacting(
        Rehonored,
        "seppuku_probe",
        lambda ctx: seen.append(ctx.card in game.table.battlefield.cards) or [],
    )

    resolve_effects(game, seppuku(hero.id, PlayerId.P1))
    run_stack(game)

    assert seen == [True]
    assert hero.dishonorable is False
    assert hero in game.table.zones[ZoneKey(PlayerId.P1, ZoneRole.DYNASTY_DISCARD)].cards


def test_a_gain_from_a_dishonorable_personality_rehonors_him_instead():
    # CR, Rehonoring 0.1: the rehonoring "is substituted for the Honor gain".
    game = two_seat_game()
    hero = put_in_play(game, personality("P1-p"))
    hero.dishonor()

    assert GainHonor(PlayerId.P1, 2, personalities=(hero.id,)).perform(game) == [Rehonored(hero.id)]
    assert not hero.dishonorable
    assert game.table.seats[PlayerId.P1].honor == 0


def test_a_gain_from_an_honorable_or_another_seats_personality_is_gained():
    game = two_seat_game()
    own = put_in_play(game, personality("P1-p"))
    theirs = put_in_play(game, personality("P2-p", owner=PlayerId.P2))
    theirs.dishonor()

    resolve_effects(game, [GainHonor(PlayerId.P1, 2, personalities=(own.id, theirs.id))])

    assert game.table.seats[PlayerId.P1].honor == 2
    assert theirs.dishonorable


def test_a_loss_from_a_dishonorable_personality_is_still_lost():
    game = two_seat_game()
    hero = put_in_play(game, personality("P1-p"))
    hero.dishonor()

    resolve_effects(game, [GainHonor(PlayerId.P1, -2, personalities=(hero.id,))])

    assert game.table.seats[PlayerId.P1].honor == -2
    assert hero.dishonorable


def test_a_gain_reduced_to_nothing_rehonors_nobody():
    # CR, Rehonoring: "preventing the Honor gain also prevents its substituted rehonoring."
    game = two_seat_game()
    hero = put_in_play(game, personality("P1-p"))
    hero.dishonor()

    resolve_effects(game, [GainHonor(PlayerId.P1, 1, adjustment=-1, personalities=(hero.id,))])

    assert hero.dishonorable


def test_a_card_can_react_to_a_dishonoring_and_a_rehonoring(reacting):
    game = two_seat_game()
    hero = put_in_play(game, personality("P1-p", printed_id="watcher"))
    seen: list[str] = []
    reacting(
        Dishonored, "watcher", lambda ctx: seen.append(f"dishonored by {ctx.event.cause}") or []
    )
    reacting(Rehonored, "watcher", lambda ctx: seen.append("rehonored") or [])

    resolve_effects(game, [Dishonor(hero.id, PlayerId.P2), Rehonor(hero.id)])

    assert seen == ["dishonored by PlayerId.P2", "rehonored"]


def test_dishonor_and_rehonor_are_payable_only_when_they_change_the_card():
    game = two_seat_game()
    hero = put_in_play(game, personality("P1-p"))

    assert Dishonor(hero.id, PlayerId.P1).is_payable(game) is True
    assert Rehonor(hero.id).is_payable(game) is False
    hero.dishonor()
    assert Dishonor(hero.id, PlayerId.P1).is_payable(game) is False
    assert Rehonor(hero.id).is_payable(game) is True


def test_removing_a_counter_needs_enough_of_it():
    game = two_seat_game()
    card = put_in_play(game, holding("P1-h", counters={"wealth": 1}))
    assert AdjustCounter(card.id, WEALTH, -1).is_payable(game) is True
    assert AdjustCounter(card.id, WEALTH, -2).is_payable(game) is False


def test_granting_a_counter_always_applies():
    game = two_seat_game()
    card = put_in_play(game, holding("P1-h"))
    assert AdjustCounter(card.id, WEALTH, 1).is_payable(game) is True


def test_banishing_needs_a_fate_card_to_banish():
    game = two_seat_game()
    assert BanishTopFate(PlayerId.P1).is_payable(game) is False
    deck = game.table.decks[DeckKey(PlayerId.P1, Side.FATE)]
    deck.cards = [fate_card("P1-fd", PlayerId.P1)]
    assert BanishTopFate(PlayerId.P1).is_payable(game) is True


def _vanished(game, card_id):
    """Drop a card from the id map while leaving it on the battlefield, as a mid-cascade destroy
    does to any effect that bound it earlier."""
    del game.table.cards_by_id[card_id]


def test_adjusting_a_counter_on_a_vanished_card_is_a_no_op():
    game = two_seat_game()
    card = put_in_play(game, holding("P1-h"))
    _vanished(game, card.id)
    assert AdjustCounter(card.id, WEALTH, 1).perform(game) == []


def test_destroying_a_vanished_card_is_a_no_op():
    game = two_seat_game()
    card = put_in_play(game, holding("P1-h"))
    _vanished(game, card.id)
    assert Destroy(card.id, PlayerId.P1).perform(game) == []


@pytest.mark.parametrize(
    "side, role",
    [(Side.FATE, ZoneRole.FATE_DISCARD), (Side.DYNASTY, ZoneRole.DYNASTY_DISCARD)],
    ids=["fate", "dynasty"],
)
def test_a_discard_lands_in_the_pile_for_its_side(side, role):
    # Destroy and Discard pick the pile the same way. Drift between them would strand a Fate card
    # in the Dynasty discard, where nothing that searches for it would look.
    game = two_seat_game()
    card = fate_card("P1-f", PlayerId.P1) if side is Side.FATE else holding("P1-h")
    put_in_play(game, card)

    events = Discard(card.id, PlayerId.P1).perform(game)

    assert card in game.table.zones[ZoneKey(PlayerId.P1, role)].cards
    assert events == [CardDiscarded(card.id, side, PlayerId.P1)]


@pytest.mark.parametrize(
    "side, role",
    [(Side.FATE, ZoneRole.FATE_BANISH), (Side.DYNASTY, ZoneRole.DYNASTY_BANISH)],
    ids=["fate", "dynasty"],
)
def test_a_banish_lands_in_the_pile_for_its_side(side, role):
    # A banish picks its pile the same way a discard does, one row over. A card banished into a
    # discard pile would be recurrable by everything the banish was meant to put it out of reach of.
    game = two_seat_game()
    card = fate_card("P1-f", PlayerId.P1) if side is Side.FATE else holding("P1-h")
    put_in_play(game, card)

    Banish(card.id).perform(game)

    assert card in game.table.zones[ZoneKey(PlayerId.P1, role)].cards


def test_banishing_a_card_that_is_already_gone_does_nothing():
    # What a delayed banish finds when something destroyed the card first. Raising here would take
    # the turn's end down with it.
    game = two_seat_game()
    card = put_in_play(game, holding("P1-h"))
    _vanished(game, card.id)

    assert Banish(card.id).perform(game) == []


def _token_game():
    """A game whose deck load resolved one token template: a 2F Follower to create."""
    game = two_seat_game()
    game.table.creatable_tokens["scout"] = AttachmentPrint(
        name="Scout",
        side=Side.FATE,
        printed_id="scout",
        attachment_type=AttachmentType.FOLLOWER,
        force=2,
    )
    return game


def test_a_clan_stamped_on_one_creation_does_not_follow_the_template():
    """The template is shared by every card that creates from it and by both seats, so a stamped
    clan has to land on a copy. Mutating it in place would hand the next creation the last
    controller's clan."""
    game = _token_game()

    CreateToken("scout", PlayerId.P1, "maker", clan="Lion").perform(game)
    CreateToken("scout", PlayerId.P2, "maker", clan="Crab").perform(game)

    lion, crab = (card for card in game.table.battlefield.cards if card.is_token)
    assert (lion.clan, crab.clan) == ("Lion", "Crab")
    assert game.table.creatable_tokens["scout"].clan is None  # the template is untouched


def test_a_creation_takes_the_clan_on_both_the_name_and_the_list():
    """A reader of a card's clans takes the list when it has one, so stamping only the singular
    would leave the card aligned to whatever the template printed."""
    game = _token_game()
    game.table.creatable_tokens["ninja"] = replace(
        game.table.creatable_tokens["scout"], printed_id="ninja", clan="Ninja", clans=("Ninja",)
    )

    CreateToken("ninja", PlayerId.P1, "maker", clan="Crane").perform(game)

    made = next(card for card in game.table.battlefield.cards if card.is_token)
    assert (made.clan, made.clans) == ("Crane", ("Crane",))


def test_creating_onto_a_personality_who_has_left_play_creates_nothing():
    # The target is fixed when the ability is announced, and anything can happen to him before the
    # creation resolves. A homeless attachment would be destroyed by the state-based actions on
    # sight.
    game = _token_game()

    events = CreateToken("scout", PlayerId.P1, "maker", attach_to="gone").perform(game)

    assert events == []
    assert game.table.battlefield.cards == []
    assert game.created_by == {}


def test_creating_from_a_template_the_deck_load_never_resolved_is_an_error():
    # A card that can create names its token in the database, so a missing template means the table
    # was built without them. Failing loudly beats a card that silently does nothing.
    game = _token_game()

    with pytest.raises(KeyError):
        CreateToken("no_such_token", PlayerId.P1, "maker").perform(game)


def test_placing_into_a_full_province_is_a_no_op():
    # The placement is deferred behind the reactions to the discard, so something can fill the
    # Province in between. Checking capacity first is what keeps the card where it is: the move
    # would take it out of play before the full Province refused it, leaving it nowhere at all.
    game = two_seat_game()
    province = ZoneKey(PlayerId.P1, ZoneRole.PROVINCE, 0)
    sitting = province_card(game, "P1-sitting", seat=PlayerId.P1)
    card = put_in_play(game, holding("P1-late"))

    assert PlaceInProvince(card.id, province).perform(game) == []
    assert [c.id for c in game.table.zones[province].cards] == [sitting.id]
    assert card in game.table.battlefield.cards  # not swallowed on the way


@dataclass(frozen=True, slots=True)
class _AskToDiscard(InterruptingEffect):
    """A second interrupting effect, defined only here. Nothing in the engine knows it exists."""

    seat: PlayerId
    candidates: tuple[str, ...]

    def describe(self) -> str:
        return f"{self.seat.name} is asked to discard"

    def request(self, game) -> ChooseCards:
        return ChooseCards(
            seat=self.seat,
            candidates=self.candidates,
            minimum=0,
            maximum=0,
            resolver="test_ask_to_discard",
        )


@choice_resolver("test_ask_to_discard")
def _ask_to_discard_resolved(game, source_id, chosen, seat):
    return []


def test_a_new_interrupting_effect_pauses_the_cascade_without_engine_changes():
    # The point of the category: the walker stashes on any InterruptingEffect, so an effect the
    # engine has never heard of pauses the cascade correctly.
    game = two_seat_game()
    card = put_in_play(game, holding("P1-h"))

    resolve_effects(
        game, [_AskToDiscard(PlayerId.P1, (card.id,)), AdjustCounter(card.id, WEALTH, 1)]
    )

    assert isinstance(game.pending, ChooseCards)
    assert card.counters.get("wealth") is None  # the effect after it has not run yet


def test_the_stashed_remainder_resumes_after_the_answer():
    game = two_seat_game()
    card = put_in_play(game, holding("P1-h"))
    resolve_effects(
        game, [_AskToDiscard(PlayerId.P1, (card.id,)), AdjustCounter(card.id, WEALTH, 1)]
    )

    submit(game, DecisionResponse(()))

    assert card.counters["wealth"] == 1  # the effect queued behind the pause ran on resume


_SOURCES_SEEN: list[str | None] = []


@choice_resolver("test_sourceless")
def _record_the_source(game, source_id, chosen, seat):
    _SOURCES_SEEN.append(source_id)
    return []


def test_a_choice_raised_by_no_card_reaches_its_resolver_with_none():
    # A rulebook ability has no card to name, and no card id can stand in for one: every string is
    # a perfectly good id that simply never matches, leaving a resolver unable to tell "no source"
    # from "a source I have not heard of".
    _SOURCES_SEEN.clear()
    game = two_seat_game()
    card = put_in_play(game, holding("P1-h"))

    resolve_effects(game, [Choose(PlayerId.P1, (card.id,), 0, 1, "test_sourceless")])
    submit(game, DecisionResponse((card.id,)))

    assert _SOURCES_SEEN == [None]


_SEATS_SEEN: list[PlayerId] = []


@choice_resolver("test_answering_seat")
def _record_the_seat(game, source_id, chosen, seat):
    _SEATS_SEEN.append(seat)
    return []


def test_a_resolver_is_told_which_seat_answered():
    """A choice can be put to a seat other than the one whose action raised it, and a declining
    answer names no card, so the seat cannot be recovered from the source or the chosen ids."""
    _SEATS_SEEN.clear()
    game = two_seat_game()
    card = put_in_play(game, holding("P2-h", owner=PlayerId.P2))

    resolve_effects(game, [Choose(PlayerId.P2, (card.id,), 0, 1, "test_answering_seat")])
    submit(game, DecisionResponse(()))  # declined: nothing chosen to infer a seat from

    assert _SEATS_SEEN == [PlayerId.P2]


def test_an_interrupting_effect_that_finds_nobody_to_ask_is_performed():
    game = two_seat_game()
    before = game.table.seats[PlayerId.P1].honor

    resolve_effects(game, [GainHonor(PlayerId.P1, 2)])

    assert game.pending is None
    assert game.table.seats[PlayerId.P1].honor == before + 2


def test_an_interrupting_effect_refuses_to_be_committed_directly():
    effect = _AskToDiscard(PlayerId.P1, ("a",))
    with pytest.raises(RuntimeError, match="never applied directly"):
        effect.perform(two_seat_game())


def test_an_unpayable_cost_refuses_to_resolve():
    # It exists to be refused by can_pay, so resolving one means a legality check was skipped. That
    # has to be loud: silently doing nothing would let an ability fire for free.
    with pytest.raises(RuntimeError, match="unpayable cost"):
        Unpayable("hero has left play").perform(two_seat_game())


@pytest.mark.parametrize(
    "candidates, count",
    [
        pytest.param((), 2, id="nowhere-to-put-them"),
        pytest.param(("a",), 0, id="nothing-to-divide"),
    ],
)
def test_a_division_that_cannot_be_answered_is_refused_rather_than_asked(candidates, count):
    # The cascade pauses on every interrupting effect, so asking either way would stop the game on a
    # question with no answer: no exception, no log, a client waiting forever.
    ask = AskDistribution(PlayerId.P1, candidates, count, "split", "source")

    with pytest.raises(ValueError, match="cannot divide"):
        ask.request(two_seat_game())


def test_taking_the_favor_gives_it_to_the_seat():
    """Twenty Festivals CR, The Imperial Favor: one player controls it at a time."""
    game = GameState.start(TableState.empty_two_seat(), PlayerId.P1, seed=0)

    TakeFavor(PlayerId.P1).perform(game)

    assert game.favor_holder is PlayerId.P1


def test_taking_the_favor_takes_it_from_whoever_held_it():
    """Changes of control are instantaneous, so the previous holder loses it in the same step
    rather than the two seats briefly both holding it."""
    game = GameState.start(TableState.empty_two_seat(), PlayerId.P1, seed=0)
    TakeFavor(PlayerId.P1).perform(game)

    TakeFavor(PlayerId.P2).perform(game)

    assert game.favor_holder is PlayerId.P2


def test_discarding_the_favor_leaves_it_held_by_nobody():
    """Discarding it returns it to uncontrolled rather than passing it to the other seat."""
    game = GameState.start(TableState.empty_two_seat(), PlayerId.P1, seed=0)
    TakeFavor(PlayerId.P1).perform(game)

    events = DiscardFavor(PlayerId.P1).perform(game)

    assert game.favor_holder is None
    assert events == [FavorDiscarded(PlayerId.P1)]


def test_discarding_the_favor_does_not_touch_another_seats_hold():
    """Only the holder discards it, so a discard by anyone else leaves the holder alone."""
    game = GameState.start(TableState.empty_two_seat(), PlayerId.P1, seed=0)
    TakeFavor(PlayerId.P1).perform(game)

    DiscardFavor(PlayerId.P2).perform(game)

    assert game.favor_holder is PlayerId.P1


@pytest.mark.parametrize("amount", [2, -4])
def test_an_honor_change_announces_its_signed_amount(amount):
    game = two_seat_game()
    before = game.table.seats[PlayerId.P1].honor

    events = GainHonor(PlayerId.P1, amount).perform(game)

    assert game.table.seats[PlayerId.P1].honor == before + amount
    assert events == [HonorChanged(PlayerId.P1, amount)]


def test_an_honor_change_of_zero_is_not_announced():
    game = two_seat_game()

    assert GainHonor(PlayerId.P1, 0).perform(game) == []


@pytest.mark.parametrize(
    ("amount", "adjustment", "expected"),
    [(3, 1, 4), (3, -1, 2), (-3, 1, -4), (-3, -1, -2), (1, -2, 0), (-1, -2, 0)],
)
def test_an_adjustment_changes_the_size_of_a_gain_or_loss_but_never_its_direction(
    amount, adjustment, expected
):
    assert effects.adjusted_honor_change(amount, adjustment) == expected


def test_an_attack_performs_every_effect_in_its_outcome():
    game = two_seat_game()
    target = put_in_play(game, holding("P1-h"))
    fear = Fear(
        9, target.id, PlayerId.P2, outcome=(Bow(target.id), Destroy(target.id, PlayerId.P2))
    )

    resolve_effects(game, [fear])

    assert target not in game.table.battlefield.cards


@choice_resolver("test_evaluate_on_the_board")
def _honor_for_each_card_in_play(game, source_id, chosen, seat):
    return [GainHonor(seat, len(game.table.battlefield.cards))]


def test_evaluate_reads_the_board_as_it_stands_when_it_resolves():
    # Built while one card is in play, resolved after a second arrived: the resolver sees two.
    game = two_seat_game()
    put_in_play(game, holding("first"))
    evaluate = Evaluate("test_evaluate_on_the_board", "first", PlayerId.P1)
    put_in_play(game, holding("second"))

    resolve_effects(game, [evaluate])

    assert game.table.seats[PlayerId.P1].honor == 2


def test_revoking_grants_takes_one_sources_ability_grants_and_nothing_else():
    game = two_seat_game()
    kept = [
        Modifier("ground", "farm", Stat.FORCE, 1, Duration.UNTIL_END_OF_TURN),
        AbilityGrant("other", "farm", (), Duration.UNTIL_END_OF_TURN),
        SeatAbilityGrant("other", PlayerId.P1, (), Duration.UNTIL_END_OF_TURN),
    ]
    game.ongoing = [
        AbilityGrant("ground", "farm", (), Duration.UNTIL_END_OF_TURN),
        *kept,
        SeatAbilityGrant("ground", PlayerId.P1, (), Duration.WHILE_SOURCE_IN_PLAY),
    ]

    RevokeGrants("ground").perform(game)

    assert game.ongoing == kept
