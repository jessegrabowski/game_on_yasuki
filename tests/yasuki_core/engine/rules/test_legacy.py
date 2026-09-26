import pytest
from yasuki_core import ruleset
from yasuki_core.engine import ops
from numpy.random import default_rng

from yasuki_core.engine.players import PlayerId
from yasuki_core.engine.table import TableState, ZoneKey, ZoneRole, DeckKey
from yasuki_core.game_pieces.constants import IMPERIAL_FAVOR_ID, LEGACY_PROXY_ID, Side
from yasuki_core.game_pieces.cards import L5RCard
from yasuki_core.game_pieces.prints import (
    ActionPrint,
    DynastyPrint,
    FatePrint,
    HoldingPrint,
    RulebookPrint,
)
from yasuki_core.engine.rules.abilities.model import Interrupt, Interruption
from yasuki_core.engine.rules.abilities.registry import register_interrupt
from yasuki_core.engine.rules.board.queries import rulebook_proxy
from yasuki_core.engine.rules.vocabulary.actions import ActivateAbility, Pass, PlayInterrupt
from yasuki_core.engine.rules.vocabulary.decisions import ChooseCards, DecisionResponse
from yasuki_core.engine.rules.vocabulary.game_events import ActionResolved, CardDiscarded
from yasuki_core.engine.rules.effects import Effect, Negated, TakeFavor
from yasuki_core.engine.rules.state import GameState
from yasuki_core.engine.rules.turn.structure import Phase, RoundKind
from yasuki_core.engine.rules import legality
from yasuki_core.engine.rules.rulebook import legacy, proxies
from yasuki_core.engine.rules.turn import action_sequence
from yasuki_core.engine.replay.game_log import replay
from yasuki_core.engine.session import EngineSession

from tests.yasuki_core.engine.builders import end_phase, holding, put_in_play, register


def _legacy(game: GameState, seat: PlayerId = PlayerId.P1) -> ActivateAbility:
    return ActivateAbility(rulebook_proxy(game, seat, LEGACY_PROXY_ID).id, legacy.LEGACY)


def _province(table: TableState, index: int):
    return table.zones[ZoneKey(PlayerId.P1, ZoneRole.PROVINCE, index)]


def _p1_provinces(table: TableState):
    return [
        zone
        for key, zone in table.zones.items()
        if key.owner is PlayerId.P1 and key.role is ZoneRole.PROVINCE
    ]


def _facedown_province(state: TableState, seat: PlayerId, card):
    register(state, card)
    card.turn_face_down()
    state.zones[ops.create_province(state, seat)].add(card)
    return card


def _legacy_holding(seat: PlayerId, card_id: str) -> L5RCard:
    return L5RCard.of(
        HoldingPrint,
        id=card_id,
        name="Ancestral Shrine",
        side=Side.DYNASTY,
        owner=seat,
        keywords=("Legacy",),
    )


def _table(*, provinces: int = 3, hand: int = 1, legacy_in: str | None = "deck") -> TableState:
    """A two-seat table with P1 holding ``hand`` fate cards, ``provinces`` face-down provinces, and
    a filled dynasty deck. ``legacy_in`` seeds a Legacy holding in P1's ``"deck"`` or first
    ``"province"``. None leaves P1 with no findable Legacy card."""
    state = TableState.empty_two_seat()
    for i in range(provinces):
        _facedown_province(
            state,
            PlayerId.P1,
            L5RCard.of(
                DynastyPrint, id=f"P1-pv{i}", name="P", side=Side.DYNASTY, owner=PlayerId.P1
            ),
        )
    hand_zone = state.zones[ZoneKey(PlayerId.P1, ZoneRole.HAND)]
    for i in range(hand):
        hand_zone.add(
            register(
                state,
                L5RCard.of(FatePrint, id=f"P1-h{i}", name="H", side=Side.FATE, owner=PlayerId.P1),
            )
        )
    deck = state.decks[DeckKey(PlayerId.P1, Side.DYNASTY)]
    deck.cards = [
        register(
            state,
            L5RCard.of(
                DynastyPrint, id=f"P1-dd{i}", name="D", side=Side.DYNASTY, owner=PlayerId.P1
            ),
        )
        for i in range(3)
    ]
    if legacy_in == "deck":
        deck.cards.insert(0, register(state, _legacy_holding(PlayerId.P1, "P1-leg")))
    elif legacy_in == "province":
        legacy = register(state, _legacy_holding(PlayerId.P1, "P1-leg"))
        legacy.turn_face_down()  # only face-down province cards are searchable
        state.zones[ZoneKey(PlayerId.P1, ZoneRole.PROVINCE, 0)].cards = [legacy]
    return state


