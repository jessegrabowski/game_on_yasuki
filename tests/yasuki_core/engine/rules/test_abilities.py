from dataclasses import replace

import pytest

from yasuki_core.engine.players import PlayerId
from yasuki_core.engine.table import TableState, ZoneKey, ZoneRole
from yasuki_core.engine.rules.abilities import (
    CardLocation,
    Ability,
    abilities_for,
    ability_for,
    has_absent_ability,
    itself,
    no_cost,
    activatable,
    _ABILITIES,
    _ENTERS_UNBOWED,
    _INVEST,
    register_ability,
    register_enters_unbowed,
    register_invest,
)
from yasuki_core.engine.rules.actions import ActionTiming, ActivateAbility, BattleDesignator
from yasuki_core.engine.rules.decisions import (
    ChooseAbilityTarget,
    ChooseCards,
    DecisionResponse,
)
from yasuki_core.engine.rules.log import replay
from yasuki_core.engine.rules.effects import AdjustCounter, Choose
from yasuki_core.engine.rules.triggers import choice_resolver
from yasuki_core.engine.session import EngineSession
from yasuki_core.game_pieces.cards import L5RCard
from yasuki_core.game_pieces.constants import Side
from yasuki_core.game_pieces.counters import WEALTH
from yasuki_core.game_pieces.prints import FatePrint, HoldingPrint
from tests.yasuki_core.engine.builders import (
    holding,
    province_card,
    put_in_play,
    register,
)


@choice_resolver("test_cost_pauses")
def _test_cost_grant(game, source_id, chosen, seat):
    return [AdjustCounter(card_id, WEALTH, 1) for card_id in chosen]


# A synthetic ability whose cost pauses for a choice. It exercises the deferred target selection: the
# cost's own decision must resolve before the ability's target is asked, neither clobbering the
# other. No real card pays a cost that pauses yet.
register_ability(
    "test_cost_pauses",
    Ability(
        timings=(ActionTiming.OPEN,),
        label="test",
        cost=lambda game, source: [
            Choose(source.owner, (source.id,), 0, 1, "test_cost_pauses", source.id)
        ],
        targets=lambda game, card: [
            c.id
            for c in game.table.battlefield.cards
            if c.owner is card.owner and c is not card and "Farm" in c.keywords
        ],
        effects=lambda game, source, target: [AdjustCounter(target.id, WEALTH, 1)],
    ),
)


def test_a_cost_that_pauses_resolves_before_the_ability_target():
    state = TableState.empty_two_seat()
    put_in_play(state, holding("src", printed_id="test_cost_pauses"))
    put_in_play(
        state, holding("tgt", printed_id="plain_farm", keywords=("Farm",), gold_production=2)
    )
    session = EngineSession.start(state, PlayerId.P1)

    session.act(PlayerId.P1, ActivateAbility("src"))
    assert isinstance(session.game.pending, ChooseCards)  # the cost's choice comes first
    assert session.game.pending.candidates == ("src",)

    session.submit(PlayerId.P1, DecisionResponse(("src",)))
    pending = session.game.pending
    assert isinstance(pending, ChooseAbilityTarget)  # the target, deferred until the cost resolved
    assert pending.candidates == ("tgt",)
    assert session.game.table.cards_by_id["src"].counters == {"wealth": 1}  # cost choice applied

    session.submit(PlayerId.P1, DecisionResponse(("tgt",)))
    assert session.game.pending is None
    assert session.game.table.cards_by_id["tgt"].counters == {"wealth": 1}  # ability effect applied
    assert replay(session.log) == session.game  # the deferred-cost chain replays deterministically


def test_a_second_unkeyed_ability_for_one_card_is_refused():
    """An unkeyed ability is "the card's only one", so a second cannot also be unkeyed — an action
    naming neither would have no way to say which it takes."""
    # These three registries were dict literals until the card modules split them up, where a
    # repeated key was ruff's F601 to catch. Registration-time checks replace that guard.
    plain = _ABILITIES["millet_farm"][0]
    register_ability("guard_probe", plain)

    try:
        with pytest.raises(ValueError, match="guard_probe prints several abilities"):
            register_ability("guard_probe", plain)
    finally:
        _ABILITIES.pop("guard_probe", None)


