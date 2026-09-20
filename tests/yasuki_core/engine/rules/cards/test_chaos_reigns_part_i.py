import pytest

from yasuki_core.engine.players import PlayerId, Rulebook
from yasuki_core.engine.rules import legality
from yasuki_core.engine.rules.turn import sequence
from yasuki_core.engine import ops
from yasuki_core.engine.rules.rulebook.favor_payment import DISCARD_THE_FAVOR, favor_payment_options
from yasuki_core.engine.rules.rulebook.favor_payment import is_favor_action
from yasuki_core.engine.rules.abilities.costs import no_cost
from yasuki_core.engine.rules.abilities.model import Ability, itself
from yasuki_core.engine.rules.rulebook.equip import may_attach
from yasuki_core.engine.rules.abilities.registry import _ABILITIES, ability_for, register_ability
from yasuki_core.engine.rules.board.queries import owned_personalities
from yasuki_core.engine.rules.vocabulary.actions import (
    ActionTiming,
    ActivateAbility,
    DynastyDiscard,
    Pass,
    PlayInterrupt,
    PlayStrategy,
    UseFavorAbility,
)
from yasuki_core.engine.rules.vocabulary.decisions import DecisionResponse
from yasuki_core.engine.rules.effects import Bow, Discard, DiscardFavor, TakeFavor
from yasuki_core.engine.rules.vocabulary.game_events import CardDiscarded
from yasuki_core.engine.rules.turn.action_sequence import submit
from yasuki_core.engine.rules.state import GameState
from yasuki_core.engine.rules.battle.records import AttackPhase, BattlefieldInfo
from yasuki_core.engine.rules.turn.structure import BATTLE_SEGMENT_TIMINGS, ActionRound, RoundKind
from yasuki_core.engine.rules.vocabulary.segments import BattleSegment
from yasuki_core.engine.rules.triggers import resolve_effects
from yasuki_core.engine.session import EngineSession
from yasuki_core.engine.table import Location, TableState, ZoneKey, ZoneRole, location_of
from yasuki_core.engine.rules.vocabulary import keywords
from yasuki_core.game_pieces.constants import IMPERIAL_FAVOR_ID, Side
from yasuki_core.game_pieces.cards import L5RCard
from yasuki_core.game_pieces.prints import ActionPrint, FatePrint, StrongholdPrint

from tests.yasuki_core.engine.rules.conftest import probe_ability
from tests.yasuki_core.engine.rules.test_interrupts import DEFENDER, _fear_announced
from tests.yasuki_core.engine.builders import (
    pay,
    attached,
    attachment,
    end_phase,
    fate_card,
    holding,
    personality,
    province_card,
    put_in_play,
    register,
    wind as wind_card,
    two_seat_game,
)

P1, P2 = PlayerId.P1, PlayerId.P2
PROBE = "fate_discard_probe"


@pytest.fixture(autouse=True)
def _clear_probe_registration():
    """The ability registry is module-global, so a probe left behind would follow later tests."""
    yield
    _ABILITIES.pop(PROBE, None)


def _discard_from_hand(game, source, target):
    """Discard the first Fate card its controller holds."""
    hand = game.table.zones[ZoneKey(source.owner, ZoneRole.HAND)]
    return [Discard(hand.cards[0].id, source.owner)] if hand.cards else []


def _register_probe() -> None:
    """Register an Open action that discards a Fate card from its controller's hand.

    Nothing shipped discards a Fate card, and the Caravansary answers only an action that did, so
    the action it answers is built here rather than borrowed from a real card.
    """
    register_ability(
        PROBE,
        Ability(
            timings=(ActionTiming.OPEN,),
            repeatable=True,
            label="Open: discard a card from hand",
            cost=no_cost,
            targets=itself,
            effects=_discard_from_hand,
            hits_every_target=True,
        ),
    )


