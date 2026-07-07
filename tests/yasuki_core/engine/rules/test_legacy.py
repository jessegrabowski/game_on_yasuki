from yasuki_core.engine import ops
from yasuki_core.engine.players import PlayerId
from yasuki_core.engine.table import TableState, ZoneKey, ZoneRole, DeckKey
from yasuki_core.game_pieces.constants import Side
from yasuki_core.game_pieces.fate import FateCard
from yasuki_core.game_pieces.dynasty import DynastyCard, DynastyHolding
from yasuki_core.engine.rules.actions import Legacy, Pass
from yasuki_core.engine.rules.decisions import ChooseLegacyCard, PlaceLegacy, DecisionResponse
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
        state.zones[ZoneKey(PlayerId.P1, ZoneRole.PROVINCE, 0)].cards = [
            _register(state, _legacy_holding(PlayerId.P1, "P1-leg"))
        ]
    return state


def _dynasty_session(**kwargs) -> EngineSession:
    session = EngineSession.start(_table(**kwargs), PlayerId.P1, seed=7)
    session.act(PlayerId.P1, Pass())  # Action -> Attack
    session.act(PlayerId.P1, Pass())  # Attack -> Dynasty
    return session


def test_legacy_candidates_finds_cards_in_the_deck_and_provinces():
    deck_only = _table(legacy_in="deck")
    province_only = _table(legacy_in="province")
    none = _table(legacy_in=None)
    game_deck = EngineSession.start(deck_only, PlayerId.P1).game
    game_prov = EngineSession.start(province_only, PlayerId.P1).game
    game_none = EngineSession.start(none, PlayerId.P1).game

    assert [c.id for c in flow.legacy_candidates(game_deck, PlayerId.P1)] == ["P1-leg"]
    assert [c.id for c in flow.legacy_candidates(game_prov, PlayerId.P1)] == ["P1-leg"]
    assert flow.legacy_candidates(game_none, PlayerId.P1) == []


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


def test_legacy_places_a_province_card_and_refills_its_old_province():
    session = _dynasty_session(legacy_in="province")
    session.act(PlayerId.P1, Legacy())
    session.submit(PlayerId.P1, DecisionResponse(("P1-h0",)))
    session.submit(PlayerId.P1, DecisionResponse(("P1-leg",)))
    # The province holding the found card cannot be its own sacrifice.
    assert "P1-leg" not in session.game.pending.candidates

    session.submit(PlayerId.P1, DecisionResponse(("P1-pv1",)))
    source = session.game.table.zones[ZoneKey(PlayerId.P1, ZoneRole.PROVINCE, 0)]
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
