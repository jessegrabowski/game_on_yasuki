import pytest

from yasuki_core.bots.agents import AutoAgent
from yasuki_core.engine.players import PlayerId
from yasuki_core.engine.rules.action_record import action_keywords
from yasuki_core.engine.rules.vocabulary import keywords
from yasuki_core.engine.rules.vocabulary.actions import (
    ActivateAbility,
    Equip,
    PlayStrategy,
    Recruit,
)
from yasuki_core.engine.rules.vocabulary.decisions import (
    ArrangeCards,
    ChooseAbilityTarget,
    ChooseCards,
    ChooseFortificationProvince,
    ChoosePayment,
    DecisionResponse,
)
from yasuki_core.engine.rules.stats.province_strength import effective_province_strength
from yasuki_core.engine.rules.gold.cost import effective_gold_cost
from yasuki_core.engine.rules.effects import Destroy
from yasuki_core.engine.rules.triggers import resolve_effects
from yasuki_core.engine.session import EngineSession
from yasuki_core.engine.table import DeckKey, TableState, ZoneKey, ZoneRole
from yasuki_core.engine.zones import ProvinceZone
from yasuki_core.game_pieces.cards import L5RCard
from yasuki_core.game_pieces.constants import IMPERIAL_FAVOR_ID, Side
from yasuki_core.game_pieces.prints import (
    AttachmentPrint,
    FatePrint,
    PersonalityPrint,
    StrongholdPrint,
)

from tests.yasuki_core.engine.builders import (
    end_phase,
    fate_card,
    holding,
    pay,
    personality,
    province_card,
    put_in_play,
    register,
)

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

    pending = session.project(P1).pending
    assert isinstance(pending, ChoosePayment)
    assert pending.amount == 4  # 3 Gold Cost plus the 1 it Invests


def test_investing_fetches_another_copy_out_of_the_fate_deck():
    session = _sand_game()
    session.act(P1, Equip("weapon", invest=True))
    pay(session, P1)
    session.submit(P1, DecisionResponse(("bearer",)))

    pending = session.project(P1).pending
    assert isinstance(pending, ChooseCards)
    assert pending.candidates == ("spare",)
    session.submit(P1, DecisionResponse(("spare",)))

    hand = session.game.table.zones[ZoneKey(P1, ZoneRole.HAND)].cards
    assert session.game.table.cards_by_id["spare"] in hand


def test_investing_raises_the_cards_gold_cost_permanently():
    """ "Permanently increase the Gold Cost by the Invest cost" (CR, Invest). The surcharge is a
    lasting property of the card in play, not a one-off payment."""
    session = _sand_game()
    session.act(P1, Equip("weapon", invest=True))
    pay(session, P1)
    session.submit(P1, DecisionResponse(("bearer",)))
    session.submit(P1, DecisionResponse(("spare",)))

    weapon = session.game.table.cards_by_id["weapon"]
    assert effective_gold_cost(session.game, weapon) == 4


def test_equipping_without_the_invest_leaves_the_cost_and_the_deck_alone():
    session = _sand_game()
    session.act(P1, Equip("weapon"))
    pay(session, P1)
    session.submit(P1, DecisionResponse(("bearer",)))

    assert session.project(P1).pending is None  # no search was raised
    assert effective_gold_cost(session.game, session.game.table.cards_by_id["weapon"]) == 3


def test_the_invest_is_withheld_when_only_the_bare_cost_is_affordable():
    session = _sand_game(production=3)

    offered = [a for a in session.legal_actions(P1) if isinstance(a, Equip)]

    assert offered == [Equip("weapon")]


