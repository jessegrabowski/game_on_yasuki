from yasuki_core.engine.players import PlayerId
from yasuki_core.engine.rules.actions import ActivateAbility, Equip
from yasuki_core.engine.rules.decisions import (
    ChooseCards,
    ChooseFortificationProvince,
    ChoosePayment,
    DecisionResponse,
)
from yasuki_core.engine.rules.economy import effective_gold_cost, effective_province_strength
from yasuki_core.engine.rules.effects import Destroy
from yasuki_core.engine.rules.triggers import resolve_effects
from yasuki_core.engine.session import EngineSession
from yasuki_core.engine.table import DeckKey, TableState, ZoneKey, ZoneRole
from yasuki_core.engine.zones import ProvinceZone
from yasuki_core.game_pieces.cards import L5RCard
from yasuki_core.game_pieces.constants import Side
from yasuki_core.game_pieces.prints import AttachmentPrint, PersonalityPrint, StrongholdPrint

from tests.yasuki_core.engine.builders import holding, pay, province_card, register

P1 = PlayerId.P1


def _weapon(state, card_id: str) -> L5RCard:
    return register(
        state,
        L5RCard.of(
            AttachmentPrint,
            id=card_id,
            name="Stockpiled Weapon",
            side=Side.FATE,
            owner=P1,
            printed_id="stockpiled_weapon",
            gold_cost=3,
            keywords=("Weapon", "One-Handed", "Sword"),
        ),
    )


def _sand_game(*, production=8, in_deck=("spare",)) -> EngineSession:
    """P1 holding a Stockpiled Weapon, a bearer for it, and ``in_deck`` copies to fetch."""
    state = TableState.empty_two_seat()
    state.battlefield.add(
        register(
            state,
            L5RCard.of(
                StrongholdPrint,
                id="P1-SH",
                name="SH",
                side=Side.STRONGHOLD,
                owner=P1,
                gold_production=production,
            ),
        )
    )
    state.battlefield.add(
        register(
            state,
            L5RCard.of(
                PersonalityPrint,
                id="bearer",
                name="Bearer",
                side=Side.DYNASTY,
                owner=P1,
                force=2,
                chi=3,
            ),
        )
    )
    state.zones[ZoneKey(P1, ZoneRole.HAND)].add(_weapon(state, "weapon"))
    for card_id in in_deck:
        state.decks[DeckKey(P1, Side.FATE)].cards.append(_weapon(state, card_id))
    return EngineSession.start(state, P1)


def test_stockpiled_weapon_offers_equip_with_and_without_the_invest():
    session = _sand_game()

    offered = [a for a in session.legal_actions(P1) if isinstance(a, Equip)]

    assert offered == [Equip("weapon"), Equip("weapon", invest=True)]


def test_investing_raises_the_price_by_the_invest_cost():
    session = _sand_game()

    session.act(P1, Equip("weapon", invest=True))
    session.submit(P1, DecisionResponse(("bearer",)))

    pending = session.project(P1).pending
    assert isinstance(pending, ChoosePayment)
    assert pending.amount == 4  # 3 Gold Cost plus the 1 it Invests


def test_investing_fetches_another_copy_out_of_the_fate_deck():
    session = _sand_game()
    session.act(P1, Equip("weapon", invest=True))
    session.submit(P1, DecisionResponse(("bearer",)))
    pay(session, P1)

    pending = session.project(P1).pending
    assert isinstance(pending, ChooseCards)
    assert pending.candidates == ("spare",)
    session.submit(P1, DecisionResponse(("spare",)))

    hand = session.game.table.zones[ZoneKey(P1, ZoneRole.HAND)].cards
    assert session.game.table.cards_by_id["spare"] in hand


def test_investing_raises_the_cards_gold_cost_permanently():
    """ "Permanently increase the Gold Cost by the Invest cost" (CR, Invest) — the surcharge is a
    lasting property of the card in play, not a one-off payment."""
    session = _sand_game()
    session.act(P1, Equip("weapon", invest=True))
    session.submit(P1, DecisionResponse(("bearer",)))
    pay(session, P1)
    session.submit(P1, DecisionResponse(("spare",)))

    weapon = session.game.table.cards_by_id["weapon"]
    assert effective_gold_cost(session.game, weapon) == 4


def test_equipping_without_the_invest_leaves_the_cost_and_the_deck_alone():
    session = _sand_game()
    session.act(P1, Equip("weapon"))
    session.submit(P1, DecisionResponse(("bearer",)))
    pay(session, P1)

    assert session.project(P1).pending is None  # no search was raised
    assert effective_gold_cost(session.game, session.game.table.cards_by_id["weapon"]) == 3


def test_the_invest_is_withheld_when_only_the_bare_cost_is_affordable():
    session = _sand_game(production=3)

    offered = [a for a in session.legal_actions(P1) if isinstance(a, Equip)]

    assert offered == [Equip("weapon")]


