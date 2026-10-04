import pytest

from yasuki_core.engine.players import PlayerId
from yasuki_core.engine.rules.stats.card_values import effective_force
from yasuki_core.engine.rules.abilities.costs import no_cost
from yasuki_core.engine.rules.abilities.model import Ability
from yasuki_core.engine.rules.board.queries import personalities_in_play
from yasuki_core.engine.rules.effects import Move
from yasuki_core.engine.rules.vocabulary.actions import (
    ActionTiming,
    ActivateAbility,
    DeclareAttack,
    Pass,
    PlayInterrupt,
    PlayStrategy,
)
from yasuki_core.engine.rules.vocabulary.decisions import (
    ArrangeCards,
    ChooseAbilityTarget,
    ChooseCards,
    DecisionResponse,
)
from yasuki_core.engine.session import EngineSession
from yasuki_core.engine.table import DeckKey, Location, TableState, ZoneKey, ZoneRole, location_of
from yasuki_core.game_pieces.cards import L5RCard
from yasuki_core.game_pieces.constants import Side
from yasuki_core.game_pieces.prints import ActionPrint, FatePrint, RingPrint

from tests.yasuki_core.engine.rules.conftest import probe_ability
from tests.yasuki_core.engine.rules.duel.conftest import (
    CHALLENGE_ABILITY,
    CHALLENGE_PROBE,
    duel_focusing,
)
from tests.yasuki_core.engine.builders import (
    focus_card,
    combat_segment,
    end_phase,
    end_turn,
    fate_card,
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
    pending = session.game.pending
    assert isinstance(pending, ChooseAbilityTarget) and pending.candidates == ("tactician",)
    session.submit(P1, DecisionResponse(("tactician",)))


def test_banish_all_doubt_takes_one_of_four_and_puts_the_rest_on_the_bottom_in_order():
    session = _doubt_game()
    _play_to_the_look(session)
    pending = session.game.pending
    assert isinstance(pending, ChooseCards) and pending.candidates == ("a", "b", "c", "d")
    assert pending.minimum == 1

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


# --- Cowed by Wisdom ---

MOVE_HOME_PROBE = "probe_battle_move_a_personality_home"
MOVE_HOME = Ability(
    timings=(ActionTiming.BATTLE,),
    label="Battle: move a target Personality home",
    cost=no_cost,
    targets=lambda game, source: [card.id for card in personalities_in_play(game)],
    effects=lambda game, source, target: [Move(target.id, Location.home(target.owner))],
)


def _cowed(owner: PlayerId) -> L5RCard:
    return L5RCard.of(
        FatePrint,
        id="cowed",
        printed_id="cowed_by_wisdom",
        name="Cowed by Wisdom",
        side=Side.FATE,
        owner=owner,
        gold_cost=0,
    )


def _cowed_battle(*, holder: PlayerId, ring: bool = False) -> EngineSession:
    """P1's raider, whose Battle action moves a target Personality home, against P2's guard at the
    battlefield, with Cowed by Wisdom in ``holder``'s hand. ``ring`` puts a Ring in P1's play."""
    in_play = [
        personality("raider", printed_id=MOVE_HOME_PROBE),
        personality("guard", owner=P2),
    ]
    if ring:
        in_play.append(
            L5RCard.of(
                RingPrint, id="ring", printed_id="ring", name="ring", side=Side.FATE, owner=P1
            )
        )
    session = combat_segment(in_play, {"raider": 0}, {"guard": 0})
    table = session.game.table
    table.zones[ZoneKey(holder, ZoneRole.HAND)].add(register(table, _cowed(holder)))
    return session


def _at_the_battlefield(session: EngineSession, card_id: str) -> bool:
    table = session.game.table
    return location_of(table, table.cards_by_id[card_id]).battlefield == 0


def test_cowed_by_wisdom_negates_an_action_moving_an_enemy_from_the_battlefield():
    with probe_ability(MOVE_HOME_PROBE, MOVE_HOME):
        session = _cowed_battle(holder=P2)
        session.act(P1, ActivateAbility("raider"))
        session.submit(P1, DecisionResponse(("raider",)))

        session.act(P2, PlayInterrupt("cowed"))
        while session.game.pending is not None:
            session.submit(session.game.pending.seat, DecisionResponse(()))

        assert _at_the_battlefield(session, "raider")


def test_cowed_by_wisdom_is_not_offered_against_moving_your_own_personality():
    with probe_ability(MOVE_HOME_PROBE, MOVE_HOME):
        session = _cowed_battle(holder=P2)
        session.act(P1, ActivateAbility("raider"))
        session.submit(P1, DecisionResponse(("guard",)))

        assert PlayInterrupt("cowed") not in session.legal_actions(P2)


@pytest.mark.parametrize(("ring", "performer_bowed"), [(False, True), (True, False)])
def test_cowed_by_wisdom_bows_your_personality_unless_you_control_a_ring(ring, performer_bowed):
    session = _cowed_battle(holder=P1, ring=ring)

    session.act(P1, PlayStrategy("cowed"))
    session.submit(P1, DecisionResponse(("raider",)))
    session.submit(P1, DecisionResponse(("guard",)))

    table = session.game.table
    assert table.cards_by_id["guard"].bowed
    assert table.cards_by_id["raider"].bowed is performer_bowed


def test_flashy_technique_honors_the_duels_winner_whoever_it_is():
    # "This duel's winner", which can be the seat that did not focus it: P1 totals 1 against P2's
    # 3 plus 1.
    with probe_ability(CHALLENGE_PROBE, CHALLENGE_ABILITY):
        card = focus_card("flashy", P1, 0, printed_id="flashy_technique")
        session = duel_focusing(card, mine_chi=1)

        assert session.game.duel.outcome.winners == (P2,)
        assert session.game.table.seats[P2].honor == 1
        assert session.game.table.seats[P1].honor == 0


def test_flashy_technique_honors_nobody_when_both_personalities_lose():
    # Equal totals that the Duelist tiebreak cannot separate are lost by both, so there is no
    # winner to honor.
    with probe_ability(CHALLENGE_PROBE, CHALLENGE_ABILITY):
        card = focus_card("flashy", P1, 1, printed_id="flashy_technique")
        session = duel_focusing(card, mine_chi=3)

        assert session.game.duel.outcome.winners == ()
        assert session.game.table.seats[P1].honor == 0
        assert session.game.table.seats[P2].honor == 0
