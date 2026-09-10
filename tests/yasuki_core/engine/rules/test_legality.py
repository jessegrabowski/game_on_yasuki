import pytest

from yasuki_core import ruleset
from yasuki_core.engine.players import PlayerId
from yasuki_core.engine.table import TableState, ZoneKey, ZoneRole
from yasuki_core.game_pieces.constants import Side
from yasuki_core.game_pieces.cards import L5RCard
from yasuki_core.game_pieces.prints import (
    FatePrint,
    HoldingPrint,
    PersonalityPrint,
    SenseiPrint,
    StrongholdPrint,
)
from yasuki_core.engine.rules.vocabulary.actions import (
    ActionTiming,
    ActivateAbility,
    Legacy,
    Pass,
    Recruit,
)
from yasuki_core.engine.rules.state import GameState
from yasuki_core.engine.rules.vocabulary.decisions import (
    DecisionResponse,
)
from yasuki_core.engine.rules import legality
from yasuki_core.engine.session import EngineSession

from tests.yasuki_core.engine.builders import (
    attachment,
    end_phase,
    holding,
    personality,
    put_in_play,
    register,
)


import numpy as np

from dataclasses import replace

from yasuki_core.engine.rules.abilities.costs import no_cost
from yasuki_core.engine.rules.abilities.model import Ability, CardLocation, itself
from yasuki_core.engine.rules.abilities.registry import (
    _ABILITIES,
    ability_for,
    register_ability,
)
from yasuki_core.engine.rules.vocabulary.actions import (
    BattleDesignator,
)
from yasuki_core.engine.rules.effects import AdjustCounter
from yasuki_core.engine.rules.log import replay
from yasuki_core.engine.rules.legality import activatable, has_absent_ability
from yasuki_core.game_pieces.constants import AttachmentType
from yasuki_core.game_pieces.counters import WEALTH

from tests.yasuki_core.engine.builders import (
    attached,
    province_card,
)
from yasuki_core.engine.rules.vocabulary.actions import (
    Cycle,
    DynastyDiscard,
)
from yasuki_core.bots.agents import make_agent
from yasuki_core.bots.policies import make_policy
from yasuki_core.engine.runner import Controls, run_game
from yasuki_core.game_setup import build_state_from_deck
from tests.yasuki_core.db_guard import requires_db
from yasuki_core.engine.rules.rulebook import recruit
from yasuki_core.engine.rules.turn import sequence

DECK = "src/yasuki_gui/assets/decks/spider_oni_control.yaml"


def _board():
    """P1 with three gold producers and two face-up Province Holdings — enough that the Dynasty
    phase offers several Recruits and a Discard for each, so narrowing to one card is observable."""
    state = TableState.empty_two_seat()
    put_in_play(state, holding("sh", printed_id="plain_stronghold", gold_production=5))
    put_in_play(
        state, holding("millet", printed_id="millet_farm", keywords=("Farm",), gold_production=1)
    )
    put_in_play(
        state, holding("farm", printed_id="plain_farm", keywords=("Farm",), gold_production=2)
    )
    province_card(state, "cheap", printed_id="plain_holding", gold_cost=1, index=0)
    province_card(state, "dear", printed_id="other_holding", gold_cost=3, index=1)
    return EngineSession.start(state, PlayerId.P1)


def _dynasty(session):
    end_phase(session)
    end_phase(session)
    return session


# Well-formed actions naming a card no board holds — never legal anywhere.
UNKNOWN_CARD = (
    Recruit("nonexistent"),
    DynastyDiscard("nonexistent"),
    ActivateAbility("nonexistent"),
)

# Plus one that names a real card in a mode it does not offer. Tied to _board's ids, so it only
# means anything against that fixture.
NEVER_LEGAL = (*UNKNOWN_CARD, Recruit("cheap", proclaim=True))  # a Holding cannot be Proclaimed


@pytest.mark.parametrize(
    "open_phase", [_board, lambda: _dynasty(_board())], ids=["action", "dynasty"]
)
def test_is_legal_accepts_exactly_what_the_enumeration_offers(open_phase):
    # is_legal and legal_actions answer the same question by different routes, so the failure worth
    # guarding is drift between them.
    session = open_phase()
    offered = legality.legal_actions(session.game, PlayerId.P1)

    assert offered, "fixture should offer something in this phase"
    for action in offered:
        assert legality.is_legal(session.game, PlayerId.P1, action), action
    for action in NEVER_LEGAL:
        assert not legality.is_legal(session.game, PlayerId.P1, action), action