def _dynasty_session_from(state: TableState) -> EngineSession:
    """A session on a prepared table, parked in the Dynasty phase where Legacy is on offer."""
    session = EngineSession.start(state, PlayerId.P1, seed=7)
    end_phase(session)  # Action -> Battle
    end_phase(session)  # Battle -> Dynasty
    return session


def _dynasty_session(**kwargs) -> EngineSession:
    session = EngineSession.start(_table(**kwargs), PlayerId.P1, seed=7)
    end_phase(session)  # Action -> Battle
    end_phase(session)  # Battle -> Dynasty
    return session


def test_legacy_candidates_finds_a_deck_or_face_down_province_card():
    # GameState.start does not reveal provinces, so the seeded face-down province card stays down.
    game_deck = GameState.start(_table(legacy_in="deck"), PlayerId.P1)
    game_prov = GameState.start(_table(legacy_in="province"), PlayerId.P1)
    game_none = GameState.start(_table(legacy_in=None), PlayerId.P1)

    assert [c.id for c in legality.legacy_candidates(game_deck, PlayerId.P1)] == ["P1-leg"]
    assert [c.id for c in legality.legacy_candidates(game_prov, PlayerId.P1)] == ["P1-leg"]
    assert legality.legacy_candidates(game_none, PlayerId.P1) == []


def test_legacy_does_not_search_a_face_up_province_card():
    state = _table(legacy_in=None)
    face_up_legacy = register(state, _legacy_holding(PlayerId.P1, "P1-shown"))  # face-up by default
    state.zones[ZoneKey(PlayerId.P1, ZoneRole.PROVINCE, 0)].cards = [face_up_legacy]
    game = GameState.start(state, PlayerId.P1)

    assert (
        legality.legacy_candidates(game, PlayerId.P1) == []
    )  # a revealed province card is not searched


def test_legacy_search_pool_is_the_whole_deck_plus_face_down_provinces():
    game = GameState.start(_table(), PlayerId.P1)
    pool = legality.legacy_search_pool(game, PlayerId.P1)
    pool_ids = {card.id for card in pool}

    deck_ids = {c.id for c in game.table.decks[DeckKey(PlayerId.P1, Side.DYNASTY)].cards}
    assert deck_ids <= pool_ids  # every deck card is searchable, not just the Legacy holding
    province_in_pool = [c for c in pool if c.id.startswith("P1-pv")]
    assert province_in_pool and all(not c.face_up for c in province_in_pool)  # only face-down ones


def test_legacy_is_offered_in_the_dynasty_phase_with_a_card_to_banish():
    session = _dynasty_session()
    assert _legacy(session.game) in session.legal_actions(PlayerId.P1)


def test_legacy_is_not_offered_without_a_card_to_banish():
    session = _dynasty_session(hand=0)
    assert _legacy(session.game) not in session.legal_actions(PlayerId.P1)


def _holding_the_favor(state: TableState) -> TableState:
    state.creatable_tokens[IMPERIAL_FAVOR_ID] = RulebookPrint(
        name="The Imperial Favor", side=Side.FATE, printed_id=IMPERIAL_FAVOR_ID
    )
    return state