def test_a_second_ability_may_not_repeat_a_key():
    """Keys are how an action names an ability, so two abilities answering to the same one would
    make the choice unresolvable."""
    plain = _ABILITIES["millet_farm"][0]
    register_ability("guard_probe", replace(plain, key="first"))

    try:
        with pytest.raises(ValueError, match="already has an ability keyed 'first'"):
            register_ability("guard_probe", replace(plain, key="first"))
    finally:
        _ABILITIES.pop("guard_probe", None)


def test_a_card_may_register_several_keyed_abilities():
    """The point of the key: two abilities under one printed id, each retrievable by name."""
    plain = _ABILITIES["millet_farm"][0]
    register_ability("guard_probe", replace(plain, key="fear", label="Battle: Fear 3"))
    register_ability("guard_probe", replace(plain, key="ranged", label="Battle: Ranged 3"))

    try:
        card = L5RCard.of(
            HoldingPrint,
            id="probe",
            name="Probe",
            printed_id="guard_probe",
            side=Side.DYNASTY,
            owner=PlayerId.P1,
        )
        assert [held.key for held in abilities_for(card)] == ["fear", "ranged"]
        assert ability_for(card, "ranged").label == "Battle: Ranged 3"
        assert ability_for(card, "absent") is None
        with pytest.raises(ValueError, match="prints several abilities; name one by key"):
            ability_for(card)
    finally:
        _ABILITIES.pop("guard_probe", None)


def test_a_second_invest_for_one_card_is_refused():
    register_invest("guard_probe", _INVEST["training_court"])

    try:
        with pytest.raises(ValueError, match="guard_probe already has an invest ability"):
            register_invest("guard_probe", _INVEST["training_court"])
    finally:
        _INVEST.pop("guard_probe", None)


def test_a_second_enters_unbowed_for_one_card_is_refused():
    # A set absorbs a repeated registration where the dict registries raise, so without this guard a
    # card listed from two set modules would be invisible rather than loud.
    register_enters_unbowed("guard_probe")

    try:
        with pytest.raises(ValueError, match="guard_probe already enters play unbowed"):
            register_enters_unbowed("guard_probe")
    finally:
        _ENTERS_UNBOWED.discard("guard_probe")


# An ability that acts from a Province rather than from play — the shape every Event needs. It
# targets its own source, so the test needs nothing else there.
register_ability(
    "test_acts_from_province",
    Ability(
        timings=(ActionTiming.OPEN,),
        label="test",
        cost=lambda game, source: [],
        targets=lambda game, card: [card.id],
        effects=lambda game, source, target: [AdjustCounter(target.id, WEALTH, 1)],
        located_at=(CardLocation.PROVINCE,),
    ),
)


# The same ability twice, differing only in where it acts from. A Strategy is played out of hand,
# which is a location nothing acted from before.
register_ability(
    "test_acts_from_hand",
    Ability(
        timings=(ActionTiming.OPEN,),
        label="test",
        cost=lambda game, source: [],
        targets=lambda game, card: [card.id],
        effects=lambda game, source, target: [AdjustCounter(target.id, WEALTH, 1)],
        located_at=(CardLocation.HAND,),
    ),
)

register_ability(
    "test_acts_from_play",
    Ability(
        timings=(ActionTiming.OPEN,),
        label="test",
        cost=lambda game, source: [],
        targets=lambda game, card: [card.id],
        effects=lambda game, source, target: [AdjustCounter(target.id, WEALTH, 1)],
    ),
)


def _in_hand(state: TableState, card_id: str, printed_id: str):
    """Put a Fate card in P1's hand, which is where a Strategy waits to be played."""
    card = register(
        state,
        L5RCard.of(
            FatePrint,
            id=card_id,
            name=card_id,
            printed_id=printed_id,
            side=Side.FATE,
            owner=PlayerId.P1,
        ),
    )
    state.zones[ZoneKey(PlayerId.P1, ZoneRole.HAND)].add(card)
    return card


