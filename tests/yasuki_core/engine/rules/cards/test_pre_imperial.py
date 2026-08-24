from yasuki_core.engine.players import PlayerId
from yasuki_core.engine.table import TableState, DeckKey, ZoneKey, ZoneRole
from yasuki_core.engine.zones import ProvinceZone
from yasuki_core.engine.rules.actions import Recruit
from yasuki_core.engine.session import EngineSession
from yasuki_core.game_pieces.constants import Side
from yasuki_core.game_pieces.cards import L5RCard
from yasuki_core.game_pieces.prints import HoldingPrint

from tests.yasuki_core.engine.builders import (
    end_phase,
    pay,
    put_in_play,
    register,
)

P1 = PlayerId.P1


def _recruited(session, card_id):
    return session.game.table.cards_by_id[card_id] in session.game.table.battlefield.cards


def test_a_producers_yield_at_resolution_still_depends_on_what_it_pays_for():
    """Jade Works yields +2 only when paying for a Jade card. Payment resolution recomputes each
    producer's yield, so it has to recompute it against the same target the offer quoted."""
    state = TableState.empty_two_seat()
    state.decks[DeckKey(P1, Side.DYNASTY)].cards = [
        register(
            state, L5RCard.of(HoldingPrint, id="refill", name="R", side=Side.DYNASTY, owner=P1)
        )
    ]
    put_in_play(
        state,
        L5RCard.of(
            HoldingPrint,
            id="jw",
            name="Jade Works",
            side=Side.DYNASTY,
            owner=P1,
            printed_id="jade_works",
            gold_production=2,
        ),
    )
    target = register(
        state,
        L5RCard.of(
            HoldingPrint,
            id="jade",
            name="Jade Thing",
            side=Side.DYNASTY,
            owner=P1,
            gold_cost=4,
            keywords=("Jade",),
        ),
    )
    target.turn_face_up()
    province = ProvinceZone(owner=P1)
    province.add(target)
    state.zones[ZoneKey(P1, ZoneRole.PROVINCE, 0)] = province

    session = EngineSession.start(state, P1)
    end_phase(session)
    end_phase(session)
    session.act(P1, Recruit("jade"))
    # The offer quotes 4 — base 2 plus the Jade bonus — and bowing it alone must cover the cost.
    pay(session, P1)

    # 4 produced (2 base + 2 Jade bonus) less the 4 spent. Recomputing without the target would
    # yield 2 and leave the seat short, which asserting on the recruit alone would not notice.
    assert session.game.gold[P1] == 0
    assert _recruited(session, "jade")