def test_legacy_is_not_offered_with_only_the_imperial_favor_in_hand():
    session = _dynasty_session_from(_holding_the_favor(_table(hand=0)))
    TakeFavor(PlayerId.P1).perform(session.game)

    assert _legacy(session.game) not in session.legal_actions(PlayerId.P1)


def test_the_imperial_favor_is_not_a_legacy_banish_candidate():
    session = _dynasty_session_from(_holding_the_favor(_table(hand=1)))
    TakeFavor(PlayerId.P1).perform(session.game)
    session.act(PlayerId.P1, _legacy(session.game))

    assert session.game.pending.candidates == ("P1-h0",)


def test_legacy_is_not_offered_outside_the_dynasty_phase():
    session = EngineSession.start(_table(), PlayerId.P1, seed=7)  # Action phase
    assert _legacy(session.game) not in session.legal_actions(PlayerId.P1)


def test_legacy_whiff_loses_the_game():
    session = _dynasty_session(legacy_in=None)
    session.act(PlayerId.P1, _legacy(session.game))
    session.submit(PlayerId.P1, DecisionResponse(("P1-h0",)))

    assert session.game.loser is PlayerId.P1
    assert session.game.game_over
    assert session.legal_actions(PlayerId.P1) == []  # a lost game offers no further actions
    # The losing action must not hand the opportunity on: a finished game's round stays exactly
    # where it stopped rather than counting passes toward a round nobody can play.
    assert session.game.phase is Phase.DYNASTY
    assert session.game.turn == 1
    assert session.game.round.priority is PlayerId.P1
    assert session.game.round.passes == 0


def test_legacy_banishes_the_chosen_hand_card():
    session = _dynasty_session(hand=2, legacy_in=None)
    session.act(PlayerId.P1, _legacy(session.game))
    session.submit(PlayerId.P1, DecisionResponse(("P1-h1",)))

    banish = session.game.table.zones[ZoneKey(PlayerId.P1, ZoneRole.FATE_BANISH)]
    assert [c.id for c in banish.cards] == ["P1-h1"]


def test_legacy_finds_a_deck_card_and_places_it_face_up_over_a_province():
    session = _dynasty_session(legacy_in="deck")
    session.act(PlayerId.P1, _legacy(session.game))
    session.submit(PlayerId.P1, DecisionResponse(("P1-h0",)))
    assert session.game.pending == ChooseCards(
        seat=PlayerId.P1,
        candidates=("P1-leg",),
        minimum=1,
        maximum=1,
        resolver=legacy.FIND_RESOLVER,
    )

    session.submit(PlayerId.P1, DecisionResponse(("P1-leg",)))
    assert session.game.pending.resolver == legacy.PLACE_RESOLVER
    assert session.game.pending.source_id == "P1-leg"  # the province pick carries the found card

    session.submit(PlayerId.P1, DecisionResponse(("P1-pv1",)))
    table = session.game.table
    placed = table.cards_by_id["P1-leg"]
    holding_province = [z for z in _p1_provinces(table) if any(c.id == "P1-leg" for c in z.cards)]
    assert placed.face_up and len(holding_province) == 1  # placed face-up into one province
    discard = table.zones[ZoneKey(PlayerId.P1, ZoneRole.DYNASTY_DISCARD)]
    assert "P1-pv1" in {c.id for c in discard.cards}  # the displaced card was discarded
    assert placed not in table.decks[DeckKey(PlayerId.P1, Side.DYNASTY)].cards  # left the deck


