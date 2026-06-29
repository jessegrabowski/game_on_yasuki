from yasuki_core.engine.players import PlayerId
from yasuki_gui.services.actions import REGISTRY as ACTIONS, ActionContext
from yasuki_gui.services.permissions import can_interact
from yasuki_gui.tags import card_tag, zone_tag
from yasuki_core.engine.table import ZoneRole


class TestCanInteract:
    def test_public_and_own_allowed_opponent_denied(self, loaded):
        field, _ = loaded  # human is P1
        assert can_interact(field, None) is True
        assert can_interact(field, PlayerId.P1) is True
        assert can_interact(field, PlayerId.P2) is False


class TestActionAffordance:
    def test_bow_enabled_for_own_card_only(self, loaded):
        field, _ = loaded
        own = ActionContext(card_tag=card_tag("P1-SH"))
        opp = ActionContext(card_tag=card_tag("P2-SH"))
        assert ACTIONS["card.toggle_bow"].when(field, own) is True
        assert ACTIONS["card.toggle_bow"].when(field, opp) is False

    def test_province_fill_enabled_for_own_province(self, loaded):
        field, state = loaded
        key = next(k for k in state.zones if k.owner is PlayerId.P1 and k.role is ZoneRole.PROVINCE)
        # A filled province cannot be filled again, so empty it first.
        state.zones[key].cards.clear()
        ctx = ActionContext(zone_tag=zone_tag(key))
        assert ACTIONS["zone.fill"].when(field, ctx) is True
