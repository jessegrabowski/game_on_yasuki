from yasuki_core.engine.players import PlayerId
from yasuki_core.engine.rules.stats.card_values import effective_force
from yasuki_core.engine.rules.vocabulary.actions import DeclareAttack, Pass, PlayStrategy
from yasuki_core.engine.rules.vocabulary.decisions import (
    ArrangeCards,
    ChooseAbilityTarget,
    ChooseCards,
    DecisionResponse,
)
from yasuki_core.engine.session import EngineSession
from yasuki_core.engine.table import DeckKey, TableState, ZoneKey, ZoneRole
from yasuki_core.game_pieces.cards import L5RCard
from yasuki_core.game_pieces.constants import Side
from yasuki_core.game_pieces.prints import ActionPrint, FatePrint

from tests.yasuki_core.engine.builders import (
    end_phase,
    end_turn,
    fate_card,
    pay,
    personality,
    province_card,
    put_in_play,
    register,
)

P1, P2 = PlayerId.P1, PlayerId.P2


# --- Flashy Technique ---


def _flashy_in_hand(*copies: str) -> EngineSession:
    """P1's Action Phase with ``copies`` of Flashy Technique in hand, a raider to attack with and
    P2's guard to defend with."""
    state = TableState.empty_two_seat()
    province_card(state, "atk-prov0", seat=P1, index=0)
    province_card(state, "def-prov0", seat=P2, index=0)
    put_in_play(state, personality("raider", force=3))
    put_in_play(state, personality("guard", owner=P2, force=3))
    for card_id in copies:
        state.zones[ZoneKey(P1, ZoneRole.HAND)].add(
            register(
                state,
                L5RCard.of(
                    ActionPrint,
                    id=card_id,
                    name="Flashy Technique",
                    printed_id="flashy_technique",
                    side=Side.FATE,
                    owner=P1,
                    gold_cost=0,
                ),
            )
        )
    return EngineSession.start(state, P1)


def _play(session: EngineSession, card_id: str) -> None:
    session.act(P1, PlayStrategy(card_id))
    pay(session, P1)


def _attack_with_the_raider(session: EngineSession) -> None:
    end_phase(session)
    session.act(P1, DeclareAttack())
    session.submit(P1, DecisionResponse(("raider@0",)))
    session.submit(P2, DecisionResponse(("guard@0",)))
    choice = session.game.pending
    session.submit(choice.seat, DecisionResponse((choice.candidates[0],)))


def test_flashy_technique_penalizes_personalities_only_while_they_attack():
    session = _flashy_in_hand("flashy")
    _play(session, "flashy")
    raider = session.game.table.cards_by_id["raider"]
    guard = session.game.table.cards_by_id["guard"]
    assert effective_force(session.game, raider) == 3

    _attack_with_the_raider(session)

    assert effective_force(session.game, raider) == 2
    assert effective_force(session.game, guard) == 3


def test_a_second_flashy_technique_is_legal_and_adds_no_second_penalty():
    session = _flashy_in_hand("first", "second")
    _play(session, "first")
    session.act(P2, Pass())  # the opportunity comes back to P1
    assert PlayStrategy("second") in session.legal_actions(P1)
    _play(session, "second")

    _attack_with_the_raider(session)

    assert effective_force(session.game, session.game.table.cards_by_id["raider"]) == 2


def test_the_limit_resets_with_the_turn():
    session = _flashy_in_hand("first", "second")
    _play(session, "first")
    end_turn(session)
    end_turn(session)
    _play(session, "second")

    _attack_with_the_raider(session)

    assert effective_force(session.game, session.game.table.cards_by_id["raider"]) == 2


# --- Banish All Doubt ---


def _doubt_game(deck: tuple[str, ...] = ("a", "b", "c", "d", "e")) -> EngineSession:
    """P1 holding Banish All Doubt, an unbowed Tactician, and a Fate deck reading ``deck`` from the
    top."""
    state = TableState.empty_two_seat()
    put_in_play(state, personality("tactician", keywords=("Tactician",)))
    state.zones[ZoneKey(P1, ZoneRole.HAND)].add(
        register(
            state,
            L5RCard.of(
                FatePrint,
                id="doubt",
                name="Banish All Doubt",
                printed_id="banish_all_doubt",
                side=Side.FATE,
                owner=P1,
                gold_cost=0,
                keywords=("Tactical",),
            ),
        )
    )
    state.decks[DeckKey(P1, Side.FATE)].cards = [
        register(state, fate_card(card_id, P1)) for card_id in reversed(deck)
    ]
    return EngineSession.start(state, P1)


def _fate_deck(session: EngineSession) -> list[str]:
    return [card.id for card in reversed(session.game.table.decks[DeckKey(P1, Side.FATE)].cards)]


def _play_to_the_look(session: EngineSession) -> None:
    session.act(P1, PlayStrategy("doubt"))
    pay(session, P1)  # the Gold Cost of zero is still asked for
    pending = session.game.pending
    assert isinstance(pending, ChooseAbilityTarget) and pending.candidates == ("tactician",)
    session.submit(P1, DecisionResponse(("tactician",)))


def test_banish_all_doubt_takes_one_of_four_and_puts_the_rest_on_the_bottom_in_order():
    session = _doubt_game()
    _play_to_the_look(session)
    pending = session.game.pending
    assert isinstance(pending, ChooseCards) and pending.candidates == ("a", "b", "c", "d")
    assert pending.decline_label is None  # one must be taken

    session.submit(P1, DecisionResponse(("c",)))
    pending = session.game.pending
    assert isinstance(pending, ArrangeCards) and pending.to_bottom
    assert pending.candidates == ("a", "b", "d")
    session.submit(P1, DecisionResponse(("d", "a", "b")))

    hand = session.game.table.zones[ZoneKey(P1, ZoneRole.HAND)].cards
    assert [card.id for card in hand] == ["c"]
    assert _fate_deck(session) == ["e", "d", "a", "b"]
    assert not session.game.table.cards_by_id["tactician"].bowed
    assert session.log.replay() == session.game


def test_keeping_the_order_puts_them_on_the_bottom_as_they_were_looked_at():
    session = _doubt_game()
    _play_to_the_look(session)
    session.submit(P1, DecisionResponse(("a",)))
    pending = session.game.pending

    session.submit(P1, DecisionResponse(pending.unchanged))

    assert _fate_deck(session) == ["e", "b", "c", "d"]


def test_banish_all_doubt_on_an_empty_deck_asks_nothing():
    """A look of nothing is not a question, so the action resolves with no effect at all."""
    session = _doubt_game(deck=())

    _play_to_the_look(session)

    assert session.game.pending is None
    assert session.game.look is None


def test_banish_all_doubt_on_a_single_card_takes_it_with_nothing_left_for_the_bottom():
    session = _doubt_game(deck=("only",))
    _play_to_the_look(session)

    session.submit(P1, DecisionResponse(("only",)))

    assert session.game.pending is None
    assert session.game.look is None
    assert _fate_deck(session) == []
