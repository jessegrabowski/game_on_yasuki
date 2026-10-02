from yasuki_core.engine.players import PlayerId
from yasuki_core.engine.rules.board.queries import has_keyword
from yasuki_core.engine.rules.vocabulary.actions import ActivateAbility
from yasuki_core.engine.rules.vocabulary.decisions import ChooseOption, DecisionResponse
from yasuki_core.engine.session import EngineSession
from yasuki_core.engine.table import TableState

from tests.yasuki_core.engine.builders import (
    end_turn,
    holding,
    personality,
    put_in_play,
    register,
    stronghold,
)

P1, P2 = PlayerId.P1, PlayerId.P2


# --- Temple to the Elements ---


def _temple_game() -> EngineSession:
    """Temple to the Elements in P1's play, beside P1's Monk, Shugenja and Bushi and P2's Monk."""
    state = TableState.empty_two_seat()
    put_in_play(state, stronghold(P1))
    put_in_play(state, register(state, holding("temple", printed_id="temple_to_the_elements")))
    put_in_play(state, register(state, personality("monk", keywords=("Monk",))))
    put_in_play(state, register(state, personality("shugenja", keywords=("Shugenja",))))
    put_in_play(state, register(state, personality("bushi", keywords=("Bushi",))))
    put_in_play(state, register(state, personality("theirs", owner=P2, keywords=("Monk",))))
    return EngineSession.start(state, P1)


def test_temple_to_the_elements_targets_your_monks_and_shugenja_bowed_or_not():
    session = _temple_game()
    session.game.table.cards_by_id["monk"].bow()

    session.act(P1, ActivateAbility("temple"))

    assert set(session.game.pending.candidates) == {"monk", "shugenja"}


def test_temple_to_the_elements_gives_the_named_element_until_the_end_of_the_turn():
    session = _temple_game()
    monk = session.game.table.cards_by_id["monk"]

    session.act(P1, ActivateAbility("temple"))
    session.submit(P1, DecisionResponse(("monk",)))
    pending = session.game.pending
    assert isinstance(pending, ChooseOption)
    assert pending.candidates == ("Air", "Earth", "Fire", "Water")
    session.submit(P1, DecisionResponse(("Earth",)))

    assert has_keyword(session.game, monk, "Earth")
    end_turn(session)
    assert not has_keyword(session.game, monk, "Earth")