def test_legacy_places_a_face_down_province_card_and_refills_its_old_province():
    # A face-down province Legacy card is only reachable off-turn (your own provinces are revealed),
    # so drive flow directly on an unrevealed GameState rather than through a session.
    game = GameState.start(_table(legacy_in="province"), PlayerId.P1)
    game.phase = Phase.DYNASTY
    proxies.spawn_rulebook_proxies(game)
    action_sequence.perform(game, _legacy(game))
    action_sequence.submit(game, DecisionResponse(("P1-h0",)))
    action_sequence.submit(game, DecisionResponse(("P1-leg",)))
    assert "P1-leg" not in game.pending.candidates  # the found card can't be its own sacrifice

    action_sequence.submit(game, DecisionResponse(("P1-pv1",)))
    source = game.table.zones[ZoneKey(PlayerId.P1, ZoneRole.PROVINCE, 0)]
    assert len(source.cards) == 1 and source.cards[0].id != "P1-leg"  # refilled from the deck


def test_a_found_card_with_no_province_to_displace_is_revealed_where_it_sits():
    session = _dynasty_session(provinces=0, legacy_in="deck")
    session.act(PlayerId.P1, _legacy(session.game))
    session.submit(PlayerId.P1, DecisionResponse(("P1-h0",)))
    session.submit(PlayerId.P1, DecisionResponse(("P1-leg",)))

    found = session.game.table.cards_by_id["P1-leg"]
    assert session.game.pending is None
    assert found.face_up
    assert found in session.game.table.decks[DeckKey(PlayerId.P1, Side.DYNASTY)].cards


def test_legacy_is_once_per_turn():
    session = _dynasty_session(legacy_in="deck")
    session.act(PlayerId.P1, _legacy(session.game))
    session.submit(PlayerId.P1, DecisionResponse(("P1-h0",)))
    session.submit(PlayerId.P1, DecisionResponse(("P1-leg",)))
    session.submit(PlayerId.P1, DecisionResponse(("P1-pv1",)))

    assert _legacy(session.game) not in session.legal_actions(PlayerId.P1)


def test_legacy_search_offers_every_found_card_to_choose_among():
    session = _dynasty_session(legacy_in="deck")  # seeds "P1-leg" in the deck
    deck = session.game.table.decks[DeckKey(PlayerId.P1, Side.DYNASTY)]
    deck.cards.insert(1, register(session.game.table, _legacy_holding(PlayerId.P1, "P1-leg2")))
    session.act(PlayerId.P1, _legacy(session.game))
    session.submit(PlayerId.P1, DecisionResponse(("P1-h0",)))

    assert set(session.game.pending.candidates) == {"P1-leg", "P1-leg2"}


def test_legacy_places_the_chosen_card_not_a_default():
    session = _dynasty_session(legacy_in="deck")  # "P1-leg" is first in search order
    deck = session.game.table.decks[DeckKey(PlayerId.P1, Side.DYNASTY)]
    deck.cards.insert(1, register(session.game.table, _legacy_holding(PlayerId.P1, "P1-leg2")))
    session.act(PlayerId.P1, _legacy(session.game))
    session.submit(PlayerId.P1, DecisionResponse(("P1-h0",)))

    session.submit(PlayerId.P1, DecisionResponse(("P1-leg2",)))  # pick the runner-up on purpose
    session.submit(PlayerId.P1, DecisionResponse(("P1-pv1",)))

    placed = [
        z for z in _p1_provinces(session.game.table) if any(c.id == "P1-leg2" for c in z.cards)
    ]
    assert len(placed) == 1  # the card the player chose is the one placed
    assert "P1-leg" in {c.id for c in deck.cards}  # the unchosen card stays in the deck


def test_a_completed_legacy_sequence_replays_to_the_same_state():
    session = _dynasty_session(legacy_in="deck")
    session.act(PlayerId.P1, _legacy(session.game))
    session.submit(PlayerId.P1, DecisionResponse(("P1-h0",)))
    session.submit(PlayerId.P1, DecisionResponse(("P1-leg",)))
    session.submit(PlayerId.P1, DecisionResponse(("P1-pv1",)))

    # The fieldless action, both re-derived decisions, and the deterministic reshuffle must all
    # rebuild identically from the log.
    assert replay(session.log) == session.game


