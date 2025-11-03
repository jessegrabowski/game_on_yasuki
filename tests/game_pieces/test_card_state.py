from app.game_pieces.cards import L5RCard
from app.game_pieces.constants import Side


def test_card_bow_and_unbow():
    c = L5RCard(id="c1", name="Test", side=Side.FATE)
    assert c.bowed is False

    c.bow()
    assert c.bowed is True

    # Idempotent bow
    c.bow()
    assert c.bowed is True

    c.unbow()
    assert c.bowed is False

    # Idempotent unbow
    c.unbow()
    assert c.bowed is False


def test_card_face_up_down_and_flip():
    c = L5RCard(id="c2", name="Test2", side=Side.DYNASTY)
    assert c.face_up is True

    c.turn_face_down()
    assert c.face_up is False

    # Idempotent
    c.turn_face_down()
    assert c.face_up is False

    c.turn_face_up()
    assert c.face_up is True

    c.flip()
    assert c.face_up is False
    c.flip()
    assert c.face_up is True


def test_card_invert_and_uninvert():
    c = L5RCard(id="c3", name="Rot", side=Side.FATE)
    assert c.inverted is False
    c.invert()
    assert c.inverted is True
    # Idempotent invert
    c.invert()
    assert c.inverted is True
    c.uninvert()
    assert c.inverted is False
    # Idempotent uninvert
    c.uninvert()
    assert c.inverted is False