def _hand_a_fate_card(table, seat, card_id):
    register(table, fate_card(card_id, seat))
    table.zones[ZoneKey(seat, ZoneRole.HAND)].add(table.cards_by_id[card_id])


# --- Caravansary ---


def _caravansary_game(*, wealth=0, discarder=P1, in_hand=1):
    """The Caravansary in play, beside ``discarder``\'s probe and the Fate card it will discard."""
    game = two_seat_game()
    caravansary = put_in_play(
        game,
        holding("caravansary", printed_id="caravansary", name="Caravansary", gold_production=2),
    )
    if wealth:
        caravansary.adjust_counter("wealth", wealth)
    put_in_play(game, holding("probe", printed_id=PROBE, owner=discarder, name="Probe"))
    for index in range(in_hand):
        _hand_a_fate_card(game.table, discarder, f"spare-fate-{index}")
    _register_probe()
    return EngineSession.start(game.table, P1)


def _step_is_open(session) -> bool:
    return bool(session.game.round_stack)


def test_the_caravansary_is_offered_after_your_action_discards_a_fate_card():
    session = _caravansary_game()

    session.act(P1, ActivateAbility("probe"))

    assert _step_is_open(session)
    assert ActivateAbility("caravansary") in session.legal_actions(P1)


def test_taking_the_response_banks_a_wealth_token():
    session = _caravansary_game()
    session.act(P1, ActivateAbility("probe"))

    session.act(P1, ActivateAbility("caravansary"))

    assert session.game.table.cards_by_id["caravansary"].counters == {"wealth": 1}


def test_passing_the_response_leaves_the_token_unclaimed():
    """A Response is an action: declining the Step is declining the token."""
    session = _caravansary_game()
    session.act(P1, ActivateAbility("probe"))

    session.act(P1, Pass())

    assert session.game.table.cards_by_id["caravansary"].counters == {}


def test_the_response_answers_one_discard_once():
    """Nothing else rations it. It costs no bow, so the Step itself does."""
    session = _caravansary_game()
    session.act(P1, ActivateAbility("probe"))

    session.act(P1, ActivateAbility("caravansary"))

    assert ActivateAbility("caravansary") not in session.legal_actions(P1)


def test_a_later_step_in_the_same_turn_does_not_offer_the_response_again():
    """The Response prints no Repeatable, so it is once per turn (CR, Using Abilities 0.3): the
    second discarding action opens a Step the Caravansary has nothing left to say in."""
    session = _caravansary_game(in_hand=2)
    session.act(P1, ActivateAbility("probe"))
    session.act(P1, ActivateAbility("caravansary"))
    session.act(P2, Pass())
    session.act(P1, Pass())  # both pass, so the Step closes
    session.act(P2, Pass())  # priority back around to P1

    session.act(P1, ActivateAbility("probe"))

    assert ActivateAbility("caravansary") not in session.legal_actions(P1)


def test_an_opponents_discard_offers_you_nothing():
    """ "If the action was yours": the Caravansary reads whose action it was, not merely that a
    Fate card reached a pile."""
    session = _caravansary_game(discarder=P2)

    session.act(P1, Pass())
    session.act(P2, ActivateAbility("probe"))

    assert not _step_is_open(session)


def test_a_dynasty_discard_offers_nothing():
    game = two_seat_game()
    put_in_play(
        game,
        holding("caravansary", printed_id="caravansary", name="Caravansary", gold_production=2),
    )
    province_card(game, "spare-dynasty", seat=P1, name="Spare")
    session = EngineSession.start(game.table, P1)
    end_phase(session)  # Action -> Battle
    end_phase(session)  # Battle -> Dynasty, where a Province card may be discarded

    session.act(P1, DynastyDiscard("spare-dynasty"))

    assert not _step_is_open(session)