def test_the_reshuffle_draws_on_the_games_own_generator():
    """Seed 7 at turn 2 and seed 8 at turn 1 once collided, because the reshuffle seed was the sum
    of the two. Drawing from the game's generator makes the turn irrelevant to which stream it
    is."""
    orders = []
    for seed, turn in ((7, 2), (8, 1)):
        session = _dynasty_session(legacy_in="deck")
        session.game.seed, session.game.turn = seed, turn
        session.game.rng = default_rng(seed)
        session.act(PlayerId.P1, _legacy(session.game))
        session.submit(PlayerId.P1, DecisionResponse(("P1-h0",)))
        session.submit(PlayerId.P1, DecisionResponse(("P1-leg",)))
        session.submit(PlayerId.P1, DecisionResponse(("P1-pv1",)))
        deck = session.game.table.decks[DeckKey(PlayerId.P1, Side.DYNASTY)]
        orders.append(tuple(card.id for card in deck.cards))

    assert orders[0] != orders[1]


def _shrine_of_courtesy(seat: PlayerId) -> L5RCard:
    """Shrine of Courtesy carries no printed Legacy keyword. Its Courtesy clause grants one."""
    return L5RCard.of(
        HoldingPrint,
        id=f"{seat.name}-courtesy",
        name="Shrine of Courtesy",
        side=Side.DYNASTY,
        owner=seat,
        printed_id="shrine_of_courtesy",
        keywords=("Temple", "Unique"),
        gold_production=2,
    )


def test_a_search_finds_a_card_granted_legacy_by_its_own_ability():
    """The search reads effective keywords: a Holding whose printed list omits Legacy is still
    findable while its own condition grants it."""
    state = _table(legacy_in=None)
    shrine = register(state, _shrine_of_courtesy(PlayerId.P2))
    state.decks[DeckKey(PlayerId.P2, Side.DYNASTY)].cards = [shrine]
    game = GameState.start(state, PlayerId.P1)  # P1 first, so P2 has Courtesy

    assert [c.id for c in legality.legacy_candidates(game, PlayerId.P2)] == ["P2-courtesy"]


def test_a_conditional_grant_that_does_not_apply_leaves_the_card_unfindable():
    state = _table(legacy_in=None)
    shrine = register(state, _shrine_of_courtesy(PlayerId.P1))
    state.decks[DeckKey(PlayerId.P1, Side.DYNASTY)].cards = [shrine]
    game = GameState.start(state, PlayerId.P1)  # P1 went first, so Courtesy grants nothing

    assert legality.legacy_candidates(game, PlayerId.P1) == []


def _buried_province_card(session: EngineSession) -> L5RCard:
    """Put a face-down card in a Province of the seat about to act, the state a Province is left in
    when it refills after a recruit, the only way one is face-down during its owner's own turn."""
    buried = L5RCard.of(
        HoldingPrint,
        id="P1-buried",
        name="Mine",
        side=Side.DYNASTY,
        owner=PlayerId.P1,
        gold_production=5,
    )
    state = session.game.table
    register(state, buried)
    state.zones[ZoneKey(PlayerId.P1, ZoneRole.PROVINCE, 0)].cards = [buried]
    buried.turn_face_down()
    return buried


def test_the_search_shows_the_seat_its_face_down_province_cards():
    """You look through your Provinces to search, so by the time you pick one to displace you have
    seen what is in each. Without it, a Province refilled face-down is a blind discard."""
    session = _dynasty_session(legacy_in="deck")
    buried = _buried_province_card(session)
    assert buried.peekers == frozenset()  # unseen until the search runs

    session.act(PlayerId.P1, _legacy(session.game))
    session.submit(PlayerId.P1, DecisionResponse((session.game.pending.candidates[0],)))

    assert buried.peekers == frozenset({PlayerId.P1})


