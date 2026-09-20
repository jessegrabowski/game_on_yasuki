from yasuki_core.engine.players import PlayerId
from yasuki_core.engine.rules.vocabulary.actions import PlayStrategy
from yasuki_core.engine.rules.units.membership import attachments_of
from yasuki_core.engine.rules.cards.gates_of_tengoku import SASADAS_OROCHI
from yasuki_core.engine.rules.vocabulary.decisions import (
    Confirm,
    ChooseAmount,
    ChooseCards,
    ChoosePayment,
    DecisionResponse,
)
from yasuki_core.engine.rules.vocabulary.game_events import EnteredPlay
from yasuki_core.engine.rules.triggers import fire
from yasuki_core.engine.rules.units.composition import unit_force
from yasuki_core.engine.session import EngineSession
from yasuki_core.engine.table import TableState, ZoneKey, ZoneRole
from yasuki_core.game_pieces.cards import L5RCard
from yasuki_core.game_pieces.constants import Side
from yasuki_core.game_pieces.prints import ActionPrint, PersonalityPrint

from yasuki_core.engine.rules.abilities.costs import no_cost
from yasuki_core.engine.rules.abilities.model import Ability
from yasuki_core.engine.rules.board.queries import personalities_in_play
from yasuki_core.engine.rules.effects import Destroy, RangedAttack
from yasuki_core.engine.rules.rulebook.recruit import finish_recruit
from yasuki_core.engine.rules.vocabulary.actions import (
    ActionTiming,
    ActivateAbility,
    DeclareAttack,
    Pass,
    PlayInterrupt,
    Recruit,
)
from yasuki_core.engine.rules.turn.structure import RoundKind
from yasuki_core.engine.rules.vocabulary.segments import BattleSegment
from yasuki_core.engine.table import DeckKey
from yasuki_core.engine.zones import ProvinceZone
from yasuki_core.engine.replay.game_log import replay
from yasuki_core.engine.rules.turn.action_sequence import submit
from tests.yasuki_core.engine.rules.conftest import probe_ability
from tests.yasuki_core.engine.builders import (
    dealt_table,
    end_phase,
    province_card,
    end_turn,
    holding,
    personality,
    put_in_play,
    pay,
    register,
    stronghold,
    token_template,
    two_seat_game,
)

P1 = PlayerId.P1


# --- Sasada, Pearl Champion ---


def _sasada_game():
    game = two_seat_game()
    token_template(
        game,
        SASADAS_OROCHI,
        name="Sasada's Orochi",
        card_type="Follower",
        keywords=("Nonhuman", "Orochi"),
        force=2,
    )
    put_in_play(
        game,
        personality("sasada", printed_id="sasada_pearl_champion_experienced", force=2, chi=3),
    )
    return game


def test_sasada_arrives_with_her_orochi():
    game = _sasada_game()

    fire(game, EnteredPlay("sasada"))

    sasada = game.table.cards_by_id["sasada"]
    orochi = attachments_of(game, sasada)[0]
    assert orochi.name == "Sasada's Orochi"
    assert unit_force(game, sasada) == 4  # her 2, plus the Orochi's own 2


def test_another_personality_arriving_does_not_summon_the_orochi():
    """The trigger fires for every event, so it has to check the arrival is Sasada's own."""
    game = _sasada_game()
    put_in_play(game, personality("sailor", force=1, chi=2))

    fire(game, EnteredPlay("sailor"))

    assert attachments_of(game, game.table.cards_by_id["sasada"]) == ()
    assert attachments_of(game, game.table.cards_by_id["sailor"]) == ()


PLAYER, OPPONENT = PlayerId.P1, PlayerId.P2


def _bad_death(state: TableState) -> L5RCard:
    """The Strategy in the player's hand. It prints no Gold Cost: the cost is the amount paid."""
    card = register(
        state,
        L5RCard.of(
            ActionPrint,
            id="bad_death",
            name="The Bad Death of Hida Daizu",
            printed_id="the_bad_death_of_hida_daizu",
            side=Side.FATE,
            owner=PLAYER,
        ),
    )
    state.zones[ZoneKey(PLAYER, ZoneRole.HAND)].add(card)
    return card


