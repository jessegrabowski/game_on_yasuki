from yasuki_core.engine.players import PlayerId
from yasuki_core.engine.redaction import HiddenCard
from yasuki_core.game_pieces.cards import L5RCard
from yasuki_core.game_pieces.constants import Side
from yasuki_gui.visuals.cardface import HiddenFace, to_render_card


def test_real_card_passes_through_unchanged():
    card = L5RCard(id="c1", name="Bushi", side=Side.DYNASTY, owner=PlayerId.P1)
    assert to_render_card(card) is card


def test_hidden_card_becomes_a_back_only_face():
    hidden = HiddenCard(card_id="h1", side=Side.FATE, owner=PlayerId.P2)
    face = to_render_card(hidden)

    assert isinstance(face, HiddenFace)
    assert face.id == "h1"
    assert face.side is Side.FATE
    assert face.owner is PlayerId.P2
    assert face.face_up is False
    # active_face resolves to itself so the visuals' front-art reads are harmless.
    assert face.active_face is face
    assert face.active_face.image_front is None
    assert face.active_face.name == ""
