from app.game_pieces.fate import FateAction, FateAttachment, FateRing
from app.game_pieces.constants import Side, AttachmentType, Timing, Element


def test_fateaction_timings_normalized():
    a = FateAction(id="fa1", name="Act", side=Side.FATE, timings=[Timing.OPEN, Timing.BATTLE])  # type: ignore[list-item]
    assert isinstance(a.timings, tuple)
    assert a.timings == (Timing.OPEN, Timing.BATTLE)


def test_fateattachment_restrictions_normalized_to_tuple():
    att = FateAttachment(
        id="fa2",
        name="Katana",
        side=Side.FATE,
        attachment_type=AttachmentType.ITEM,
        attach_restrictions=["Personality"],
    )  # type: ignore[list-item]
    assert isinstance(att.attach_restrictions, tuple)
    assert att.attach_restrictions == ("Personality",)


def test_fatering_element_default():
    ring = FateRing(id="r1", name="Ring of the Void", side=Side.FATE)
    assert ring.element is Element.VOID
