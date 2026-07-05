from yasuki_core.game_pieces.cards import L5RCard
from yasuki_core.game_pieces.constants import Side


def test_card_bow_and_unbow():
    c = L5RCard(id="c1", name="Test", side=Side.FATE)
    assert c.bowed is False

    c.bow()
    assert c.bowed is True

    c.unbow()
    assert c.bowed is False


def test_card_face_up_down_and_flip():
    c = L5RCard(id="c2", name="Test2", side=Side.DYNASTY)
    assert c.face_up is True

    c.turn_face_down()
    assert c.face_up is False

    c.turn_face_up()
    assert c.face_up is True

    c.flip()
    assert c.face_up is False
    c.flip()
    assert c.face_up is True


def test_adjust_counter_accumulates_floors_at_zero_and_drops_the_key():
    c = L5RCard(id="c4", name="Farm", side=Side.DYNASTY)
    assert c.counters == {}

    c.adjust_counter("wealth", 2)
    assert c.counters == {"wealth": 2}

    c.adjust_counter("wealth", -1)
    assert c.counters == {"wealth": 1}

    # Removing past zero floors at zero and drops the key, keeping the dict canonical for equality.
    c.adjust_counter("wealth", -5)
    assert c.counters == {}


def test_counters_participate_in_card_equality():
    # A replay must detect counter drift, so counters compare (unlike note/art_swap, which don't).
    plain = L5RCard(id="c5", name="Farm", side=Side.DYNASTY)
    tokened = L5RCard(id="c5", name="Farm", side=Side.DYNASTY)
    tokened.adjust_counter("wealth", 1)
    assert plain != tokened


def test_card_invert_and_uninvert():
    c = L5RCard(id="c3", name="Rot", side=Side.FATE)
    assert c.inverted is False
    c.invert()
    assert c.inverted is True
    c.uninvert()
    assert c.inverted is False