def test_an_ability_that_acts_from_the_hand_is_found_there():
    state = TableState.empty_two_seat()
    card = _in_hand(state, "strategy", "test_acts_from_hand")
    session = EngineSession.start(state, PlayerId.P1)
    open_timing = frozenset({ActionTiming.OPEN})

    found = activatable(session.game, PlayerId.P1, open_timing, at=(CardLocation.HAND,))

    assert [(held.id, offered.label) for held, offered in found] == [
        (card.id, ability_for(card).label)
    ]


def test_an_ability_that_acts_from_play_is_not_found_in_the_hand():
    """`located_at` defaults to the battlefield, which is what keeps the hand from leaking into
    every ability that already works."""
    state = TableState.empty_two_seat()
    _in_hand(state, "not_yet", "test_acts_from_play")
    session = EngineSession.start(state, PlayerId.P1)
    open_timing = frozenset({ActionTiming.OPEN})

    assert activatable(session.game, PlayerId.P1, open_timing, at=(CardLocation.HAND,)) == []


def test_a_card_in_hand_is_never_activated_in_play():
    """A card in hand is played, not activated, so it must not reach `ActivateAbility` — it pays a
    Gold Cost and goes to the discard, neither of which that action does."""
    state = TableState.empty_two_seat()
    card = _in_hand(state, "strategy", "test_acts_from_hand")
    session = EngineSession.start(state, PlayerId.P1)

    assert ActivateAbility(card.id) not in session.legal_actions(PlayerId.P1)


def test_an_ability_that_acts_from_a_province_is_offered_there():
    state = TableState.empty_two_seat()
    card = province_card(state, "event", printed_id="test_acts_from_province")
    session = EngineSession.start(state, PlayerId.P1)

    assert ActivateAbility(card.id) in session.legal_actions(PlayerId.P1)


def test_an_ability_that_acts_from_a_province_is_not_offered_face_down():
    """Face-down the card has not been revealed, so it is not offering anything yet. Setup reveals
    what starts in a Province, so this is the state a refill leaves behind mid-game."""
    state = TableState.empty_two_seat()
    province_card(state, "event", printed_id="test_acts_from_province")
    session = EngineSession.start(state, PlayerId.P1)
    session.game.table.cards_by_id["event"].turn_face_down()

    assert ActivateAbility("event") not in session.legal_actions(PlayerId.P1)


def test_an_ability_that_acts_from_a_province_is_not_offered_in_play():
    """The scope says where the card acts from, so it excludes as well as it includes."""
    state = TableState.empty_two_seat()
    put_in_play(state, holding("event", printed_id="test_acts_from_province"))
    session = EngineSession.start(state, PlayerId.P1)

    assert ActivateAbility("event") not in session.legal_actions(PlayerId.P1)


def test_a_province_ability_is_not_offered_for_another_seats_card():
    """Asked from the seat holding priority, so it fails if the scan stops filtering by owner —
    asking P2 instead would pass on P2 having no actions at all."""
    state = TableState.empty_two_seat()
    province_card(state, "event", printed_id="test_acts_from_province", seat=PlayerId.P2)
    session = EngineSession.start(state, PlayerId.P1)

    assert ActivateAbility("event") not in session.legal_actions(PlayerId.P1)


def test_an_ability_in_play_is_not_offered_from_a_province():
    """The default scope is the battlefield, so a Holding sitting face-up in a Province offers
    nothing — which is what keeps every existing registration behaving as it did."""
    state = TableState.empty_two_seat()
    card = province_card(
        state, "millet", printed_id="millet_farm", keywords=("Farm",), gold_production=1
    )
    put_in_play(state, holding("farm", printed_id="plain_farm", keywords=("Farm",)))
    session = EngineSession.start(state, PlayerId.P1)

    assert ActivateAbility(card.id) not in session.legal_actions(PlayerId.P1)