def test_the_banish_pick_can_be_cancelled_and_leaves_legacy_unspent():
    session = _dynasty_session(legacy_in="deck")
    session.act(PlayerId.P1, _legacy(session.game))

    assert session.can_cancel(PlayerId.P1)
    session.cancel(PlayerId.P1)
    assert session.game.pending is None
    assert _legacy(session.game) in session.legal_actions(PlayerId.P1)


def test_no_pick_after_the_search_can_be_cancelled():
    session = _dynasty_session(legacy_in="deck")
    session.act(PlayerId.P1, _legacy(session.game))
    session.submit(PlayerId.P1, DecisionResponse((session.game.pending.candidates[0],)))
    assert session.game.pending.resolver == legacy.FIND_RESOLVER

    assert not session.can_cancel(PlayerId.P1)
    with pytest.raises(ValueError, match="looked at"):
        session.cancel(PlayerId.P1)

    session.submit(PlayerId.P1, DecisionResponse((session.game.pending.candidates[0],)))
    assert session.game.pending.resolver == legacy.PLACE_RESOLVER
    assert not session.can_cancel(PlayerId.P1)


def test_a_resolved_legacy_no_longer_bars_backing_out():
    session = _dynasty_session(legacy_in="deck")
    session.act(PlayerId.P1, _legacy(session.game))
    session.submit(PlayerId.P1, DecisionResponse(("P1-h0",)))
    session.submit(PlayerId.P1, DecisionResponse(("P1-leg",)))
    session.submit(PlayerId.P1, DecisionResponse(("P1-pv1",)))

    assert session.game.action_resolved
    assert not session.game.hidden_card_shown


def test_the_search_does_not_show_the_pool_to_the_opponent():
    session = _dynasty_session(legacy_in="deck")
    buried = _buried_province_card(session)

    session.act(PlayerId.P1, _legacy(session.game))
    session.submit(PlayerId.P1, DecisionResponse((session.game.pending.candidates[0],)))

    assert PlayerId.P2 not in buried.peekers


def test_a_reaction_to_the_displaced_card_sees_the_province_it_left(reacting):
    """The rules resolve what the displaced card leaving triggered before the Legacy card lands, so
    a seat reacting to its own discard acts on the Province that discard emptied.

    Doji Meiji is the card this is for. "after you discard Meiji from a Province, if you are Crane
    Clan, take the Imperial Favor" should resolve while the Province is still the one Meiji left.
    """
    seen = []
    reacting(
        CardDiscarded,
        "legacy_probe",
        lambda ctx: seen.append([card.id for card in _province(ctx.game.table, 1).cards]) or [],
    )
    session = _dynasty_session(legacy_in="deck")
    put_in_play(session.game, holding("P1-eyes", owner=PlayerId.P1, printed_id="legacy_probe"))

    session.act(PlayerId.P1, _legacy(session.game))
    session.submit(PlayerId.P1, DecisionResponse(("P1-h0",)))
    session.submit(PlayerId.P1, DecisionResponse(("P1-leg",)))
    session.submit(PlayerId.P1, DecisionResponse(("P1-pv1",)))

    assert seen == [[]]  # the displaced card gone, the Legacy card not yet in its place
    assert [c.id for c in _province(session.game.table, 1).cards] == ["P1-leg"]


def test_each_seat_is_dealt_its_own_legacy_proxy():
    session = _dynasty_session()

    proxies_dealt = [rulebook_proxy(session.game, seat, LEGACY_PROXY_ID) for seat in PlayerId]
    assert [proxy.owner for proxy in proxies_dealt] == list(PlayerId)


def test_an_arc_without_legacy_deals_no_legacy_proxy(monkeypatch):
    # The Legacy keyword arrived with the Twenty Festivals CR, so the Clan Wars and Jade rulebooks
    # grant no Legacy ability.
    monkeypatch.setattr(ruleset, "ACTIVE", ruleset.IMPERIAL)
    session = _dynasty_session()

    assert rulebook_proxy(session.game, PlayerId.P1, LEGACY_PROXY_ID) is None