def _bad_death_reply(asked, amount: int | None) -> DecisionResponse:
    """What a player would answer: the named amount when asked for one, nothing when the pool
    already covers a payment, and the first option otherwise."""
    if isinstance(asked, ChooseAmount) and amount is not None:
        return DecisionResponse((str(amount),))
    if isinstance(asked, ChoosePayment) and asked.covers_cost(DecisionResponse()):
        return DecisionResponse()
    return DecisionResponse(asked.candidates[:1])


def _spend(session: EngineSession, amount: int) -> None:
    """Play the card through to its end, spending ``amount``."""
    for _ in range(12):
        asked = session.game.pending
        if asked is None:
            return
        session.submit(asked.seat, _bad_death_reply(asked, amount))
    raise AssertionError("the action never resolved")


def _targets_offered(session: EngineSession, *, paying: int) -> tuple[str, ...]:
    """Spend ``paying`` and advance to the target choice, handing back the candidates."""
    for _ in range(8):
        asked = session.game.pending
        if isinstance(asked, ChooseCards):
            return asked.candidates
        assert asked is not None, "no targets were offered"
        session.submit(asked.seat, _bad_death_reply(asked, paying))
    raise AssertionError("no targets were offered")


def _on_board(session: EngineSession) -> set[str]:
    return {card.id for card in session.game.table.battlefield.cards}


def test_an_amount_reaches_every_unit_costing_that_much_or_less():
    """The card reads "equal to or less than", so one amount leaves a choice of targets rather than
    naming one, and the seat still chooses after the cost is paid."""
    state = TableState.empty_two_seat()
    put_in_play(state, holding("mine", owner=PLAYER, gold_production=10))
    put_in_play(state, personality("cheap", owner=OPPONENT, gold_cost=1))
    put_in_play(state, personality("dear", owner=OPPONENT, gold_cost=4))
    card = _bad_death(state)
    session = EngineSession.start(state, PLAYER)

    session.act(PLAYER, PlayStrategy(card.id))

    assert set(_targets_offered(session, paying=4)) == {"cheap", "dear"}


def test_the_target_stays_in_play_until_the_turn_ends():
    """ "Banish them at the end of the turn" means he is still there to fight with until it does."""
    state = TableState.empty_two_seat()
    put_in_play(state, holding("mine", owner=PLAYER, gold_production=10))
    put_in_play(state, personality("target", owner=OPPONENT, gold_cost=2))
    card = _bad_death(state)
    session = EngineSession.start(state, PLAYER)

    session.act(PLAYER, PlayStrategy(card.id))
    _spend(session, 2)
    assert "target" in _on_board(session)

    end_turn(session)

    assert "target" not in _on_board(session)


def test_the_card_banishes_itself_rather_than_going_to_the_discard():
    """The card banishes itself, so step F must not also discard it (CR, Action Sequence)."""
    state = TableState.empty_two_seat()
    put_in_play(state, holding("mine", owner=PLAYER, gold_production=10))
    put_in_play(state, personality("target", owner=OPPONENT, gold_cost=2))
    card = _bad_death(state)
    session = EngineSession.start(state, PLAYER)

    session.act(PLAYER, PlayStrategy(card.id))
    _spend(session, 2)

    zones = session.game.table.zones
    assert [held.id for held in zones[ZoneKey(PLAYER, ZoneRole.FATE_BANISH)].cards] == [card.id]
    assert zones[ZoneKey(PLAYER, ZoneRole.FATE_DISCARD)].cards == []


def test_an_amount_below_every_unit_reaches_no_target():
    """The Gold is spent in the cost step whether or not the amount reaches anybody (CR, Action
    Sequence step E), and nothing is banished when the turn ends."""
    state = TableState.empty_two_seat()
    put_in_play(state, holding("mine", owner=PLAYER, gold_production=10))
    put_in_play(state, personality("target", owner=OPPONENT, gold_cost=5))
    card = _bad_death(state)
    session = EngineSession.start(state, PLAYER)

    session.act(PLAYER, PlayStrategy(card.id))
    _spend(session, 3)
    assert session.game.gold[PLAYER] == 7  # 10 produced, 3 spent

    end_turn(session)

    assert "target" in _on_board(session)