def test_the_invested_cost_dies_with_the_card():
    """The Invest raises the Gold Cost stat, which Hired Killer and its kin read off a unit.
    The card ceasing to exist takes the raise with it, so a copy that comes back is priced as
    printed."""
    session = _sand_game()
    session.act(P1, Equip("weapon", invest=True))
    pay(session, P1)
    session.submit(P1, DecisionResponse(("bearer",)))
    session.submit(P1, DecisionResponse(("spare",)))
    weapon = session.game.table.cards_by_id["weapon"]
    assert effective_gold_cost(session.game, weapon) == 4

    resolve_effects(session.game, [Destroy("weapon", P1)])

    assert effective_gold_cost(session.game, weapon) == 3
    assert session.game.ongoing == []


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
    CR hands its controller the choice, and the token follows wherever that lands."""
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
    """A plain Holding in the discard pile is not a target. The ability needs the keyword."""
    session = _beiru_game(discarded=())
    state = session.game.table
    state.zones[ZoneKey(P1, ZoneRole.DYNASTY_DISCARD)].add(
        register(state, holding("farm", printed_id="farm", gold_cost=2))
    )

    assert ActivateAbility("beiru") not in session.legal_actions(P1)


# --- The Ivory Courtroom ---


def _courtroom_in_province(*, dishonorable: tuple[str, ...] = ()) -> EngineSession:
    """P1 with the Courtroom face-up in a Province, the Favor uncontrolled, and ``dishonorable``
    Personalities in play."""
    state = TableState.empty_two_seat()
    state.creatable_tokens[IMPERIAL_FAVOR_ID] = FatePrint(
        name="The Imperial Favor", side=Side.FATE, printed_id=IMPERIAL_FAVOR_ID
    )
    put_in_play(state, holding("mine", gold_production=4))
    for card_id in dishonorable:
        put_in_play(state, personality(card_id)).dishonor()
    put_in_play(state, personality("upright"))
    province_card(state, "courtroom", printed_id="the_ivory_courtroom", gold_cost=2)
    return EngineSession.start(state, P1)


def test_the_courtroom_takes_the_favor_and_rehonors_a_chosen_personality():
    session = _courtroom_in_province(dishonorable=("shamed", "disgraced"))
    end_phase(session)
    end_phase(session)  # through the Battle phase into the Dynasty phase

    session.act(P1, Recruit("courtroom"))
    pay(session, P1)
    assert session.game.favor_holder is P1
    assert set(session.game.pending.candidates) == {"shamed", "disgraced"}
    session.submit(P1, DecisionResponse(("shamed",)))

    game = session.game
    assert game.table.cards_by_id["shamed"].dishonorable is False
    assert game.table.cards_by_id["disgraced"].dishonorable is True


def test_the_courtroom_asks_nothing_with_nobody_to_rehonor():
    session = _courtroom_in_province()
    end_phase(session)
    end_phase(session)

    session.act(P1, Recruit("courtroom"))
    pay(session, P1)

    assert session.game.favor_holder is P1
    assert session.game.pending is None


def test_the_courtroom_may_be_recruited_in_the_action_phase_as_a_political_action():
    # "You may Recruit this Holding as a Political Open action."
    session = _courtroom_in_province()

    assert Recruit("courtroom") in session.legal_actions(P1)
    session.act(P1, Recruit("courtroom"))
    assert action_keywords(session.game) == {keywords.POLITICAL}
    pay(session, P1)

    assert session.game.favor_holder is P1


def test_the_courtroom_recruited_in_the_dynasty_phase_is_not_a_political_action():
    session = _courtroom_in_province()
    end_phase(session)
    end_phase(session)

    session.act(P1, Recruit("courtroom"))

    assert action_keywords(session.game) == frozenset()


def test_a_plain_holding_is_not_recruited_in_the_action_phase():
    state = TableState.empty_two_seat()
    put_in_play(state, holding("mine", gold_production=4))
    province_card(state, "farm", printed_id="rice_farm", gold_cost=2)
    session = EngineSession.start(state, P1)

    assert Recruit("farm") not in session.legal_actions(P1)


# --- Beset from All Sides ---


def _beset_game(*, chi: int = 3, deck: tuple[str, ...] = ("top", "second", "third", "fourth")):
    """P1 holding Beset from All Sides, gold for it, an unbowed Courtier of ``chi`` Chi, and a Fate
    deck reading ``deck`` from the top."""
    state = TableState.empty_two_seat()
    put_in_play(state, holding("sh", printed_id="plain_stronghold", gold_production=4, owner=P1))
    put_in_play(state, personality("courtier", chi=chi, keywords=("Courtier",)))
    put_in_play(state, personality("bushi", chi=chi))
    state.zones[ZoneKey(P1, ZoneRole.HAND)].add(
        register(
            state,
            L5RCard.of(
                FatePrint,
                id="beset",
                name="Beset from All Sides",
                printed_id="beset_from_all_sides",
                side=Side.FATE,
                owner=P1,
                gold_cost=2,
                keywords=("Political",),
            ),
        )
    )
    state.decks[DeckKey(P1, Side.FATE)].cards = [
        register(state, fate_card(card_id, P1)) for card_id in reversed(deck)
    ]
    return EngineSession.start(state, P1)


def _fate_deck(session: EngineSession) -> list[str]:
    """P1's Fate deck, top first."""
    return [card.id for card in reversed(session.game.table.decks[DeckKey(P1, Side.FATE)].cards)]


