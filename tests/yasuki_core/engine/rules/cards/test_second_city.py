from yasuki_core.engine.players import PlayerId
from yasuki_core.engine.table import TableState, DeckKey, ZoneKey, ZoneRole
from yasuki_core.engine.rules.actions import ActivateAbility
from yasuki_core.engine.rules.effects import DestroyProvince
from yasuki_core.engine.rules.log import replay
from yasuki_core.engine.rules.triggers import resolve_effects
from yasuki_core.engine.session import EngineSession
from yasuki_core.game_pieces.constants import Side

from yasuki_core.game_pieces.cards import L5RCard
from yasuki_core.game_pieces.prints import FatePrint

from tests.yasuki_core.engine.builders import (
    province_card,
    register,
)

P1 = PlayerId.P1


# --- Harsh Choices ---


def _harsh_game(*, other_provinces=1, fate_cards=5) -> EngineSession:
    """A session with Harsh Choices face-up in P1's Province 0, plus ``other_provinces`` more so the
    seat is not left with none, and a Fate deck deep enough to draw three from."""
    state = TableState.empty_two_seat()
    province_card(state, "harsh", printed_id="harsh_choices", name="Harsh Choices", index=0)
    for index in range(1, other_provinces + 1):
        province_card(state, f"other{index}", gold_cost=2, index=index)
    state.decks[DeckKey(P1, Side.FATE)].cards = [
        register(
            state,
            L5RCard.of(FatePrint, id=f"f{i}", name=f"F{i}", side=Side.FATE, owner=P1),
        )
        for i in range(fate_cards)
    ]
    return EngineSession.start(state, P1)


def _hand(session) -> list[str]:
    return [c.id for c in session.game.table.zones[ZoneKey(P1, ZoneRole.HAND)].cards]


def test_harsh_choices_is_offered_from_its_province():
    session = _harsh_game()
    assert ActivateAbility("harsh") in session.legal_actions(P1)


def test_it_destroys_its_own_province_and_draws_three():
    session = _harsh_game()
    before = len(_hand(session))
    session.act(P1, ActivateAbility("harsh"))

    assert ZoneKey(P1, ZoneRole.PROVINCE, 0) not in session.game.table.zones  # the Province is gone
    assert len(_hand(session)) == before + 3


def test_the_event_goes_to_the_discard_with_the_province_it_destroyed():
    """Destroying a Province discards its contents face-up, so the Event is spent by the same
    stroke rather than needing a discard of its own."""
    session = _harsh_game()
    session.act(P1, ActivateAbility("harsh"))

    discard = session.game.table.zones[ZoneKey(P1, ZoneRole.DYNASTY_DISCARD)]
    assert "harsh" in {c.id for c in discard.cards}
    assert session.game.table.cards_by_id["harsh"].face_up


def test_it_leaves_the_seats_other_provinces_alone():
    session = _harsh_game(other_provinces=3)
    session.act(P1, ActivateAbility("harsh"))

    remaining = {
        key.idx
        for key in session.game.table.zones
        if key.owner is P1 and key.role is ZoneRole.PROVINCE
    }
    assert remaining == {1, 2, 3}


def test_destroying_a_province_replays_to_the_same_state():
    session = _harsh_game()
    session.act(P1, ActivateAbility("harsh"))
    assert replay(session.log) == session.game


def test_destroying_a_province_that_is_already_gone_is_a_no_op():
    """Two Events in one Province both resolving, or a Province destroyed by anything else first —
    the effect finds nothing to destroy rather than raising on a missing zone."""
    session = _harsh_game()
    gone = ZoneKey(P1, ZoneRole.PROVINCE, 0)
    session.act(P1, ActivateAbility("harsh"))
    assert gone not in session.game.table.zones

    before = len(session.game.table.zones)
    resolve_effects(session.game, [DestroyProvince(P1, gone)])

    assert len(session.game.table.zones) == before
