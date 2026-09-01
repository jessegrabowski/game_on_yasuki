from yasuki_core.engine.players import PlayerId
from yasuki_core.engine.rules.actions import PlayStrategy
from yasuki_core.engine.rules.attachments import attachments_of
from yasuki_core.engine.rules.cards.gates_of_tengoku import SASADAS_OROCHI
from yasuki_core.engine.rules.decisions import (
    ChooseAmount,
    ChooseCards,
    ChoosePayment,
    DecisionResponse,
)
from yasuki_core.engine.rules.events import EnteredPlay
from yasuki_core.engine.rules.triggers import fire
from yasuki_core.engine.rules.units import unit_force
from yasuki_core.engine.session import EngineSession
from yasuki_core.engine.table import TableState, ZoneKey, ZoneRole
from yasuki_core.game_pieces.cards import L5RCard
from yasuki_core.game_pieces.constants import Side
from yasuki_core.game_pieces.prints import ActionPrint

from tests.yasuki_core.engine.builders import (
    end_turn,
    holding,
    personality,
    put_in_play,
    register,
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
    """ "Banish them at the end of the turn" — he is still there to fight with until it does."""
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
