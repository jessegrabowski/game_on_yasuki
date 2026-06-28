from yasuki_core.engine.players import PlayerId
from yasuki_core.engine.table import DeckKey, ZoneKey, ZoneRole
from yasuki_core.engine.intents import Draw
from yasuki_core.game_pieces.constants import Side
from yasuki_gui.tags import card_tag, deck_tag, zone_tag

from tests.yasuki_gui.conftest import DummyEventNamespace


def _at(field, tag):
    """Monkeypatch-free tag resolver: make resolve_tag_at return ``tag`` for any event."""
    field.resolve_tag_at = lambda e: tag


class TestDoubleClick:
    def test_double_click_deck_draws(self, loaded):
        field, state = loaded
        hand = state.zones[ZoneKey(PlayerId.P1, ZoneRole.HAND)]
        before = len(hand.cards)
        _at(field, deck_tag(DeckKey(PlayerId.P1, Side.FATE)))
        field._controller.on_double_click(DummyEventNamespace(x=200, y=600))
        assert len(hand.cards) == before + 1

    def test_double_click_card_toggles_bow(self, loaded):
        field, state = loaded
        _at(field, card_tag("P1-SH"))
        field._controller.on_double_click(DummyEventNamespace(x=300, y=600))
        assert state.cards_by_id["P1-SH"].bowed is True

    def test_double_click_opponent_card_is_blocked(self, loaded):
        field, state = loaded
        _at(field, card_tag("P2-SH"))
        field._controller.on_double_click(DummyEventNamespace(x=300, y=200))
        assert state.cards_by_id["P2-SH"].bowed is False


class TestDrag:
    def test_drag_on_battlefield_commits_position(self, loaded):
        field, state = loaded
        tag = card_tag("P1-SH")
        sp = field.sprites[tag]
        _at(field, tag)
        field._controller.on_press(DummyEventNamespace(x=sp.x, y=sp.y))
        field._controller.on_motion(DummyEventNamespace(x=480, y=360))
        field._controller.on_release(DummyEventNamespace(x=480, y=360))
        assert state.positions["P1-SH"] == (480, 360)
        assert field.sprites[tag].x == 480

    def test_drag_card_onto_deck_moves_it_off_battlefield(self, loaded):
        field, state = loaded
        # A dynasty draw lands on the battlefield because every province is full.
        field.dispatch(Draw(DeckKey(PlayerId.P1, Side.DYNASTY)))
        drawn = state.battlefield.cards[-1]
        tag = card_tag(drawn.id)
        sp = field.sprites[tag]
        deck = state.decks[DeckKey(PlayerId.P1, Side.DYNASTY)]
        deck_count = len(deck.cards)
        _at(field, tag)
        field._controller.on_press(DummyEventNamespace(x=sp.x, y=sp.y))
        # Drop on the P1 dynasty deck (bottom-left).
        field._controller.on_motion(DummyEventNamespace(x=200, y=600))
        field._controller.on_release(DummyEventNamespace(x=200, y=600))
        assert tag not in field.sprites
        assert len(deck.cards) == deck_count + 1

    def test_deck_drag_out_creates_battlefield_sprite(self, loaded):
        field, state = loaded
        deck = state.decks[DeckKey(PlayerId.P1, Side.FATE)]
        deck_count = len(deck.cards)
        before_sprites = set(field.sprites)
        dv = field.decks[deck_tag(DeckKey(PlayerId.P1, Side.FATE))]
        _at(field, deck_tag(DeckKey(PlayerId.P1, Side.FATE)))
        field._controller.on_press(DummyEventNamespace(x=dv.x, y=dv.y))
        # Drag away from the deck towards the centre of the board.
        field._controller.on_motion(DummyEventNamespace(x=500, y=400))
        assert len(deck.cards) == deck_count - 1
        new_sprites = set(field.sprites) - before_sprites
        assert len(new_sprites) == 1
        assert card_tag(state.battlefield.cards[-1].id) in new_sprites


class TestMarquee:
    def test_marquee_selects_sprite(self, loaded):
        field, _ = loaded
        sp = field.sprites[card_tag("P1-SH")]
        # Background press starts a marquee; drag a box that encloses the sprite.
        _at(field, None)
        field._controller.on_press(DummyEventNamespace(x=sp.x - 60, y=sp.y - 80))
        field._controller.on_motion(DummyEventNamespace(x=sp.x + 60, y=sp.y + 80))
        field._controller.on_release(DummyEventNamespace(x=sp.x + 60, y=sp.y + 80))
        assert card_tag("P1-SH") in field._selected


class TestHotkeys:
    def test_hover_deck_draw_hotkey(self, loaded):
        field, state = loaded
        hand = state.zones[ZoneKey(PlayerId.P1, ZoneRole.HAND)]
        before = len(hand.cards)
        field._controller._hover_deck_tag = deck_tag(DeckKey(PlayerId.P1, Side.FATE))
        field._controller.on_key(DummyEventNamespace(keysym=field._controller._hotkeys.draw))
        assert len(hand.cards) == before + 1


class TestDecisionSelection:
    def test_clicking_a_candidate_hand_card_toggles_it(self, loaded):
        field, _ = loaded
        field.dispatch(Draw(DeckKey(PlayerId.P1, Side.FATE)))  # ensure a card in hand
        hand_tag = zone_tag(ZoneKey(PlayerId.P1, ZoneRole.HAND))
        hv = field.hands[hand_tag]
        card_id = hv.cards[0].id
        cx, cy = hv.center_for_index(0)

        field.begin_selection([card_id])
        _at(field, hand_tag)
        field._controller.on_press(DummyEventNamespace(x=cx, y=cy))
        assert card_id in field.selection

        field._controller.on_press(DummyEventNamespace(x=cx, y=cy))  # click again to deselect
        assert card_id not in field.selection

    def test_clicking_a_candidate_battlefield_card_toggles_it(self, loaded):
        # Board targets are selectable the same way as hand cards (readiness for ChooseTarget).
        field, _ = loaded
        sp = field.sprites[card_tag("P1-SH")]

        field.begin_selection(["P1-SH"])
        _at(field, card_tag("P1-SH"))
        field._controller.on_press(DummyEventNamespace(x=sp.x, y=sp.y))
        assert "P1-SH" in field.selection

    def test_non_candidate_click_is_ignored_while_selecting(self, loaded):
        field, _ = loaded
        sp = field.sprites[card_tag("P1-SH")]

        field.begin_selection(["other-id"])  # P1-SH is not a candidate
        _at(field, card_tag("P1-SH"))
        field._controller.on_press(DummyEventNamespace(x=sp.x, y=sp.y))
        assert field.selection == frozenset()