def _hand(session: EngineSession) -> list[str]:
    return [card.id for card in session.game.table.zones[ZoneKey(P1, ZoneRole.HAND)].cards]


def _play_beset_to_the_look(session: EngineSession) -> None:
    session.act(P1, PlayStrategy("beset"))
    pay(session, P1)
    pending = session.game.pending
    assert isinstance(pending, ChooseAbilityTarget) and pending.candidates == ("courtier",)
    session.submit(P1, DecisionResponse(("courtier",)))


def test_beset_targets_only_unbowed_courtiers():
    """Neither the Personality without the keyword nor the Courtier already bowed is offered."""
    session = _beset_game()
    tired = put_in_play(session.game, personality("tired", keywords=("Courtier",)))
    tired.bow()  # after start, which straightens the active seat's board
    session.act(P1, PlayStrategy("beset"))
    pay(session, P1)

    assert session.game.pending.candidates == ("courtier",)


def test_beset_can_be_backed_out_of_until_the_cards_are_seen():
    session = _beset_game()
    session.act(P1, PlayStrategy("beset"))
    pay(session, P1)

    session.cancel(P1)

    assert session.game.pending is None
    assert "beset" in _hand(session)
    assert not session.game.table.cards_by_id["courtier"].bowed


def test_beset_looks_at_the_courtiers_chi_in_cards_and_cannot_be_backed_out_of():
    session = _beset_game(chi=3)

    _play_beset_to_the_look(session)

    assert session.game.look.card_ids == ("top", "second", "third")
    assert session.game.table.cards_by_id["courtier"].bowed
    pending = session.game.pending
    assert isinstance(pending, ChooseCards) and pending.candidates == ("top", "second", "third")
    assert pending.decline_label == "Decline"
    with pytest.raises(ValueError):
        session.cancel(P1)


def test_beset_puts_the_chosen_card_on_the_bottom_and_draws_what_was_put_on_top_last():
    session = _beset_game(chi=3)
    _play_beset_to_the_look(session)

    session.submit(P1, DecisionResponse(("second",)))
    pending = session.game.pending
    assert isinstance(pending, ArrangeCards) and set(pending.candidates) == {"top", "third"}
    assert not pending.to_bottom
    session.submit(P1, DecisionResponse(("top", "third")))

    assert _hand(session) == ["third"]
    assert _fate_deck(session) == ["top", "fourth", "second"]
    assert session.game.look is None
    assert session.game.pending is None
    assert session.log.replay() == session.game


def test_beset_declined_puts_every_card_back_before_the_draw():
    session = _beset_game(chi=2)
    _play_beset_to_the_look(session)

    session.submit(P1, DecisionResponse(()))
    pending = session.game.pending
    assert isinstance(pending, ArrangeCards) and pending.candidates == ("top", "second")
    session.submit(P1, DecisionResponse(pending.unchanged))

    assert _hand(session) == ["top"]
    assert _fate_deck(session) == ["second", "third", "fourth"]


def test_beset_with_one_card_seen_has_nothing_to_arrange_after_it_goes_to_the_bottom():
    session = _beset_game(chi=1)
    _play_beset_to_the_look(session)

    session.submit(P1, DecisionResponse(("top",)))

    assert session.game.pending is None
    assert _hand(session) == ["second"]
    assert _fate_deck(session) == ["third", "fourth", "top"]


def test_a_bot_plays_beset_through_to_the_draw():
    """The bots answer by prefix: nothing for the may-choice, the look's own order for the
    arrangement. Both are legal, so a bot never stalls on the chain."""
    session = _beset_game(chi=3)
    agent = AutoAgent()
    session.act(P1, PlayStrategy("beset"))
    pay(session, P1)
    while session.game.pending is not None:
        session.submit(P1, agent.decide(session.game.pending, session.project(P1)))

    assert session.game.look is None
    assert _hand(session) == ["top"]
    assert _fate_deck(session) == ["second", "third", "fourth"]


def test_beset_on_an_empty_fate_deck_bows_the_courtier_and_asks_nothing():
    session = _beset_game(deck=())

    _play_beset_to_the_look(session)

    assert session.game.table.cards_by_id["courtier"].bowed
    assert session.game.pending is None
    assert session.game.look is None
