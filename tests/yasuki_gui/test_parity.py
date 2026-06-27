from yasuki_core.engine.players import PlayerId
from yasuki_core.engine.table import BoardPos, FlipFace
from yasuki_core.game_pieces.cards import L5RCard
from yasuki_core.game_pieces.constants import Side
from yasuki_gui.services import actions
from yasuki_gui.services.actions import REGISTRY as ACTIONS, ActionContext
from yasuki_gui.tags import card_tag


def _tokens(state):
    return [c for c in state.battlefield.cards if c.is_token]


def _inject_double_faced(state, owner=PlayerId.P1):
    back = L5RCard(id="DF-back", name="Back Face", side=Side.DYNASTY)
    front = L5RCard(
        id="DF",
        name="Front Face",
        side=Side.DYNASTY,
        owner=owner,
        back_card_id="DF-back",
        back=back,
    )
    state.cards_by_id["DF"] = front
    state.battlefield.add(front)
    state.positions["DF"] = BoardPos(100.0, 100.0)
    return front


class TestTokens:
    def test_spawn_token_adds_battlefield_sprite(self, loaded):
        field, state = loaded
        before = len(field.sprites)
        actions.spawn_token(field, "Bushi", Side.DYNASTY, BoardPos(400.0, 400.0))
        assert len(field.sprites) == before + 1
        token = _tokens(state)[-1]
        assert token.name == "Bushi"
        assert card_tag(token.id) in field.sprites

    def test_fresh_token_id_skips_taken_ids(self, loaded):
        field, state = loaded
        first = actions.fresh_token_id(state)
        actions.spawn_token(field, "T", Side.DYNASTY, BoardPos(0.0, 0.0))
        assert first in state.cards_by_id
        assert actions.fresh_token_id(state) != first

    def test_duplicate_copies_face_and_side(self, loaded):
        field, state = loaded
        actions.spawn_token(field, "Original", Side.FATE, BoardPos(300.0, 300.0))
        original = _tokens(state)[-1]
        actions.duplicate_card(field, original.id)
        copy = _tokens(state)[-1]
        assert copy.id != original.id
        assert (copy.name, copy.side) == ("Original", Side.FATE)
        assert copy.is_token  # a duplicate is itself a removable token

    def test_remove_only_offered_for_tokens(self, loaded):
        field, state = loaded
        actions.spawn_token(field, "Temp", Side.DYNASTY, BoardPos(200.0, 200.0))
        token = _tokens(state)[-1]
        assert ACTIONS["card.remove"].when(field, ActionContext(card_tag=card_tag(token.id)))
        assert not ACTIONS["card.remove"].when(field, ActionContext(card_tag=card_tag("P1-SH")))

    def test_remove_takes_token_off_the_table(self, loaded):
        field, state = loaded
        actions.spawn_token(field, "Temp", Side.DYNASTY, BoardPos(200.0, 200.0))
        token = _tokens(state)[-1]
        ACTIONS["card.remove"].run(field, ActionContext(card_tag=card_tag(token.id)))
        assert token.id not in state.cards_by_id
        assert card_tag(token.id) not in field.sprites


class TestNotes:
    def test_set_and_clear_note(self, loaded):
        field, state = loaded
        actions.apply_note(field, "P1-SH", "dead")
        assert state.cards_by_id["P1-SH"].note == "dead"
        actions.apply_note(field, "P1-SH", "")
        assert state.cards_by_id["P1-SH"].note is None

    def test_note_offered_only_for_face_up_cards(self, loaded):
        field, state = loaded
        assert ACTIONS["card.set_note"].when(field, ActionContext(card_tag=card_tag("P1-SH")))
        state.cards_by_id["P1-SH"].turn_face_down()
        assert not ACTIONS["card.set_note"].when(field, ActionContext(card_tag=card_tag("P1-SH")))


class TestFlipFace:
    def test_offered_only_for_double_faced_cards(self, loaded):
        field, state = loaded
        _inject_double_faced(state)
        field.reconcile_all()
        assert ACTIONS["card.flip_face"].when(field, ActionContext(card_tag=card_tag("DF")))
        assert not ACTIONS["card.flip_face"].when(field, ActionContext(card_tag=card_tag("P1-SH")))

    def test_flip_face_toggles_active_face(self, loaded):
        field, state = loaded
        front = _inject_double_faced(state)
        field.reconcile_all()
        assert front.active_face is front
        field.dispatch(FlipFace((front.id,)))
        assert front.showing_back is True
        assert front.active_face is front.back
