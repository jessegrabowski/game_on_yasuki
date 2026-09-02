from yasuki_core.engine.players import PlayerId
from yasuki_core.engine.rules.actions import ActionTiming, PlayStrategy
from yasuki_core.engine.rules.abilities import CardLocation
from yasuki_core.engine.rules.decisions import DecisionResponse
from yasuki_core.engine.rules.economy import effective_chi, effective_force
from yasuki_core.engine.rules.modifiers import Duration, Modifier, Stat
from yasuki_core.engine.rules import abilities
from yasuki_core.engine.session import EngineSession
from yasuki_core.engine.table import TableState, ZoneKey, ZoneRole
from yasuki_core.game_pieces.cards import L5RCard
from yasuki_core.game_pieces.constants import Side
from yasuki_core.game_pieces.prints import ActionPrint

from tests.yasuki_core.engine.builders import end_turn, personality, put_in_play, register

PLAYER, OPPONENT = PlayerId.P1, PlayerId.P2


def _uncertainty(state: TableState) -> L5RCard:
    """Uncertainty in the player's hand. It prints no Gold Cost."""
    card = register(
        state,
        L5RCard.of(
            ActionPrint,
            id="uncertainty",
            name="Uncertainty",
            printed_id="uncertainty",
            side=Side.FATE,
            owner=PLAYER,
            gold_cost=0,
        ),
    )
    state.zones[ZoneKey(PLAYER, ZoneRole.HAND)].add(card)
    return card


def _play_at(session: EngineSession, target_id: str) -> None:
    """Play Uncertainty and point it at ``target_id``, answering the free payment on the way."""
    session.act(PLAYER, PlayStrategy("uncertainty"))
    for _ in range(4):
        asked = session.game.pending
        if asked is None:
            return
        chosen = (target_id,) if target_id in asked.candidates else ()
        session.submit(asked.seat, DecisionResponse(chosen))
    raise AssertionError("the action never resolved")


def test_the_target_keeps_one_chi_however_far_the_penalty_takes_him():
    """A 2 Chi Personality given -2C reads 1, not 0 — the minimum applies on top of the penalty."""
    state = TableState.empty_two_seat()
    put_in_play(state, personality("shiba", owner=OPPONENT, force=3, chi=2))
    _uncertainty(state)
    session = EngineSession.start(state, PLAYER)

    _play_at(session, "shiba")

    target = session.game.table.cards_by_id["shiba"]
    assert effective_chi(session.game, target) == 1
    assert effective_force(session.game, target) == 1


def test_the_target_survives_the_chi_penalty():
    """Without the minimum the -2C would take a 2 Chi Personality to zero and the Chi Death Rule
    would destroy him."""
    state = TableState.empty_two_seat()
    put_in_play(state, personality("shiba", owner=OPPONENT, force=3, chi=2))
    _uncertainty(state)
    session = EngineSession.start(state, PLAYER)

    _play_at(session, "shiba")

    assert "shiba" in {card.id for card in session.game.table.battlefield.cards}


def test_it_reaches_the_players_own_personality_too():
    """The card says "a target Personality" without naming a side."""
    state = TableState.empty_two_seat()
    put_in_play(state, personality("own", owner=PLAYER, force=4, chi=4))
    _uncertainty(state)
    session = EngineSession.start(state, PLAYER)

    _play_at(session, "own")

    target = session.game.table.cards_by_id["own"]
    assert effective_force(session.game, target) == 2
    assert effective_chi(session.game, target) == 2


def test_it_is_not_offered_with_no_personality_in_play():
    state = TableState.empty_two_seat()
    card = _uncertainty(state)
    session = EngineSession.start(state, PLAYER)

    assert PlayStrategy(card.id) not in session.legal_actions(PLAYER)


def test_it_is_offered_under_both_of_its_printed_designators():
    """ "Battle/Open" — the Open half is reachable through a round today, the Battle half once battle
    rounds open one, and the card is the same card in either."""
    state = TableState.empty_two_seat()
    put_in_play(state, personality("shiba", owner=OPPONENT, force=3, chi=2))
    card = _uncertainty(state)
    game = EngineSession.start(state, PLAYER).game
    in_hand = (CardLocation.HAND,)

    uncertainty = abilities.ability_for(card)
    for designator in (ActionTiming.OPEN, ActionTiming.BATTLE):
        assert abilities.activatable(game, PLAYER, frozenset({designator}), at=in_hand) == [
            (card, uncertainty)
        ]
    assert abilities.activatable(game, PLAYER, frozenset({ActionTiming.DYNASTY}), at=in_hand) == []


def test_the_penalty_and_the_minimum_both_wear_off_when_the_turn_ends():
    """Neither prints a duration, so both last until the end of the current turn (CR, Duration of
    Effects) — a minimum that outlived its turn would keep a Personality out of the Chi Death Rule
    for the rest of the game."""
    state = TableState.empty_two_seat()
    put_in_play(state, personality("shiba", owner=OPPONENT, force=3, chi=2))
    _uncertainty(state)
    session = EngineSession.start(state, PLAYER)
    _play_at(session, "shiba")

    end_turn(session)

    target = session.game.table.cards_by_id["shiba"]
    assert effective_chi(session.game, target) == 2
    assert effective_force(session.game, target) == 3
    # A floor that outlived its turn is invisible while the stat is above it, so the assertion that
    # it is gone has to be a penalty that would otherwise be stopped by it.
    session.game.modifiers.append(
        Modifier("later", "shiba", Stat.CHI, -5, Duration.UNTIL_END_OF_TURN)
    )
    assert effective_chi(session.game, target) == 0