# --- Ninube Aitso, "Doji Yeiko" (Experienced) ---

DESTROY_PROBE = "probe_battle_destroy_an_enemy"
RANGED_PROBE = "probe_battle_ranged_attack"
AITSO = "ninube_aitso_doji_yeiko_experienced"


def _enemy_personalities(game, source):
    return [card.id for card in personalities_in_play(game) if card.owner is not source.owner]


DESTROY_ABILITY = Ability(
    timings=(ActionTiming.BATTLE,),
    label="Battle: destroy a target enemy Personality",
    cost=no_cost,
    targets=_enemy_personalities,
    effects=lambda game, source, target: [Destroy(target.id, source.owner)],
)
RANGED_ABILITY = Ability(
    timings=(ActionTiming.BATTLE,),
    label="Battle: Ranged 9 Attack",
    cost=no_cost,
    targets=_enemy_personalities,
    effects=lambda game, source, target: [RangedAttack(9, target.id, source.owner)],
)


def _aitso_defending(*, probe: str = DESTROY_PROBE, target: str = "guard") -> EngineSession:
    """Aitso's Dynasty deck starts empty so the reshuffle is easy to read."""
    state = TableState.empty_two_seat()
    province_card(state, "atk-prov0", seat=P1, index=0)
    province_card(state, "def-prov0", seat=PlayerId.P2, index=0)
    put_in_play(state, personality("raider", owner=P1, printed_id=probe, force=3))
    put_in_play(state, personality("guard", owner=PlayerId.P2, force=2))
    put_in_play(state, personality("aitso", owner=PlayerId.P2, printed_id=AITSO, force=2))
    session = EngineSession.start(state, P1)
    end_phase(session)
    session.act(P1, DeclareAttack())
    session.submit(P1, DecisionResponse(("raider@0",)))
    session.submit(PlayerId.P2, DecisionResponse(("guard@0", "aitso@0")))
    choice = session.game.pending
    session.submit(choice.seat, DecisionResponse((choice.candidates[0],)))
    while session.game.attack.battle_segment is not BattleSegment.COMBAT:
        session.act(session.game.round.priority, Pass())
    session.act(PlayerId.P2, Pass())
    session.act(P1, ActivateAbility("raider"))
    session.submit(P1, DecisionResponse((target,)))
    return session


def _dynasty_deck(session: EngineSession) -> list[str]:
    return [card.id for card in session.game.table.decks[DeckKey(PlayerId.P2, Side.DYNASTY)].cards]


def test_aitso_reshuffles_herself_into_the_dynasty_deck_to_negate_the_destruction():
    with probe_ability(DESTROY_PROBE, DESTROY_ABILITY):
        session = _aitso_defending()
        assert session.game.round.kind is RoundKind.INTERRUPT

        session.act(PlayerId.P2, PlayInterrupt("aitso"))

        game = session.game
        assert "guard" in {card.id for card in game.table.battlefield.cards}
        assert _dynasty_deck(session) == ["aitso"]
        assert game.pending is None


def test_aitso_answers_the_destruction_a_ranged_attack_would_make():
    with probe_ability(RANGED_PROBE, RANGED_ABILITY):
        session = _aitso_defending(probe=RANGED_PROBE)
        assert session.game.round.kind is RoundKind.INTERRUPT

        session.act(PlayerId.P2, PlayInterrupt("aitso"))

        assert "guard" in {card.id for card in session.game.table.battlefield.cards}


WEAK_RANGED_ABILITY = Ability(
    timings=(ActionTiming.BATTLE,),
    label="Battle: Ranged 1 Attack",
    cost=no_cost,
    targets=_enemy_personalities,
    effects=lambda game, source, target: [RangedAttack(1, target.id, source.owner)],
)