def test_legacy_resolves_as_a_rulebook_ability(reacting):
    resolved = []
    reacting(ActionResolved, "legacy_probe", lambda ctx: resolved.append(ctx.event) or [])
    session = _dynasty_session(legacy_in="deck")
    put_in_play(session.game, holding("P1-eyes", owner=PlayerId.P1, printed_id="legacy_probe"))
    session.act(PlayerId.P1, _legacy(session.game))
    session.submit(PlayerId.P1, DecisionResponse(("P1-h0",)))
    session.submit(PlayerId.P1, DecisionResponse(("P1-leg",)))
    session.submit(PlayerId.P1, DecisionResponse(("P1-pv1",)))

    assert [event.printed for event in resolved] == [False]


register_interrupt(
    "legacy_negate_probe",
    Interrupt(
        label="Interrupt: negate the action's effects",
        answers=Effect,
        interrupt=lambda game, source, effect: Interruption(Negated(effect)),
        answers_every=True,
    ),
)


def _opponent_holds_a_negation(state: TableState) -> TableState:
    """``state`` with P2 holding an Interrupt that negates every effect of an action. Dealt before
    the session starts, so a cancel's replay deals it too."""
    card = L5RCard.of(
        ActionPrint,
        id="P2-negate",
        name="Negate",
        printed_id="legacy_negate_probe",
        side=Side.FATE,
        owner=PlayerId.P2,
    )
    state.zones[ZoneKey(PlayerId.P2, ZoneRole.HAND)].add(register(state, card))
    return state


def test_the_search_waits_for_the_interrupt_step_after_the_banish():
    session = _dynasty_session_from(_opponent_holds_a_negation(_table(legacy_in="deck")))
    buried = _buried_province_card(session)
    session.act(PlayerId.P1, _legacy(session.game))
    session.submit(PlayerId.P1, DecisionResponse(("P1-h0",)))

    assert session.game.round.kind is RoundKind.INTERRUPT
    assert session.game.action_taken == "the ability on Legacy"  # the banner the opponent reads
    assert buried.peekers == frozenset()
    assert not session.game.hidden_card_shown

    session.act(PlayerId.P2, Pass())
    assert session.game.pending.resolver == legacy.FIND_RESOLVER
    assert buried.peekers == frozenset({PlayerId.P1})


def test_the_opponents_interrupt_question_can_be_cancelled():
    session = _dynasty_session_from(_opponent_holds_a_negation(_table(legacy_in="deck")))
    session.act(PlayerId.P1, _legacy(session.game))
    session.submit(PlayerId.P1, DecisionResponse(("P1-h0",)))
    session.act(PlayerId.P2, PlayInterrupt("P2-negate"))

    assert session.game.pending.seat is PlayerId.P2
    assert session.can_cancel(PlayerId.P2)
    session.cancel(PlayerId.P2)
    assert session.game.round.kind is RoundKind.INTERRUPT
    assert PlayInterrupt("P2-negate") in session.legal_actions(PlayerId.P2)


def test_a_negated_legacy_neither_searches_nor_loses_but_keeps_its_banish():
    session = _dynasty_session_from(_opponent_holds_a_negation(_table(legacy_in=None)))
    session.act(PlayerId.P1, _legacy(session.game))
    session.submit(PlayerId.P1, DecisionResponse(("P1-h0",)))
    session.act(PlayerId.P2, PlayInterrupt("P2-negate"))
    session.submit(PlayerId.P2, DecisionResponse(()))  # the cost of zero

    banish = session.game.table.zones[ZoneKey(PlayerId.P1, ZoneRole.FATE_BANISH)]
    assert not session.game.game_over
    assert session.game.pending is None
    assert [card.id for card in banish.cards] == ["P1-h0"]