def test_a_discard_no_player_made_offers_nothing():
    """Trimming to the maximum hand size is a step of the turn rather than an action (CR, Drawing
    and Discarding Fate Cards), so "if the action was yours" has no action to claim, and turn
    structure opens no Response Step at all."""
    session = _caravansary_game()
    game = session.game

    sequence.apply_discard(game, P1, ("spare-fate-0",))

    assert game.action_events[-1] == CardDiscarded(
        "spare-fate-0", Side.FATE, Rulebook.MAXIMUM_HAND_SIZE, from_hand_or_deck=True
    )
    assert not _step_is_open(session)


def test_a_caravansary_is_not_offered_for_the_discard_of_your_own_interrupt():
    # Okura is P2's Interrupt to P1's Fear, and its discard happens inside the Interrupt step: it
    # is P2's doing, not the action's, so P1's action did not discard P2's Fate card.
    session = _fear_announced({}, strategies=(("okura", "okura_is_released", DEFENDER),))
    put_in_play(
        session.game,
        holding("caravansary", printed_id="caravansary", owner=DEFENDER, gold_production=2),
    )
    session.act(DEFENDER, PlayInterrupt("okura"))
    pay(session, DEFENDER)

    assert session.game.round.kind is not RoundKind.RESPONSE
    assert not any(isinstance(event, CardDiscarded) for event in session.game.action_events)


def test_a_caravansary_already_at_three_is_not_offered():
    session = _caravansary_game(wealth=3)

    session.act(P1, ActivateAbility("probe"))

    assert not _step_is_open(session)


def _oaths_game(*, holds_favor: bool = True, yojimbo: bool = False) -> GameState:
    """A battle each side has a unit in, so the Rule of Presence is what lets P1 act at all, with
    an enemy Personality to send home."""
    game = GameState.start(TableState.empty_two_seat(), PlayerId.P1, seed=0)
    game.table.creatable_tokens[IMPERIAL_FAVOR_ID] = FatePrint(
        name="The Imperial Favor", side=Side.FATE, printed_id=IMPERIAL_FAVOR_ID
    )
    game.attack = AttackPhase(
        attacker=PlayerId.P1,
        defender=PlayerId.P2,
        battlefields=(BattlefieldInfo(province=ZoneKey(PlayerId.P2, ZoneRole.PROVINCE, 0)),),
        current=0,
    )
    for card_id, owner in (("guard", PlayerId.P2), ("bushi", PlayerId.P1)):
        unit = put_in_play(game, personality(card_id, owner=owner))
        ops.set_location(game.table, unit, Location.at_battlefield(0))
    if yojimbo:
        put_in_play(game, personality("kakita", keywords=(keywords.YOJIMBO,)))
    if holds_favor:
        TakeFavor(PlayerId.P1).perform(game)
    return game


def _oaths(game: GameState):
    """Honor Your Oaths in its controller's hand, where a Strategy is played from, and its
    ability."""
    card = register(
        game.table,
        L5RCard.of(
            ActionPrint,
            id="oaths",
            name="Honor Your Oaths",
            printed_id="honor_your_oaths",
            side=Side.FATE,
            owner=PlayerId.P1,
            gold_cost=0,
        ),
    )
    game.table.zones[ZoneKey(PlayerId.P1, ZoneRole.HAND)].add(card)
    return card, ability_for(game, card, None)


def test_honor_your_oaths_reads_the_favor_without_spending_it():
    """CRI: "Political Battle: If you control :favor:, move home a target enemy Personality." The
    condition is a check, not a cost, so the Favor is still yours afterward."""
    game = _oaths_game()
    source, ability = _oaths(game)

    resolve_effects(game, ability.effects(game, source, game.table.cards_by_id["guard"]))

    assert location_of(game.table, game.table.cards_by_id["guard"]).is_home
    assert game.favor_holder is PlayerId.P1, "checking the Favor does not spend it"


def test_honor_your_oaths_is_not_offered_without_the_favor():
    """No Favor, no first clause, and the enemy Personality is the action's only target."""
    game = _oaths_game(holds_favor=False)
    source, ability = _oaths(game)

    assert ability.targets(game, source) == []