def test_an_action_with_no_legality_rule_raises():
    # Action is a closed union and every member is handled, so this is only reachable by adding one
    # without a rule here — which would otherwise read as a rules bug rather than a missing case.
    game = _board().game

    with pytest.raises(ValueError, match="no legality rule"):
        legality.is_legal(game, PlayerId.P1, object())


def test_is_legal_rejects_an_action_belonging_to_another_phase():
    action_phase = _board()
    dynasty = _dynasty(_board())

    assert not legality.is_legal(action_phase.game, PlayerId.P1, Recruit("cheap"))
    assert not legality.is_legal(action_phase.game, PlayerId.P1, DynastyDiscard("cheap"))
    assert legality.is_legal(dynasty.game, PlayerId.P1, Recruit("cheap"))
    assert not legality.is_legal(dynasty.game, PlayerId.P1, Cycle())


def test_is_legal_rejects_every_action_from_the_seat_that_is_not_active():
    session = _dynasty(_board())

    assert not legality.is_legal(session.game, PlayerId.P2, Pass())
    assert not legality.is_legal(session.game, PlayerId.P2, Recruit("cheap"))


def test_is_legal_rejects_every_action_while_a_decision_is_pending():
    session = _board()
    session.act(PlayerId.P1, ActivateAbility("millet"))

    assert session.game.awaiting_decision
    assert not legality.is_legal(session.game, PlayerId.P1, Pass())


@requires_db
def test_is_legal_and_the_enumeration_agree_across_a_driven_game():
    # The fixtures above are hand-built and shallow. This walks real boards — refills, bowed
    # producers, spent gold, a used Legacy — and checks the two never diverge on any of them.
    table, first = build_state_from_deck(DECK, rng=np.random.default_rng(11))
    session = EngineSession.start(table, first, seed=11)
    controls = {seat: Controls(make_policy("economic"), make_agent("paying")) for seat in PlayerId}

    checked = 0
    for _ in run_game(session, controls, turn_limit=8):
        for seat in PlayerId:
            offered = legality.legal_actions(session.game, seat)
            for action in offered:
                assert legality.is_legal(session.game, seat, action), (seat, action)
            for action in (*UNKNOWN_CARD, Legacy(), Cycle()):
                if action not in offered:
                    assert not legality.is_legal(session.game, seat, action), (seat, action)
            checked += len(offered)

    assert checked > 100, f"only {checked} actions checked — the walk is not exercising much"


def test_gold_reach_holds_a_target_independent_producer_in_its_fixed_part():
    session = _board()
    game = session.game

    fixed, variable = legality.gold_reach(game, PlayerId.P1)

    assert variable == ()
    assert fixed == 5 + 1 + 2


def test_gold_reach_counts_a_bow_time_boost_the_seat_could_opt_into():
    # Outlying Farms yields 2 more if the seat destroys it as it bows. That is optional, so it does
    # not change what the producer makes — but it does change what the seat can reach, which is what
    # decides whether a Recruit is offered at all. `maximum_gold_production` is where that lives.
    state = TableState.empty_two_seat()
    put_in_play(state, holding("outlying", printed_id="outlying_farms", gold_production=3))
    game = EngineSession.start(state, PlayerId.P1).game

    fixed, variable = legality.gold_reach(game, PlayerId.P1)

    assert variable == ()
    assert fixed == 3 + 2


def test_gold_reach_leaves_a_producer_that_reads_its_target_variable():
    # Jade Works yields +2 when paying for a Jade card, so its yield cannot be settled until the
    # purchase is known — the whole reason for the split.
    state = TableState.empty_two_seat()
    put_in_play(state, holding("jade", printed_id="jade_works", gold_production=2))
    put_in_play(state, holding("farm", printed_id="plain_farm", gold_production=3))
    province_card(state, "jadecard", printed_id="plain_holding", keywords=("Jade",), gold_cost=1)
    province_card(state, "plain", printed_id="other_holding", gold_cost=1, index=1)
    game = EngineSession.start(state, PlayerId.P1).game

    fixed, variable = legality.gold_reach(game, PlayerId.P1)

    assert fixed == 3
    assert [card.id for card in variable] == ["jade"]
    assert legality.reachable_gold(game, PlayerId.P1, game.table.cards_by_id["jadecard"]) == 3 + 4
    assert legality.reachable_gold(game, PlayerId.P1, game.table.cards_by_id["plain"]) == 3 + 2