# A card that acts from either place. The scope is a tuple so an ability can name more than one, and
# nothing else pins that.
register_ability(
    "test_acts_from_either",
    Ability(
        timings=(ActionTiming.OPEN,),
        label="test",
        cost=lambda game, source: [],
        targets=lambda game, card: [card.id],
        effects=lambda game, source, target: [AdjustCounter(target.id, WEALTH, 1)],
        located_at=(CardLocation.BATTLEFIELD, CardLocation.PROVINCE),
    ),
)


@pytest.mark.parametrize("in_play", [True, False])
def test_an_ability_may_act_from_more_than_one_place(in_play):
    state = TableState.empty_two_seat()
    if in_play:
        put_in_play(state, holding("event", printed_id="test_acts_from_either"))
    else:
        province_card(state, "event", printed_id="test_acts_from_either")
    session = EngineSession.start(state, PlayerId.P1)

    assert ActivateAbility("event") in session.legal_actions(PlayerId.P1)


# A synthetic card printing two abilities under the same designator, which is what Yoritomo Tatsuki
# and Incendiary Archers do: both of each card's abilities are Battle, so nothing but a key tells
# them apart.
for _key, _amount in (("small", 1), ("large", 3)):
    register_ability(
        "test_two_abilities",
        Ability(
            timings=(ActionTiming.OPEN,),
            label=f"Open: Add {_amount} wealth",
            cost=lambda game, source: [],
            targets=lambda game, card: [
                held.id for held in game.table.battlefield.cards if held is not card
            ],
            effects=(
                lambda amount: lambda game, source, target: [
                    AdjustCounter(target.id, WEALTH, amount)
                ]
            )(_amount),
            key=_key,
        ),
    )


def _two_ability_game():
    state = TableState.empty_two_seat()
    put_in_play(state, holding("src", printed_id="test_two_abilities"))
    put_in_play(state, holding("tgt", printed_id="plain_farm", gold_production=2))
    return EngineSession.start(state, PlayerId.P1)


def test_both_of_a_cards_abilities_are_offered():
    """The designator cannot disambiguate — both abilities are Open — so the key is what makes them
    two separate actions rather than one offered twice."""
    session = _two_ability_game()

    offered = [
        action
        for action in session.legal_actions(PlayerId.P1)
        if isinstance(action, ActivateAbility) and action.card_id == "src"
    ]

    assert offered == [ActivateAbility("src", "small"), ActivateAbility("src", "large")]


@pytest.mark.parametrize(("key", "wealth"), [("small", 1), ("large", 3)])
def test_the_ability_named_by_the_action_is_the_one_that_resolves(key, wealth):
    """The whole point of threading the key: the ability announced has to be the ability that
    lands, across the target decision that suspends it."""
    session = _two_ability_game()

    session.act(PlayerId.P1, ActivateAbility("src", key))
    session.submit(PlayerId.P1, DecisionResponse(("tgt",)))

    assert session.game.table.cards_by_id["tgt"].counters == {"wealth": wealth}


def test_a_keyed_activation_replays():
    """``log.Act`` holds the action itself, so a tape carrying a key must replay to the same board
    — the guarantee that keeps every pre-existing tape valid too."""
    session = _two_ability_game()

    session.act(PlayerId.P1, ActivateAbility("src", "large"))
    session.submit(PlayerId.P1, DecisionResponse(("tgt",)))

    assert replay(session.log) == session.game


