from app.game_pieces.fate import FateCard, FateAction, FateAttachment, FateRing
from app.game_pieces.constants import Side, AttachmentType, Timing, Element


def test_fatecard_allows_basic_construction():
    ok = FateCard(id="f1", name="OK", side=Side.FATE, focus=0, gold_cost=0)
    assert ok.focus == 0 and ok.gold_cost == 0


def test_fateaction_timings_normalized():
    a = FateAction(id="fa1", name="Act", side=Side.FATE, timings=[Timing.OPEN, Timing.BATTLE])  # type: ignore[list-item]
    assert isinstance(a.timings, tuple)
    assert a.timings == (Timing.OPEN, Timing.BATTLE)


def test_fateattachment_defaults_and_restrictions_tuple():
    att = FateAttachment(
        id="fa2",
        name="Katana",
        side=Side.FATE,
        attachment_type=AttachmentType.ITEM,
        attach_restrictions=["Personality"],
    )  # type: ignore[list-item]
    assert att.attachment_type is AttachmentType.ITEM
    assert isinstance(att.attach_restrictions, tuple)
    assert att.attach_restrictions == ("Personality",)


def test_fatering_element_default_and_override():
    ring = FateRing(id="r1", name="Ring of the Void", side=Side.FATE)
    assert ring.element is Element.VOID
    ring2 = FateRing(id="r2", name="Ring of Air", side=Side.FATE, element=Element.AIR)
    assert ring2.element is Element.AIR