@pytest.mark.parametrize("card_id", ["cheap", "dear"])
def test_reachable_gold_ignores_the_target_when_no_producer_reads_it(card_id):
    # reachable_gold is public and used outside legality, so the split has to stay invisible through
    # it. With nothing in the variable half, every candidate must reach the same total.
    game = _dynasty(_board()).game
    card = game.table.cards_by_id[card_id]

    assert legality.reachable_gold(game, PlayerId.P1, card) == 5 + 1 + 2


def test_a_recruit_reachable_only_by_a_self_grant_is_still_offered():
    """The sentinel for the whole projection. A card that can raise its own yield makes purchases
    legal that its printed production cannot reach, and withholding one is silent: the action simply
    is not in the list, the board gives no reason, and a policy never sees it."""
    state = TableState.empty_two_seat()
    put_in_play(state, holding("outlying", printed_id="outlying_farms", gold_production=2))
    session = EngineSession.start(state, PlayerId.P1)
    province_card(session.game, "target", seat=PlayerId.P1, gold_cost=4)
    end_phase(session)
    end_phase(session)

    # Printed 2 against a cost of 4; only the grant reaches it.
    assert Recruit("target") in session.legal_actions(PlayerId.P1)


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


def test_a_spell_on_a_shugenja_may_be_cast():
    state = TableState.empty_two_seat()
    caster = put_in_play(state, personality("caster", keywords=("Shugenja",)))
    attached(
        state,
        attachment("spell", attachment_type=AttachmentType.SPELL, printed_id="test_acts_from_play"),
        caster.id,
    )
    session = EngineSession.start(state, PlayerId.P1)

    offered = activatable(session.game, PlayerId.P1, frozenset({ActionTiming.OPEN}))

    assert [card.id for card, _ in offered] == ["spell"]


def test_a_spell_is_not_cast_from_a_personality_who_is_no_shugenja():
    """ "Their abilities can only be used ('cast') if attached to a Shugenja" (CR, Spell). Attaching
    is checked when the Spell lands; this is the same rule read again at the moment of casting,
    which is what a Personality who stops being a Shugenja needs."""
    state = TableState.empty_two_seat()
    bushi = put_in_play(state, personality("bushi", keywords=("Bushi",)))
    attached(
        state,
        attachment("spell", attachment_type=AttachmentType.SPELL, printed_id="test_acts_from_play"),
        bushi.id,
    )
    session = EngineSession.start(state, PlayerId.P1)

    assert activatable(session.game, PlayerId.P1, frozenset({ActionTiming.OPEN})) == []


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
            hits_every_target=True,
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
            hits_every_target=True,
            battle_designators=frozenset({BattleDesignator.ABSENT}),
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


def _game_with_stronghold_clan(clan: str | None) -> GameState:
    state = TableState.empty_two_seat()
    put_in_play(
        state,
        L5RCard.of(
            StrongholdPrint,
            id="P1-SH",
            name="SH",
            side=Side.STRONGHOLD,
            owner=PlayerId.P1,
            clan=clan,
        ),
    )
    return GameState.start(state, PlayerId.P1)


def test_recruit_cost_adds_the_off_clan_surcharge_only_for_a_different_clan():
    game = _game_with_stronghold_clan("crab")
    same = L5RCard.of(
        HoldingPrint,
        id="h1",
        name="H",
        side=Side.DYNASTY,
        owner=PlayerId.P1,
        gold_cost=4,
        clan="crab",
    )
    other = L5RCard.of(
        HoldingPrint,
        id="h2",
        name="H",
        side=Side.DYNASTY,
        owner=PlayerId.P1,
        gold_cost=4,
        clan="crane",
    )

    assert legality.recruit_cost(game, same) == 4
    assert legality.recruit_cost(game, other) == 4 + ruleset.ACTIVE.off_clan_surcharge


