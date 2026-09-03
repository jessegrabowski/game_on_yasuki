from yasuki_core.engine.players import PlayerId
from yasuki_core.engine.rules.actions import Recruit
from yasuki_core.engine.session import EngineSession
from yasuki_core.engine.table import DeckKey, TableState, ZoneKey, ZoneRole
from yasuki_core.engine.zones import ProvinceZone
from yasuki_core.game_pieces.cards import L5RCard
from yasuki_core.game_pieces.constants import Side
from yasuki_core.game_pieces.prints import HoldingPrint

from tests.yasuki_core.engine.builders import end_phase, pay, put_in_play, register

P1 = PlayerId.P1


def _recruit_the_bazaar(*, printed_keywords: tuple[str, ...]) -> EngineSession:
    """Recruit Famous Bazaar out of a Province, built with ``printed_keywords`` on its record."""
    state = TableState.empty_two_seat()
    state.decks[DeckKey(P1, Side.DYNASTY)].cards = [
        register(
            state, L5RCard.of(HoldingPrint, id="refill", name="R", side=Side.DYNASTY, owner=P1)
        )
    ]
    put_in_play(
        state,
        L5RCard.of(
            HoldingPrint, id="SH", name="SH", side=Side.DYNASTY, owner=P1, gold_production=8
        ),
    )
    bazaar = register(
        state,
        L5RCard.of(
            HoldingPrint,
            id="bazaar",
            name="Famous Bazaar",
            side=Side.DYNASTY,
            owner=P1,
            printed_id="famous_bazaar",
            keywords=printed_keywords,
            gold_cost=2,
        ),
    )
    bazaar.turn_face_up()
    province = ProvinceZone(owner=P1)
    province.add(bazaar)
    state.zones[ZoneKey(P1, ZoneRole.PROVINCE, 0)] = province
    session = EngineSession.start(state, P1)
    end_phase(session)  # Action -> Battle
    end_phase(session)  # Battle -> Dynasty
    session.act(P1, Recruit("bazaar"))
    pay(session, P1)
    return session


def test_the_bazaar_refills_its_province_face_up():
    """Shattered Empire prints Renew on the keyword line, so the record carries it."""
    session = _recruit_the_bazaar(printed_keywords=("Market", "Renew"))

    refill = session.game.table.zones[ZoneKey(P1, ZoneRole.PROVINCE, 0)].cards[-1]
    assert refill.face_up


def test_it_refills_face_up_from_a_record_that_prints_no_keyword():
    """Every printing before Shattered Empire spells the rule out in the text box instead, and the
    card database keeps one keyword set per card rather than one per printing. Reading the keyword
    alone leaves the card inert on the record the older templating produces."""
    session = _recruit_the_bazaar(printed_keywords=("Market",))

    refill = session.game.table.zones[ZoneKey(P1, ZoneRole.PROVINCE, 0)].cards[-1]
    assert refill.face_up