def test_aitso_is_not_offered_against_an_attack_that_cannot_reach():
    # "If the action would destroy": the window forecasts an attack's outcome on the board as it
    # stands, and a Ranged 1 Attack on a 2F guard would destroy nobody.
    with probe_ability(RANGED_PROBE, WEAK_RANGED_ABILITY):
        session = _aitso_defending(probe=RANGED_PROBE)

        assert session.game.round.kind is not RoundKind.INTERRUPT
        assert "guard" in {card.id for card in session.game.table.battlefield.cards}
        assert _dynasty_deck(session) == []


def test_aitso_may_negate_her_own_destruction():
    with probe_ability(DESTROY_PROBE, DESTROY_ABILITY):
        session = _aitso_defending(target="aitso")

        session.act(PlayerId.P2, PlayInterrupt("aitso"))

        assert _dynasty_deck(session) == ["aitso"]
        assert session.game.pending is None


def test_declining_aitso_lets_the_destruction_resolve():
    with probe_ability(DESTROY_PROBE, DESTROY_ABILITY):
        session = _aitso_defending()

        session.act(PlayerId.P2, Pass())

        in_play = {card.id for card in session.game.table.battlefield.cards}
        assert "guard" not in in_play and "aitso" in in_play


def test_aitsos_interrupt_replays_to_the_same_board():
    with probe_ability(DESTROY_PROBE, DESTROY_ABILITY):
        session = _aitso_defending()
        session.act(PlayerId.P2, PlayInterrupt("aitso"))

        rebuilt = replay(session.log)

        assert rebuilt.table == session.game.table
        assert rebuilt.pending is None and not rebuilt.stack


def test_proclaiming_aitso_asks_whether_to_gain_three_instead():
    # "You may gain 3 Honor instead of her Personal Honor" is the seat's call, asked once she has
    # entered play, which is when a Proclaim's gain is added (CR, Proclaim).
    game = two_seat_game()
    aitso = put_in_play(game, personality("aitso", printed_id=AITSO, personal_honor=0))

    finish_recruit(game, aitso.id, None, proclaim=True)

    assert isinstance(game.pending, Confirm)
    assert game.pending.prompt() == "Gain 3 Honor from Proclaiming instead of 0?"
    submit(game, DecisionResponse(game.pending.candidates))
    assert game.table.seats[P1].honor == 3


def test_proclaiming_a_dishonored_aitso_for_three_rehonors_her_instead():
    # Dishonored face up in a Province, she is recruited dishonorable (CR, Honorable and
    # Dishonorable). The Recruit action targets her, so the 3 Honor her trait offers is a gain 0.1
    # substitutes her rehonoring for. The seat gains nothing.
    table = dealt_table(hand=0)
    put_in_play(table, stronghold(P1, gold_production=8, clan="Crane"))
    aitso = L5RCard.of(
        PersonalityPrint,
        id="aitso",
        name="aitso",
        printed_id=AITSO,
        side=Side.DYNASTY,
        owner=P1,
        force=2,
        chi=2,
        clan="Crane",
        personal_honor=0,
        gold_cost=0,
        honor_requirement=0,
    )
    aitso.turn_face_up()
    aitso.dishonor()
    province = ProvinceZone(owner=P1)
    province.add(register(table, aitso))
    table.zones[ZoneKey(P1, ZoneRole.PROVINCE, 0)] = province
    session = EngineSession.start(table, P1, seed=4)
    end_phase(session)
    end_phase(session)

    proclaim = next(
        action
        for action in session.legal_actions(P1)
        if isinstance(action, Recruit) and action.proclaim
    )
    session.act(P1, proclaim)
    pay(session, P1)
    assert isinstance(session.game.pending, Confirm)
    session.submit(P1, DecisionResponse(session.game.pending.candidates))

    recruited = session.game.table.cards_by_id["aitso"]
    assert recruited in session.game.table.battlefield.cards
    assert not recruited.dishonorable
    assert session.game.table.seats[P1].honor == 0


def test_declining_the_alternative_proclaims_aitso_for_her_personal_honor():
    game = two_seat_game()
    aitso = put_in_play(game, personality("aitso", printed_id=AITSO, personal_honor=4))

    finish_recruit(game, aitso.id, None, proclaim=True)
    submit(game, DecisionResponse())

    assert game.table.seats[P1].honor == 4