def test_the_invested_cost_dies_with_the_card():
    """The Invest raises the Gold Cost stat, which Hired Killer and its kin read off a unit. The
    card ceasing to exist takes the raise with it, so a copy that comes back is priced as printed."""
    session = _sand_game()
    session.act(P1, Equip("weapon", invest=True))
    session.submit(P1, DecisionResponse(("bearer",)))
    pay(session, P1)
    session.submit(P1, DecisionResponse(("spare",)))
    weapon = session.game.table.cards_by_id["weapon"]
    assert effective_gold_cost(session.game, weapon) == 4

    resolve_effects(session.game, [Destroy("weapon", P1)])

    assert effective_gold_cost(session.game, weapon) == 3
    assert session.game.modifiers == []


# --- Agasha Beiru ---


def _beiru_game(*, provinces=("keep",), discarded=("wall",)):
    """Beiru in play, Fortifications in the Dynasty discard, and occupied Provinces to attach to."""
    state = TableState.empty_two_seat()
    state.battlefield.add(
        register(
            state,
            L5RCard.of(
                StrongholdPrint,
                id="P1-SH",
                name="SH",
                side=Side.STRONGHOLD,
                owner=P1,
                gold_production=8,
                province_strength=3,
            ),
        )
    )
    state.battlefield.add(
        register(
            state,
            L5RCard.of(
                PersonalityPrint,
                id="beiru",
                name="Agasha Beiru",
                side=Side.DYNASTY,
                owner=P1,
                printed_id="agasha_beiru",
                force=1,
                chi=3,
                keywords=("Earth", "Shugenja"),
            ),
        )
    )
    for index, card_id in enumerate(provinces):
        province_card(state, card_id, printed_id=card_id, gold_cost=1, index=index)
    discard = state.zones[ZoneKey(P1, ZoneRole.DYNASTY_DISCARD)]
    for card_id in discarded:
        discard.add(
            register(
                state,
                holding(card_id, printed_id=card_id, gold_cost=2, keywords=("Fortification",)),
            )
        )
    return EngineSession.start(state, P1)


def test_beiru_walls_the_province_he_attaches_the_fortification_to():
    """ "Recruit a target Fortification in your discard pile (attach it to any of your Provinces).
    Give its Province a +1 strength Wall token." The Fortification never sat in a Province, so the
    CR hands its controller the choice — and the token follows wherever that lands."""
    session = _beiru_game()

    session.act(P1, ActivateAbility("beiru"))
    session.submit(P1, DecisionResponse(("wall",)))  # the Fortification to recruit
    pay(session, P1)  # pay for it
    pending = session.project(P1).pending
    assert isinstance(pending, ChooseFortificationProvince)
    # Provinces are named by slot rather than by the card standing in one.
    assert pending.candidates == (ZoneKey(P1, ZoneRole.PROVINCE, 0).token,)
    session.submit(P1, DecisionResponse((ZoneKey(P1, ZoneRole.PROVINCE, 0).token,)))

    game = session.game
    first = ZoneKey(P1, ZoneRole.PROVINCE, 0)
    assert game.table.province_attachments == {"wall": first}
    assert game.table.province_counters == {first: {"wall": 1}}
    assert effective_province_strength(game, first) == 4  # 3 printed, +1 walled
    assert game.table.cards_by_id["beiru"].bowed  # his bow is the cost


def test_beiru_offers_the_seat_every_province():
    session = _beiru_game(provinces=("keep", "farm"))

    session.act(P1, ActivateAbility("beiru"))
    session.submit(P1, DecisionResponse(("wall",)))
    pay(session, P1)

    assert set(session.project(P1).pending.candidates) == {
        ZoneKey(P1, ZoneRole.PROVINCE, index).token for index in range(2)
    }


def test_beiru_can_wall_an_empty_province():
    """A Province is a slot, so one standing empty takes a Fortification like any other. Named by
    the card in it instead, an empty Province is unpickable and the paid-for recruit deadlocks."""
    game_state = _beiru_game(provinces=()).game.table
    empty = ZoneKey(P1, ZoneRole.PROVINCE, 0)
    game_state.zones[empty] = ProvinceZone(owner=P1)
    session = EngineSession.start(game_state, P1)

    session.act(P1, ActivateAbility("beiru"))
    session.submit(P1, DecisionResponse(("wall",)))
    pay(session, P1)
    assert session.project(P1).pending.candidates == (empty.token,)
    session.submit(P1, DecisionResponse((empty.token,)))

    assert session.game.table.province_attachments == {"wall": empty}
    assert session.game.table.province_counters == {empty: {"wall": 1}}


def test_beiru_is_not_offered_without_a_fortification_to_raise():
    """A plain Holding in the discard pile is not a target; the ability needs the keyword."""
    session = _beiru_game(discarded=())
    state = session.game.table
    state.zones[ZoneKey(P1, ZoneRole.DYNASTY_DISCARD)].add(
        register(state, holding("farm", printed_id="farm", gold_cost=2))
    )

    assert ActivateAbility("beiru") not in session.legal_actions(P1)
