from yasuki_core.engine.players import PlayerId
from yasuki_core.engine.session import EngineSession
from yasuki_core.engine.table import DeckKey, TableState, ZoneKey, ZoneRole
from yasuki_core.engine.intents import Draw
from yasuki_core.game_pieces.constants import Side
from yasuki_gui.tags import card_tag, zone_tag

from tests.yasuki_gui.conftest import DummyEventNamespace


def _at(field, tag):
    """Monkeypatch-free tag resolver: make resolve_tag_at return ``tag`` for any event."""
    field.resolve_tag_at = lambda e: tag


def _in_rules_mode(field):
    """Put the field in rules mode, which is what gates the board menu."""
    session = EngineSession.start(TableState.empty_two_seat(), PlayerId.P1)
    field.render_snapshot(session.project(PlayerId.P1).table, PlayerId.P1)


class TestBoardMenu:
    def test_right_click_on_empty_board_opens_the_menu(self, loaded):
        field, _ = loaded
        opened = []
        field.on_board_menu = lambda: opened.append("opened")
        _in_rules_mode(field)
        _at(field, None)

        field._controller.on_context_click(DummyEventNamespace(x=10, y=10))

        assert opened == ["opened"]

    def test_right_click_on_a_card_leaves_the_board_menu_shut(self, loaded):
        # The rulebook abilities act on whole zones, so a right-click that lands on a card is not
        # asking for them — and a card's own actions are a left-click away.
        field, _ = loaded
        opened = []
        field.on_board_menu = lambda: opened.append("opened")
        _in_rules_mode(field)
        _at(field, card_tag("P1-SH"))

        field._controller.on_context_click(DummyEventNamespace(x=10, y=10))

        assert opened == []

    def test_both_right_click_buttons_are_bound(self, loaded):
        # Aqua calls a right-click Button-2 and X11 calls it Button-3, so binding only one leaves
        # the menu unreachable on half the platforms — and on the wrong one it fires on the wheel.
        field, _ = loaded

        assert {"<Button-2>", "<Button-3>"} <= set(field.bind())

    def test_the_sandbox_has_no_board_menu(self, loaded):
        # The manual surface has no rulebook abilities to offer, and right-click is free there.
        field, _ = loaded
        opened = []
        field.on_board_menu = lambda: opened.append("opened")
        _at(field, None)

        field._controller.on_context_click(DummyEventNamespace(x=10, y=10))

        assert field.rules_mode is False
        assert opened == []


class TestDoubleClick:
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


def _is_own_province(key, seat) -> bool:
    return isinstance(key, ZoneKey) and key.role is ZoneRole.PROVINCE and key.owner is seat


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

    def test_clicking_your_own_province_toggles_the_slot_when_it_is_a_candidate(self, loaded):
        """A Fortification attaches to the Province slot, so a decision names the slot rather than
        the card standing in it — and an empty Province has to be as clickable as a full one."""
        field, _ = loaded
        key = next(k for k in field._tag_to_key.values() if _is_own_province(k, field.seat))
        tag = zone_tag(key)
        zv = field.zones[tag]

        field.begin_selection([key.token])
        _at(field, tag)
        field._controller.on_press(DummyEventNamespace(x=zv.x, y=zv.y))

        assert field.selection == (key.token,)

    def test_a_province_click_still_picks_the_card_when_the_card_is_the_candidate(self, loaded):
        """Only a slot-token candidate claims the click; a decision over province cards is
        unaffected."""
        field, _ = loaded
        key = next(k for k in field._tag_to_key.values() if _is_own_province(k, field.seat))
        tag = zone_tag(key)
        zv = field.zones[tag]
        card_id = zv.cards[-1].id

        field.begin_selection([card_id])
        _at(field, tag)
        field._controller.on_press(DummyEventNamespace(x=zv.x, y=zv.y))

        assert field.selection == (card_id,)

    def test_non_candidate_click_is_ignored_while_selecting(self, loaded):
        field, _ = loaded
        sp = field.sprites[card_tag("P1-SH")]

        field.begin_selection(["other-id"])  # P1-SH is not a candidate
        _at(field, card_tag("P1-SH"))
        field._controller.on_press(DummyEventNamespace(x=sp.x, y=sp.y))
        assert field.selection == ()


class TestProvinceActivation:
    def test_clicking_your_own_province_resolves_its_card(self, loaded):
        field, state = loaded
        province = ZoneKey(PlayerId.P1, ZoneRole.PROVINCE, 0)
        expected = state.zones[province].cards[-1].id
        resolved = field._controller._card_at(zone_tag(province), DummyEventNamespace(x=0, y=0))
        assert resolved == expected

    def test_clicking_the_opponents_province_resolves_nothing(self, loaded):
        field, _ = loaded
        tag = zone_tag(ZoneKey(PlayerId.P2, ZoneRole.PROVINCE, 0))
        assert field._controller._card_at(tag, DummyEventNamespace(x=0, y=0)) is None
