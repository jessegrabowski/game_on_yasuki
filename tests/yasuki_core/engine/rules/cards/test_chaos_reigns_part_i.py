import pytest

from yasuki_core.engine.players import PlayerId, Rulebook
from yasuki_core.engine.rules import flow, legality
from yasuki_core.engine import ops
from yasuki_core.engine.rules.abilities import (
    DISCARD_THE_FAVOR,
    favor_payers,
    _ABILITIES,
    Ability,
    ability_for,
    is_favor_action,
    itself,
    no_cost,
    register_ability,
)
from yasuki_core.engine.rules.actions import (
    ActionTiming,
    ActivateAbility,
    DynastyDiscard,
    Pass,
    PlayStrategy,
)
from yasuki_core.engine.rules.decisions import DecisionResponse
from yasuki_core.engine.rules.effects import Discard, DiscardFavor, TakeFavor
from yasuki_core.engine.rules.events import CardDiscarded
from yasuki_core.engine.rules.flow import submit
from yasuki_core.engine.rules.state import (
    BATTLE_SEGMENT_TIMINGS,
    ActionRound,
    AttackPhase,
    BattleSegment,
    BattlefieldInfo,
    GameState,
    RoundKind,
)
from yasuki_core.engine.rules.triggers import resolve_effects
from yasuki_core.engine.session import EngineSession
from yasuki_core.engine.table import Location, TableState, ZoneKey, ZoneRole, location_of
from yasuki_core.game_pieces import keywords
from yasuki_core.game_pieces.constants import IMPERIAL_FAVOR_ID, Side
from yasuki_core.game_pieces.cards import L5RCard
from yasuki_core.game_pieces.prints import ActionPrint, FatePrint

from tests.yasuki_core.engine.builders import (
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
            label="Open: discard a card from hand",
            cost=no_cost,
            targets=itself,
            effects=_discard_from_hand,
            all_targets=True,
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
    """Nothing else rations it — it costs no bow — so the Step itself does."""
    session = _caravansary_game()
    session.act(P1, ActivateAbility("probe"))

    session.act(P1, ActivateAbility("caravansary"))

    assert ActivateAbility("caravansary") not in session.legal_actions(P1)


def test_a_later_step_offers_the_response_again():
    """The once-a-Step limit is scoped to the Step, so a second discarding action offers the card
    again rather than spending it for the rest of the turn."""
    session = _caravansary_game(in_hand=2)
    session.act(P1, ActivateAbility("probe"))
    session.act(P1, ActivateAbility("caravansary"))
    session.act(P2, Pass())
    session.act(P1, Pass())  # both pass, so the Step closes
    session.act(P2, Pass())  # priority back around to P1

    session.act(P1, ActivateAbility("probe"))

    assert _step_is_open(session)
    assert ActivateAbility("caravansary") in session.legal_actions(P1)


def test_an_opponents_discard_offers_you_nothing():
    """ "If the action was yours" — the Caravansary reads whose action it was, not merely that a Fate
    card reached a pile."""
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
    flow.advance(session.game)  # Action -> Battle
    flow.advance(session.game)  # Battle -> Dynasty, where a Province card may be discarded

    session.act(P1, DynastyDiscard("spare-dynasty"))

    assert not _step_is_open(session)


def test_a_discard_no_player_made_offers_nothing():
    """Trimming to the maximum hand size is a step of the turn rather than an action (CR, Drawing
    and Discarding Fate Cards), so "if the action was yours" has no action to claim — and turn
    structure opens no Response Step at all."""
    session = _caravansary_game()
    game = session.game

    flow._apply_discard(game, P1, ("spare-fate-0",))

    assert game.action_events[-1] == CardDiscarded(
        "spare-fate-0", Side.FATE, Rulebook.MAXIMUM_HAND_SIZE, from_hand_or_deck=True
    )
    assert not _step_is_open(session)


def test_a_caravansary_already_at_three_is_not_offered():
    session = _caravansary_game(wealth=3)

    session.act(P1, ActivateAbility("probe"))

    assert not _step_is_open(session)


def _oaths_game(*, holds_favor: bool = True, yojimbo: bool = False) -> GameState:
    """A battle each side has a unit in — the Rule of Presence is what lets P1 act at all — with an
    enemy Personality to send home."""
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
    """Honor Your Oaths in its controller's hand, where a Strategy is played from, and its ability."""
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
    return card, ability_for(card, None)


def test_honor_your_oaths_reads_the_favor_without_spending_it():
    """CRI: "Political Battle: If you control :favor:, move home a target enemy Personality." The
    condition is a check, not a cost — the Favor is still yours afterward."""
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


def test_paying_the_favor_for_the_second_clause_makes_it_a_favor_action():
    """ShE datasheet, The Favor Icon: an action with alternate costs is a Favor action only when the
    Favor is the half actually paid."""
    game = _oaths_game(yojimbo=True)
    source, ability = _oaths(game)
    game.action = ActivateAbility(source.id)

    resolve_effects(game, ability.effects(game, source, game.table.cards_by_id["guard"]))
    submit(game, DecisionResponse(choices=(DISCARD_THE_FAVOR,)))

    assert game.table.seats[PlayerId.P1].honor == 1
    assert game.favor_holder is None, "this half of the cost discards it"
    assert is_favor_action(game)


def test_bowing_the_yojimbo_instead_leaves_an_ordinary_action():
    """The same clause paid the other way. The Favor is untouched and no card watching for a Favor
    action sees one."""
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
    """ "You may" — so the seat that wants only the first clause is not made to pay for the rest."""
    game = _oaths_game(yojimbo=True)
    source, ability = _oaths(game)

    resolve_effects(game, ability.effects(game, source, game.table.cards_by_id["guard"]))
    submit(game, DecisionResponse(choices=("Take neither",)))

    assert game.table.seats[PlayerId.P1].honor == 0
    assert game.favor_holder is PlayerId.P1
    assert not game.table.cards_by_id["kakita"].bowed


def test_honor_your_oaths_is_offered_from_hand_during_a_battle():
    """A Strategy is played out of hand, so its ability has to say it acts from there — the default
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
    them can take the Favor away — leaving a seat with no Yojimbo nothing to be asked about, and the
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
    is paid at step B of the Action Sequence and an Interrupt is played at D — the printed window
    opens after the cost it names. The deviation is deliberate and recorded on the handler.
    """
    game = _manjodh_game()

    resolve_effects(game, favor_payers(game, PlayerId.P1)["manjodh"])

    assert game.table.cards_by_id["manjodh"].bowed
    assert game.favor_holder is None, "he paid, and nobody held the Favor to begin with"


def test_a_bowed_manjodh_cannot_pay():
    """Bowing him is the price, and a bowed card cannot pay a bow cost (CR, Costs)."""
    game = _manjodh_game()
    game.table.cards_by_id["manjodh"].bow()

    assert favor_payers(game, PlayerId.P1) == {}


def test_manjodh_will_not_pay_for_a_player_with_a_wind():
    """ "If you have no Wind" — the clause the datasheet's Winds rule explains, since a seat with a
    Wind may not take rulebook Favor actions at all."""
    game = _manjodh_game(has_wind=True)

    assert favor_payers(game, PlayerId.P1) == {}