def test_recruit_cost_charges_no_surcharge_when_clan_alignment_is_unknown():
    game = _game_with_stronghold_clan(None)
    holding = L5RCard.of(
        HoldingPrint,
        id="h",
        name="H",
        side=Side.DYNASTY,
        owner=PlayerId.P1,
        gold_cost=4,
        clan="crane",
    )
    assert legality.recruit_cost(game, holding) == 4  # no Stronghold clan to compare against


def _personality(clans: tuple[str, ...], **kwargs) -> L5RCard:
    return L5RCard.of(
        PersonalityPrint,
        id="p",
        name="P",
        side=Side.DYNASTY,
        owner=PlayerId.P1,
        gold_cost=5,
        clan=clans[0] if clans else None,
        clans=clans,
        **kwargs,
    )


def test_recruit_cost_reads_every_listed_clan_not_just_the_first():
    # Bayushi Aramoro is printed Ninja and Scorpion; the alignment that matters is second in the list.
    game = _game_with_stronghold_clan("Scorpion")
    aramoro = _personality(("Ninja", "Scorpion"))
    assert legality.recruit_cost(game, aramoro) == 5


def test_recruit_cost_treats_naga_and_akasha_as_one_alignment():
    game = _game_with_stronghold_clan("Naga")
    akasha_personality = _personality(("Akasha",))
    assert legality.recruit_cost(game, akasha_personality) == 5


def test_recruit_cost_charges_no_surcharge_for_an_unaligned_personality():
    game = _game_with_stronghold_clan("Scorpion")
    # A clan name that is not a legal alignment (a minor clan) leaves the card unaligned.
    assert legality.recruit_cost(game, _personality(("Fox",))) == 5
    assert legality.recruit_cost(game, _personality(())) == 5


def test_recruit_cost_surcharges_a_personality_aligned_to_another_clan():
    game = _game_with_stronghold_clan("Scorpion")
    assert (
        legality.recruit_cost(game, _personality(("Crane",)))
        == 5 + ruleset.ACTIVE.off_clan_surcharge
    )


def test_a_stronghold_printing_several_clans_surcharges_none_of_them():
    """A Stronghold is a card, and a card may print more than one clan (the debug fixture prints all
    ten). Every alignment it carries is one the seat plays, so none of them is off-clan."""
    state = TableState.empty_two_seat()
    put_in_play(
        state,
        L5RCard.of(
            StrongholdPrint,
            id="P1-SH",
            name="SH",
            side=Side.STRONGHOLD,
            owner=PlayerId.P1,
            clans=("Lion", "Crane"),
        ),
    )
    game = GameState.start(state, PlayerId.P1)

    assert legality.recruit_cost(game, _personality(("Lion",))) == 5
    assert legality.recruit_cost(game, _personality(("Crane",))) == 5
    assert (
        legality.recruit_cost(game, _personality(("Scorpion",)))
        == 5 + ruleset.ACTIVE.off_clan_surcharge
    )


def test_a_stronghold_with_no_legal_alignment_neither_surcharges_nor_proclaims():
    # A Shadowlands / minor-clan Stronghold has no legal Clan Alignment, so it has nothing to compare
    # against: an aligned Personality costs face value and none can be Proclaimed.
    game = _game_with_stronghold_clan("Shadowlands")
    assert legality.recruit_cost(game, _personality(("Crab",))) == 5
    assert not legality.can_proclaim(game, _personality(("Crab",)))


def test_can_proclaim_accepts_any_shared_alignment_of_a_multi_clan_personality():
    doji = _personality(("Crane", "Mantis"))  # a legal Crane/Mantis Personality
    assert legality.can_proclaim(_game_with_stronghold_clan("Crane"), doji)
    assert legality.can_proclaim(_game_with_stronghold_clan("Mantis"), doji)


def test_can_proclaim_rejects_off_clan_and_unaligned_personalities():
    game = _game_with_stronghold_clan("Scorpion")
    assert not legality.can_proclaim(game, _personality(("Crane",)))  # off-clan
    assert not legality.can_proclaim(game, _personality(("Fox",)))  # unaligned (minor clan only)
    assert not legality.can_proclaim(game, _personality(()))  # unaligned (no clan)


