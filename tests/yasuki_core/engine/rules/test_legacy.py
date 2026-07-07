from yasuki_core.engine import ops
from yasuki_core.engine.players import PlayerId
from yasuki_core.engine.table import TableState, ZoneKey, ZoneRole, DeckKey
from yasuki_core.game_pieces.constants import Side
from yasuki_core.game_pieces.fate import FateCard
from yasuki_core.game_pieces.dynasty import DynastyCard, DynastyHolding
from yasuki_core.engine.rules.actions import Legacy, Pass
from yasuki_core.engine.rules.decisions import ChooseLegacyCard, PlaceLegacy, DecisionResponse
from yasuki_core.engine.rules.state import GameState, Phase
from yasuki_core.engine.rules import flow
from yasuki_core.engine.rules.log import replay
from yasuki_core.engine.session import EngineSession


def _register(state: TableState, card):
    state.cards_by_id[card.id] = card
    return card


def _p1_provinces(table: TableState):
    return [
        zone
        for key, zone in table.zones.items()
        if key.owner is PlayerId.P1 and key.role is ZoneRole.PROVINCE
    ]


def _facedown_province(state: TableState, seat: PlayerId, card):
    _register(state, card)
    card.turn_face_down()
    state.zones[ops.create_province(state, seat)].add(card)
    return card


def _legacy_holding(seat: PlayerId, card_id: str) -> DynastyHolding:
    return DynastyHolding(
        id=card_id, name="Ancestral Shrine", side=Side.DYNASTY, owner=seat, keywords=("Legacy",)
    )


def _table(*, provinces: int = 3, hand: int = 1, legacy_in: str | None = "deck") -> TableState:
    """A two-seat table with P1 holding ``hand`` fate cards, ``provinces`` face-down provinces, and
    a filled dynasty deck. ``legacy_in`` seeds a Legacy holding in P1's ``"deck"`` or first
    ``"province"``; None leaves P1 with no findable Legacy card."""
    state = TableState.empty_two_seat()
    for i in range(provinces):
        _facedown_province(
            state,
            PlayerId.P1,
            DynastyCard(id=f"P1-pv{i}", name="P", side=Side.DYNASTY, owner=PlayerId.P1),
        )
    hand_zone = state.zones[ZoneKey(PlayerId.P1, ZoneRole.HAND)]
    for i in range(hand):
        hand_zone.add(
            _register(state, FateCard(id=f"P1-h{i}", name="H", side=Side.FATE, owner=PlayerId.P1))
        )
    deck = state.decks[DeckKey(PlayerId.P1, Side.DYNASTY)]
    deck.cards = [
        _register(
            state, DynastyCard(id=f"P1-dd{i}", name="D", side=Side.DYNASTY, owner=PlayerId.P1)
        )
        for i in range(3)
    ]
    if legacy_in == "deck":
        deck.cards.insert(0, _register(state, _legacy_holding(PlayerId.P1, "P1-leg")))
    elif legacy_in == "province":
        legacy = _register(state, _legacy_holding(PlayerId.P1, "P1-leg"))
        legacy.turn_face_down()  # only face-down province cards are searchable
        state.zones[ZoneKey(PlayerId.P1, ZoneRole.PROVINCE, 0)].cards = [legacy]
    return state


def _dynasty_session(**kwargs) -> EngineSession:
    session = EngineSession.start(_table(**kwargs), PlayerId.P1, seed=7)
    session.act(PlayerId.P1, Pass())  # Action -> Attack
    session.act(PlayerId.P1, Pass())  # Attack -> Dynasty
    return session


def test_legacy_candidates_finds_a_deck_or_face_down_province_card():
    # GameState.start does not reveal provinces, so the seeded face-down province card stays down.
    game_deck = GameState.start(_table(legacy_in="deck"), PlayerId.P1)
    game_prov = GameState.start(_table(legacy_in="province"), PlayerId.P1)
    game_none = GameState.start(_table(legacy_in=None), PlayerId.P1)

    assert [c.id for c in flow.legacy_candidates(game_deck, PlayerId.P1)] == ["P1-leg"]
    assert [c.id for c in flow.legacy_candidates(game_prov, PlayerId.P1)] == ["P1-leg"]
    assert flow.legacy_candidates(game_none, PlayerId.P1) == []


def test_legacy_does_not_search_a_face_up_province_card():
    state = _table(legacy_in=None)
    face_up_legacy = _register(
        state, _legacy_holding(PlayerId.P1, "P1-shown")
    )  # face-up by default
    state.zones[ZoneKey(PlayerId.P1, ZoneRole.PROVINCE, 0)].cards = [face_up_legacy]
    game = GameState.start(state, PlayerId.P1)

    assert (
        flow.legacy_candidates(game, PlayerId.P1) == []
    )  # a revealed province card is not searched