def test_a_round_offers_only_the_abilities_its_designator_permits():
    """The designator filter is per ability, not per card. A card printing one Open and one Dynasty
    ability is offered once in an Open round — a check hoisted back up to the card would offer both
    or neither."""
    register_ability(
        "test_split_designators",
        replace(
            _ABILITIES["test_two_abilities"][0], timings=(ActionTiming.DYNASTY,), key="dynasty"
        ),
    )
    register_ability(
        "test_split_designators",
        replace(_ABILITIES["test_two_abilities"][1], timings=(ActionTiming.OPEN,), key="open"),
    )

    try:
        state = TableState.empty_two_seat()
        put_in_play(state, holding("src", printed_id="test_split_designators"))
        put_in_play(state, holding("tgt", printed_id="plain_farm", gold_production=2))
        session = EngineSession.start(state, PlayerId.P1)

        offered = [
            action
            for action in session.legal_actions(PlayerId.P1)
            if isinstance(action, ActivateAbility) and action.card_id == "src"
        ]

        assert offered == [ActivateAbility("src", "open")]
    finally:
        _ABILITIES.pop("test_split_designators", None)


def test_an_action_naming_a_key_the_card_does_not_print_is_not_legal():
    """Good Faith is enforced by ``legal_actions``, so a hand-built action carrying an unknown key
    must not be accepted as though it named the card's only ability."""
    session = _two_ability_game()

    assert ActivateAbility("src", "enormous") not in session.legal_actions(PlayerId.P1)


# A pair of probes differing only in Tireless, so the bowed rule and its one exception can be told
# apart on otherwise identical cards.
for _probe, _tireless in (("test_bows_to_act", False), ("test_acts_while_bowed", True)):
    register_ability(
        _probe,
        Ability(
            timings=(ActionTiming.OPEN,),
            label="Open: probe",
            cost=no_cost,
            targets=itself,
            effects=lambda game, source, target: [],
            all_targets=True,
            tireless=_tireless,
        ),
    )


def test_a_bowed_card_offers_nothing():
    """ "Abilities on bowed cards may not normally be used" (CR, Using Abilities). The cost is not
    what stops it — this ability costs nothing at all."""
    state = TableState.empty_two_seat()
    put_in_play(state, holding("probe", printed_id="test_bows_to_act"))
    session = EngineSession.start(state, PlayerId.P1)
    assert ActivateAbility("probe") in session.legal_actions(PlayerId.P1)

    session.game.table.cards_by_id["probe"].bow()

    assert ActivateAbility("probe") not in session.legal_actions(PlayerId.P1)


def test_a_tireless_ability_survives_its_card_being_bowed():
    """The one exception: "an ability with the Tireless keyword may be used even if the card it is
    on is bowed" (CR, Tireless)."""
    state = TableState.empty_two_seat()
    put_in_play(state, holding("probe", printed_id="test_acts_while_bowed"))
    session = EngineSession.start(state, PlayerId.P1)
    session.game.table.cards_by_id["probe"].bow()

    assert ActivateAbility("probe") in session.legal_actions(PlayerId.P1)


for _probe, _tireless in (("test_absent_probe", False), ("test_absent_tireless_probe", True)):
    register_ability(
        _probe,
        Ability(
            timings=(ActionTiming.OPEN,),
            label="Open: absent probe",
            cost=no_cost,
            targets=itself,
            effects=lambda game, source, target: [],
            all_targets=True,
            battle=frozenset({BattleDesignator.ABSENT}),
            tireless=_tireless,
        ),
    )


def test_a_bowed_card_earns_its_seat_no_absent_opportunity():
    """Absent decides whether a seat with no presence is offered the opportunity at all. A bowed
    card's ability cannot be used, so it is no reason to open one."""
    state = TableState.empty_two_seat()
    put_in_play(state, holding("probe", printed_id="test_absent_probe"))
    session = EngineSession.start(state, PlayerId.P1)
    assert has_absent_ability(session.game, PlayerId.P1)

    session.game.table.cards_by_id["probe"].bow()

    assert not has_absent_ability(session.game, PlayerId.P1)


def test_a_bowed_tireless_card_still_earns_the_absent_opportunity():
    state = TableState.empty_two_seat()
    put_in_play(state, holding("probe", printed_id="test_absent_tireless_probe"))
    session = EngineSession.start(state, PlayerId.P1)
    session.game.table.cards_by_id["probe"].bow()

    assert has_absent_ability(session.game, PlayerId.P1)