def test_discarding_the_favor_for_the_second_clause_is_not_a_favor_cost():
    """The Favor icon is a cost only in the cost block (ShE datasheet, The Favor Icon). Here it is
    in the effect text, so a card watching for a Favor action sees none."""
    game = _oaths_game(yojimbo=True)
    source, ability = _oaths(game)
    game.action = ActivateAbility(source.id)
    game.action_seat = PlayerId.P1
    estate = put_in_play(
        game,
        L5RCard.of(
            StrongholdPrint,
            id="estate",
            name="The Palatial Estate of the Crane",
            printed_id="the_palatial_estate_of_the_crane",
            side=Side.DYNASTY,
            owner=PlayerId.P1,
        ),
    )

    resolve_effects(game, ability.effects(game, source, game.table.cards_by_id["guard"]))
    submit(game, DecisionResponse(choices=(DISCARD_THE_FAVOR,)))

    assert game.table.seats[PlayerId.P1].honor == 1
    assert game.favor_holder is None
    assert not is_favor_action(game)
    assert ability_for(game, estate, None).targets(game, estate) == []


def test_nothing_may_discard_the_favor_in_the_seats_place():
    """ "Discarding the Favor can happen only if you control it" (CR, Imperial Favor). Manjodh pays
    Favor costs, and this is not one, so without the Favor only the Yojimbo is offered."""
    game = _oaths_game(holds_favor=False, yojimbo=True)
    source, ability = _oaths(game)
    put_in_play(game, personality("manjodh", printed_id="manjodh"))

    resolve_effects(game, ability.effects(game, source, game.table.cards_by_id["guard"]))

    assert game.pending is not None
    assert DISCARD_THE_FAVOR not in game.pending.candidates
    assert "Bow your target Yojimbo" in game.pending.candidates


def test_bowing_the_yojimbo_instead_leaves_the_favor_untouched():
    game = _oaths_game(yojimbo=True)
    source, ability = _oaths(game)
    game.action = ActivateAbility(source.id)

    resolve_effects(game, ability.effects(game, source, game.table.cards_by_id["guard"]))
    submit(game, DecisionResponse(choices=("Bow your target Yojimbo",)))
    submit(game, DecisionResponse(choices=("kakita",)))

    assert game.table.cards_by_id["kakita"].bowed
    assert game.table.seats[PlayerId.P1].honor == 1
    assert game.favor_holder is PlayerId.P1, "the Yojimbo paid, so the Favor stayed"
    assert not is_favor_action(game)


def test_the_second_clause_can_be_declined():
    """ "You may", so the seat that wants only the first clause is not made to pay for the rest."""
    game = _oaths_game(yojimbo=True)
    source, ability = _oaths(game)

    resolve_effects(game, ability.effects(game, source, game.table.cards_by_id["guard"]))
    submit(game, DecisionResponse(choices=("Take neither",)))

    assert game.table.seats[PlayerId.P1].honor == 0
    assert game.favor_holder is PlayerId.P1
    assert not game.table.cards_by_id["kakita"].bowed


def test_honor_your_oaths_is_offered_from_hand_during_a_battle():
    """A Strategy is played out of hand, so its ability has to say it acts from there. The default
    is the battlefield, where a card in hand never is, and the action would simply never appear."""
    game = _oaths_game()
    _oaths(game)
    game.round = ActionRound(
        timings=BATTLE_SEGMENT_TIMINGS[BattleSegment.COMBAT],
        priority=PlayerId.P1,
        kind=RoundKind.BATTLE_SEGMENT,
    )

    assert PlayStrategy("oaths") in legality.legal_actions(game, PlayerId.P1)


