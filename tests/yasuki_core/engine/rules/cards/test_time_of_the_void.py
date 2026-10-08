import pytest

from yasuki_core.engine.players import PlayerId
from yasuki_core.engine.rules.effects import AttachCard
from yasuki_core.engine.rules.triggers import resolve_effects
from yasuki_core.engine.rules.vocabulary.actions import Equip, Pass
from yasuki_core.engine.rules.vocabulary.decisions import Confirm, DecisionResponse
from yasuki_core.engine.session import EngineSession
from yasuki_core.engine.table import DeckKey, TableState, ZoneKey, ZoneRole
from yasuki_core.game_pieces.cards import L5RCard
from yasuki_core.game_pieces.constants import AttachmentType, Side
from yasuki_core.game_pieces.prints import EventPrint

from tests.yasuki_core.engine.builders import (
    attachment,
    end_turn,
    fate_card,
    personality,
    put_in_play,
    register,
)

P1, P2 = PlayerId.P1, PlayerId.P2


# --- Enlistment ---


def _enlistment_game() -> EngineSession:
    """Enlistment in play for P1, P1's hero beside it and a 0-Gold Follower in P1's hand, with
    cards in both Fate decks to draw."""
    state = TableState.empty_two_seat()
    enlistment = L5RCard.of(
        EventPrint,
        id="enlistment",
        name="Enlistment",
        printed_id="enlistment",
        side=Side.DYNASTY,
        owner=P1,
    )
    put_in_play(state, enlistment)
    put_in_play(state, personality("hero"))
    follower = attachment("ashigaru", attachment_type=AttachmentType.FOLLOWER)
    state.zones[ZoneKey(P1, ZoneRole.HAND)].add(register(state, follower))
    for seat in (P1, P2):
        state.decks[DeckKey(seat, Side.FATE)].cards = [
            register(state, fate_card(f"{seat.name}-{index}", seat)) for index in range(6)
        ]
    return EngineSession.start(state, P1)


def _equip_the_follower(session: EngineSession) -> None:
    session.act(P1, Equip("ashigaru"))
    session.submit(P1, DecisionResponse(("hero",)))


def _fate_deck_size(session: EngineSession) -> int:
    return len(session.game.table.decks[DeckKey(P1, Side.FATE)].cards)


@pytest.mark.parametrize(("draws", "drawn"), [(True, 2), (False, 1)], ids=["draws", "declines"])
def test_enlistment_offers_a_card_before_the_turn_ends_after_equipping_a_follower(draws, drawn):
    session = _enlistment_game()
    _equip_the_follower(session)

    end_turn(session)
    asked = session.game.pending
    assert isinstance(asked, Confirm)
    deck = _fate_deck_size(session)
    session.submit(P1, DecisionResponse(asked.candidates if draws else ()))

    assert deck - _fate_deck_size(session) == drawn


def test_enlistment_counts_a_follower_equipped_on_the_other_players_turn():
    session = _enlistment_game()
    end_turn(session)
    session.act(P2, Pass())
    _equip_the_follower(session)

    end_turn(session)
    end_turn(session)

    assert session.game.active is P1
    assert isinstance(session.game.pending, Confirm)


@pytest.mark.parametrize("attached_by_effect", [False, True], ids=["nothing", "attached"])
def test_enlistment_offers_nothing_without_an_equipped_follower(attached_by_effect):
    session = _enlistment_game()
    if attached_by_effect:
        resolve_effects(session.game, [AttachCard("ashigaru", "hero")])

    end_turn(session)

    assert session.game.active is P2
    assert session.game.pending is None