def _begun_game_with_sensei(sensei_printed_id: str) -> GameState:
    state = TableState.empty_two_seat()
    put_in_play(
        state,
        L5RCard.of(StrongholdPrint, id="P1-SH", name="SH", side=Side.STRONGHOLD, owner=PlayerId.P1),
    )
    put_in_play(
        state,
        L5RCard.of(
            SenseiPrint,
            id="P1-SE",
            name="Sensei",
            side=Side.FATE,
            owner=PlayerId.P1,
            printed_id=sensei_printed_id,
        ),
    )
    game = GameState.start(state, PlayerId.P1)
    sequence.begin_game(game)
    return game


def test_begin_game_grants_mishimes_ignore_honor_requirements_waiver():
    game = _begun_game_with_sensei("mishime_sensei")
    assert game.table.seats[PlayerId.P1].ignores_honor_requirements is True


def _discount_game(*, clan=None, first_player=PlayerId.P1, in_play=()):
    state = TableState.empty_two_seat()
    put_in_play(
        state,
        L5RCard.of(
            StrongholdPrint,
            id="P1-SH",
            name="SH",
            side=Side.STRONGHOLD,
            owner=PlayerId.P1,
            clan=clan,
        ),
    )
    for card in in_play:
        put_in_play(state, card)
    return GameState.start(state, first_player)


def _holding(printed_id: str, gold_cost: int, clan: str | None = None) -> L5RCard:
    return L5RCard.of(
        HoldingPrint,
        id=f"{printed_id}-inst",
        name="H",
        side=Side.DYNASTY,
        owner=PlayerId.P1,
        printed_id=printed_id,
        gold_cost=gold_cost,
        clan=clan,
    )


def test_colonial_farm_discounts_one_for_a_lion_player():
    farm = _holding("colonial_farm", gold_cost=6)
    assert legality.recruit_cost(_discount_game(clan="Lion"), farm) == 5
    assert legality.recruit_cost(_discount_game(clan="Crab"), farm) == 6  # no discount off-clan


def test_fantastic_gardens_discounts_two_for_a_crane_player():
    gardens = _holding("fantastic_gardens", gold_cost=7)
    assert legality.recruit_cost(_discount_game(clan="Crane"), gardens) == 5
    assert legality.recruit_cost(_discount_game(clan="Lion"), gardens) == 7


def test_moto_traders_discounts_with_another_merchant_caravan_in_play():
    caravan = L5RCard.of(
        HoldingPrint,
        id="mc",
        name="C",
        side=Side.DYNASTY,
        owner=PlayerId.P1,
        keywords=("Merchant Caravan",),
    )
    traders = _holding("moto_traders", gold_cost=5)
    assert legality.recruit_cost(_discount_game(in_play=(caravan,)), traders) == 4
    assert legality.recruit_cost(_discount_game(), traders) == 5


def test_shrine_of_courtesy_discounts_three_when_you_went_second():
    shrine = _holding("shrine_of_courtesy", gold_cost=4)
    assert (
        legality.recruit_cost(_discount_game(first_player=PlayerId.P2), shrine) == 1
    )  # P1 went second
    assert legality.recruit_cost(_discount_game(first_player=PlayerId.P1), shrine) == 4


def test_recruit_discount_floors_the_cost_at_zero():
    cheap = _holding("shrine_of_courtesy", gold_cost=2)  # a -3 discount would go negative
    assert legality.recruit_cost(_discount_game(first_player=PlayerId.P2), cheap) == 0


def test_recruit_discount_stacks_additively_with_the_off_clan_surcharge():
    caravan = L5RCard.of(
        HoldingPrint,
        id="mc",
        name="C",
        side=Side.DYNASTY,
        owner=PlayerId.P1,
        keywords=("Merchant Caravan",),
    )
    game = _discount_game(clan="Crab", in_play=(caravan,))
    traders = _holding(
        "moto_traders", gold_cost=5, clan="Unicorn"
    )  # off-clan from the Crab stronghold
    # Both apply and sum: +2 off-clan surcharge, -1 Merchant Caravan discount.
    assert legality.recruit_cost(game, traders) == 5 + ruleset.ACTIVE.off_clan_surcharge - 1


def test_recruit_rejects_invest_and_proclaim_together():
    # legal_actions never offers the pair, but a decoded tape could still carry it; recruit must
    # fail loudly rather than silently drop the Proclaim.
    game = _discount_game(clan="Crab")
    holding = register(game.table, _holding("teahouse", gold_cost=2))
    with pytest.raises(ValueError, match="Invest and Proclaim"):
        recruit.recruit(game, holding.id, invest=True, proclaim=True)