def test_a_bowed_yojimbo_cannot_pay_for_the_second_clause():
    """Bowing him is the price, and a card already bowed cannot pay a bow cost (CR, Costs). With no
    other Yojimbo the option is not offered at all."""
    game = _oaths_game(yojimbo=True)
    source, ability = _oaths(game)
    game.table.cards_by_id["kakita"].bow()

    resolve_effects(game, ability.effects(game, source, game.table.cards_by_id["guard"]))

    assert game.pending is not None
    assert "Bow your target Yojimbo" not in game.pending.candidates


def test_the_second_clause_is_not_offered_when_neither_half_can_be_paid():
    """The targets are chosen at step C and the action resolves at step E, so an Interrupt between
    them can take the Favor away, leaving a seat with no Yojimbo nothing to be asked about, and the
    first clause to resolve alone."""
    game = _oaths_game()
    source, ability = _oaths(game)
    target = game.table.cards_by_id["guard"]
    DiscardFavor(PlayerId.P1).perform(game)

    resolve_effects(game, ability.effects(game, source, target))

    assert location_of(game.table, target).is_home
    assert game.pending is None, "nothing to ask"


def _manjodh_game(*, has_wind: bool = False) -> GameState:
    """Manjodh in play, his controller holding no Favor, so he is the only way to pay one."""
    game = GameState.start(TableState.empty_two_seat(), PlayerId.P1, seed=0)
    put_in_play(game, personality("manjodh", printed_id="manjodh"))
    if has_wind:
        put_in_play(game, wind_card(PlayerId.P1))
    return game


def test_manjodh_pays_a_favor_cost_by_bowing():
    """CRI: "Political Interrupt, :bow:: If you have no Wind, pay the action's :favor: cost."

    Implemented as a payer priced at bowing rather than as the Interrupt he prints, because a cost
    is paid at step B of the Action Sequence and an Interrupt is played at D. The printed window
    opens after the cost it names. The deviation is deliberate and recorded on the handler.
    """
    game = _manjodh_game()

    resolve_effects(game, favor_payment_options(game, PlayerId.P1)["manjodh"])

    assert game.table.cards_by_id["manjodh"].bowed
    assert game.favor_holder is None, "he paid, and nobody held the Favor to begin with"


def test_a_bowed_manjodh_cannot_pay():
    """Bowing him is the price, and a bowed card cannot pay a bow cost (CR, Costs)."""
    game = _manjodh_game()
    game.table.cards_by_id["manjodh"].bow()

    assert favor_payment_options(game, PlayerId.P1) == {}


def test_manjodh_will_not_pay_for_a_player_with_a_wind():
    """ "If you have no Wind": the clause the datasheet's Winds rule explains, since a seat with a
    Wind may not take rulebook Favor actions at all."""
    game = _manjodh_game(has_wind=True)

    assert favor_payment_options(game, PlayerId.P1) == {}


# --- Latest Fashions ---

POLITICAL_PROBE = "probe_political_open_bow_a_personality"
PLAIN_PROBE = "probe_open_bow_a_personality"


def _bow_a_personality(keywords_printed: frozenset[str]) -> Ability:
    return Ability(
        timings=(ActionTiming.OPEN,),
        keywords=keywords_printed,
        label="Open: bow a target Personality",
        cost=no_cost,
        targets=lambda game, source: [card.id for card in owned_personalities(game, source.owner)],
        effects=lambda game, source, target: [Bow(target.id)],
    )


def _fashions_on_doji(*, envoy_probe: str = POLITICAL_PROBE) -> EngineSession:
    """P1's doji wears Latest Fashions and prints a Political Open action. P1's envoy prints
    ``envoy_probe``, which targets a Personality."""
    state = TableState.empty_two_seat()
    put_in_play(state, personality("doji", printed_id=POLITICAL_PROBE))
    put_in_play(state, personality("envoy", printed_id=envoy_probe))
    attached(
        state,
        attachment("kimono", printed_id="latest_fashions", keywords=(keywords.KIMONO,)),
        "doji",
    )
    return EngineSession.start(state, P1)