def test_legacy_search_pool_is_the_whole_deck_plus_face_down_provinces():
    game = GameState.start(_table(), PlayerId.P1)
    pool = flow.legacy_search_pool(game, PlayerId.P1)
    pool_ids = {card.id for card in pool}

    deck_ids = {c.id for c in game.table.decks[DeckKey(PlayerId.P1, Side.DYNASTY)].cards}
    assert deck_ids <= pool_ids  # every deck card is searchable, not just the Legacy holding
    province_in_pool = [c for c in pool if c.id.startswith("P1-pv")]
    assert province_in_pool and all(not c.face_up for c in province_in_pool)  # only face-down ones


def test_legacy_is_offered_in_the_dynasty_phase_with_a_card_to_banish():
    session = _dynasty_session()
    assert Legacy() in session.legal_actions(PlayerId.P1)


def test_legacy_is_not_offered_without_a_card_to_banish():
    session = _dynasty_session(hand=0)
    assert Legacy() not in session.legal_actions(PlayerId.P1)


def test_legacy_is_not_offered_outside_the_dynasty_phase():
    session = EngineSession.start(_table(), PlayerId.P1, seed=7)  # Action phase
    assert Legacy() not in session.legal_actions(PlayerId.P1)


def test_legacy_whiff_loses_the_game():
    session = _dynasty_session(legacy_in=None)
    session.act(PlayerId.P1, Legacy())
    session.submit(PlayerId.P1, DecisionResponse(("P1-h0",)))

    assert session.game.loser is PlayerId.P1
    assert session.game.game_over
    assert session.legal_actions(PlayerId.P1) == []  # a lost game offers no further actions


def test_legacy_banishes_the_chosen_hand_card():
    session = _dynasty_session(hand=2, legacy_in=None)
    session.act(PlayerId.P1, Legacy())
    session.submit(PlayerId.P1, DecisionResponse(("P1-h1",)))

    banish = session.game.table.zones[ZoneKey(PlayerId.P1, ZoneRole.FATE_BANISH)]
    assert [c.id for c in banish.cards] == ["P1-h1"]


def test_legacy_finds_a_deck_card_and_places_it_face_up_over_a_province():
    session = _dynasty_session(legacy_in="deck")
    session.act(PlayerId.P1, Legacy())
    session.submit(PlayerId.P1, DecisionResponse(("P1-h0",)))
    assert isinstance(session.game.pending, ChooseLegacyCard)

    session.submit(PlayerId.P1, DecisionResponse(("P1-leg",)))
    assert isinstance(session.game.pending, PlaceLegacy)

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
    flow.legacy(game)
    flow.submit(game, DecisionResponse(("P1-h0",)))
    flow.submit(game, DecisionResponse(("P1-leg",)))
    assert "P1-leg" not in game.pending.candidates  # the found card can't be its own sacrifice

    flow.submit(game, DecisionResponse(("P1-pv1",)))
    source = game.table.zones[ZoneKey(PlayerId.P1, ZoneRole.PROVINCE, 0)]
    assert len(source.cards) == 1 and source.cards[0].id != "P1-leg"  # refilled from the deck


def test_legacy_is_once_per_turn():
    session = _dynasty_session(legacy_in="deck")
    session.act(PlayerId.P1, Legacy())
    session.submit(PlayerId.P1, DecisionResponse(("P1-h0",)))
    session.submit(PlayerId.P1, DecisionResponse(("P1-leg",)))
    session.submit(PlayerId.P1, DecisionResponse(("P1-pv1",)))

    assert Legacy() not in session.legal_actions(PlayerId.P1)


def test_legacy_search_offers_every_found_card_to_choose_among():
    session = _dynasty_session(legacy_in="deck")  # seeds "P1-leg" in the deck
    deck = session.game.table.decks[DeckKey(PlayerId.P1, Side.DYNASTY)]
    deck.cards.insert(1, _register(session.game.table, _legacy_holding(PlayerId.P1, "P1-leg2")))
    session.act(PlayerId.P1, Legacy())
    session.submit(PlayerId.P1, DecisionResponse(("P1-h0",)))

    assert set(session.game.pending.candidates) == {"P1-leg", "P1-leg2"}


def test_legacy_places_the_chosen_card_not_a_default():
    session = _dynasty_session(legacy_in="deck")  # "P1-leg" is first in search order
    deck = session.game.table.decks[DeckKey(PlayerId.P1, Side.DYNASTY)]
    deck.cards.insert(1, _register(session.game.table, _legacy_holding(PlayerId.P1, "P1-leg2")))
    session.act(PlayerId.P1, Legacy())
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
    session.act(PlayerId.P1, Legacy())
    session.submit(PlayerId.P1, DecisionResponse(("P1-h0",)))
    session.submit(PlayerId.P1, DecisionResponse(("P1-leg",)))
    session.submit(PlayerId.P1, DecisionResponse(("P1-pv1",)))

    # The fieldless action, both re-derived decisions, and the deterministic reshuffle must all
    # rebuild identically from the log.
    assert replay(session.log) == session.game
