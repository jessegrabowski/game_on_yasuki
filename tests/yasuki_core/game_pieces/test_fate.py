from yasuki_core.game_pieces.constants import Side, AttachmentType, Timing, Element
from yasuki_core.game_pieces.cards import L5RCard
from yasuki_core.game_pieces.prints import ActionPrint, AttachmentPrint, RingPrint
from yasuki_core.engine.players import PlayerId


def test_fateaction_timings_normalized():
    a = L5RCard.of(
        ActionPrint,
        id="fa1",
        name="Act",
        side=Side.FATE,
        timings=[Timing.OPEN, Timing.BATTLE],
        owner=PlayerId.P1,
    )  # type: ignore[list-item]
    assert isinstance(a.timings, tuple)
    assert a.timings == (Timing.OPEN, Timing.BATTLE)


def test_fateattachment_restrictions_normalized_to_tuple():
    att = L5RCard.of(
        AttachmentPrint,
        id="fa2",
        name="Katana",
        side=Side.FATE,
        attachment_type=AttachmentType.ITEM,
        attach_restrictions=["Personality"],
        owner=PlayerId.P1,
    )  # type: ignore[list-item]
    assert isinstance(att.attach_restrictions, tuple)
    assert att.attach_restrictions == ("Personality",)


def test_fatering_element_default():
    ring = L5RCard.of(
        RingPrint, id="r1", name="Ring of the Void", side=Side.FATE, owner=PlayerId.P1
    )
    assert ring.element is Element.VOID