def test_latest_fashions_gains_honor_after_a_political_action_from_its_wearer():
    with probe_ability(POLITICAL_PROBE, _bow_a_personality(frozenset({keywords.POLITICAL}))):
        session = _fashions_on_doji()
        session.act(P1, ActivateAbility("doji"))
        session.submit(P1, DecisionResponse(("envoy",)))

        session.act(P1, ActivateAbility("kimono"))

        assert session.game.table.seats[P1].honor == 1


def test_latest_fashions_gains_honor_after_a_political_action_targeting_its_wearer():
    with probe_ability(POLITICAL_PROBE, _bow_a_personality(frozenset({keywords.POLITICAL}))):
        session = _fashions_on_doji()
        session.act(P1, ActivateAbility("envoy"))
        session.submit(P1, DecisionResponse(("doji",)))

        assert ActivateAbility("kimono") in session.legal_actions(P1)


def test_latest_fashions_is_not_offered_after_a_plain_action():
    with (
        probe_ability(POLITICAL_PROBE, _bow_a_personality(frozenset({keywords.POLITICAL}))),
        probe_ability(PLAIN_PROBE, _bow_a_personality(frozenset())),
    ):
        session = _fashions_on_doji(envoy_probe=PLAIN_PROBE)
        session.act(P1, ActivateAbility("envoy"))
        session.submit(P1, DecisionResponse(("doji",)))

        assert ActivateAbility("kimono") not in session.legal_actions(P1)


def test_a_personality_wearing_a_kimono_may_not_attach_another():
    game = GameState.start(TableState.empty_two_seat(), P1)
    doji = put_in_play(game, personality("doji"))
    bare = put_in_play(game, personality("bare"))
    attached(game, attachment("silk", keywords=(keywords.KIMONO,)), "doji")
    fashions = attachment("kimono", printed_id="latest_fashions", keywords=(keywords.KIMONO,))

    assert may_attach(game, bare, fashions) is True
    assert may_attach(game, doji, fashions) is False


# --- Shrine to Inari ---


def _bowed_estate_with_shrine(*, shrine_bowed: bool = False) -> EngineSession:
    """P1's Stronghold is the Palatial Estate, bowed, beside a Shrine to Inari. P1 has just paid
    the Favor for a rulebook Favor action, which is what the Estate's Response answers."""
    state = TableState.empty_two_seat()
    state.creatable_tokens[IMPERIAL_FAVOR_ID] = FatePrint(
        name="The Imperial Favor", side=Side.FATE, printed_id=IMPERIAL_FAVOR_ID
    )
    put_in_play(
        state,
        L5RCard.of(
            StrongholdPrint,
            id="estate",
            name="The Palatial Estate of the Crane",
            printed_id="the_palatial_estate_of_the_crane",
            side=Side.DYNASTY,
            owner=P1,
        ),
    )
    put_in_play(state, holding("shrine", printed_id="shrine_to_inari"))
    _hand_a_fate_card(state, P1, "spare")
    session = EngineSession.start(state, P1)
    # Bowed after the game opens, since opening straightens the active seat's board.
    session.game.table.cards_by_id["estate"].bow()
    if shrine_bowed:
        session.game.table.cards_by_id["shrine"].bow()
    TakeFavor(P1).perform(session.game)
    session.act(P1, UseFavorAbility("discard_to_draw"))
    session.submit(P1, DecisionResponse(("spare",)))
    return session


def test_the_shrine_lets_a_bowed_stronghold_use_its_ability():
    session = _bowed_estate_with_shrine()

    assert ActivateAbility("estate") in session.legal_actions(P1)


def test_a_bowed_shrine_grants_nothing():
    session = _bowed_estate_with_shrine(shrine_bowed=True)

    assert ActivateAbility("estate") not in session.legal_actions(P1)
