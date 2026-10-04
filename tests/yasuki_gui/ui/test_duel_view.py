import tkinter as tk

import pytest

from yasuki_core.engine.players import PlayerId
from yasuki_core.engine.rules.projection import DuelistView, DuelView
from yasuki_core.engine.rules.vocabulary.segments import DuelStep
from yasuki_core.engine.redaction import HiddenCard
from yasuki_core.game_pieces.constants import Side
from yasuki_gui.ui.duel_view import DuelPanel, _outcome_text, _panel_title, _sides, _source_to_draw

from tests.yasuki_core.engine.builders import personality

P1, P2 = PlayerId.P1, PlayerId.P2


def _side(
    seat: PlayerId,
    *,
    duelist=None,
    attached=(),
    focused=(),
    total=None,
) -> DuelistView:
    return DuelistView(
        seat=seat,
        duelist=duelist,
        attached=tuple(attached),
        focused=tuple(focused),
        duel_stat=3,
        total=total,
    )


def _duel(
    *,
    step: DuelStep = DuelStep.FOCUSING,
    winners: tuple[PlayerId, ...] = (),
    losers: tuple[PlayerId, ...] = (),
    decided: bool = False,
    challenger: DuelistView | None = None,
    challenged: DuelistView | None = None,
    option: PlayerId | None = None,
    source=None,
) -> DuelView:
    return DuelView(
        challenger=challenger or _side(P1),
        challenged=challenged or _side(P2),
        step=step,
        option=option,
        ordinal=1,
        source_name="Sanctioned Duel",
        source=source,
        winners=winners,
        losers=losers,
        decided=decided,
    )


@pytest.mark.parametrize(
    "duel, viewer, said",
    [
        (_duel(), P1, "Focus Effects resolve"),
        # Decided and lost by neither: a duelist left play, so nobody won and nobody lost.
        (_duel(step=DuelStep.ENDED, decided=True), P1, "The duel ended without resolution"),
        # A tie the Duelist rule cannot separate is lost by both (CR, Duel).
        (
            _duel(step=DuelStep.RESOLUTION, losers=(P1, P2), decided=True),
            P1,
            "Both Personalities lose the duel",
        ),
        (
            _duel(step=DuelStep.ENDED, winners=(P1,), losers=(P2,), decided=True),
            P1,
            "You win the duel",
        ),
        (
            _duel(step=DuelStep.ENDED, winners=(P1,), losers=(P2,), decided=True),
            P2,
            "Your opponent wins the duel",
        ),
    ],
)
def test_the_panel_reads_the_outcome_from_whether_the_duel_was_decided(duel, viewer, said):
    # An empty `winners` means both "nobody won" and "not decided yet", so reading it alone calls a
    # tie and a duel that ended early by the wrong names.
    assert _outcome_text(duel, viewer) == said


@pytest.mark.parametrize("viewer, near", [(P1, P1), (P2, P2), (None, P1)])
def test_the_seat_being_played_is_always_the_near_duelist(viewer, near):
    # The board draws the seat being played at the bottom, and a duel is read the same way wherever
    # the viewer sits in it. Outside a seated game the challenger is near.
    duel = _duel(step=DuelStep.ENDED, winners=(P1,), losers=(P2,), decided=True)

    sides = _sides(duel, viewer)

    assert sides[0].seat is near
    assert sides[1].seat is not near


def test_a_duelist_that_also_created_the_duel_is_not_drawn_twice():
    # A Personality whose own ability makes the duel is both a duelist and the duel's source. Two
    # sprites under one tag are one card to hit-testing and to the sprite cache.
    haikeru = personality("haikeru", owner=P1)
    strategy = personality("sanctioned", owner=P1)

    assert _source_to_draw(_with(source=haikeru, duelist=haikeru)) is None
    assert _source_to_draw(_with(source=strategy, duelist=haikeru)).id == "sanctioned"
    assert _source_to_draw(_with(source=None, duelist=haikeru)) is None
    # A duelist the viewer cannot identify is still the card it is, by the id its sprite carries.
    hidden = HiddenCard(card_id="haikeru", side=Side.DYNASTY, owner=P1)
    assert _source_to_draw(_with(source=haikeru, duelist=hidden)) is None


def _with(*, source, duelist) -> DuelView:
    """A duel carrying ``source`` as its creator and ``duelist`` as the challenger's Personality."""
    return _duel(challenger=_side(P1, duelist=duelist, total=3), source=source)


@pytest.mark.parametrize(
    "duel, titled",
    [
        (_duel(), "Duel: Sanctioned Duel"),
        (None, "Duel"),
    ],
)
def test_the_panel_is_named_after_the_card_that_created_the_duel(duel, titled):
    # The duel's source is drawn beside it only when it is not one of the duelists, so the title is
    # the one place the card is always named.
    assert _panel_title(duel) == titled


@pytest.fixture
def panel():
    root = tk.Tk()
    root.withdraw()
    built = DuelPanel(root)
    try:
        yield built
    finally:
        root.destroy()


def _with_option(seat, step=DuelStep.FOCUSING) -> DuelView:
    return _duel(step=step, option=seat)


def test_the_duelist_holding_the_option_is_marked(panel):
    # Which duelist is being asked is the one thing an alternating focusing loop does not show on
    # the cards, and both sides are drawn the same way.
    panel.refresh(_with_option(P1), viewer=P1)
    near = panel.canvas.bbox("duel-option")
    panel.refresh(_with_option(P2), viewer=P1)
    far = panel.canvas.bbox("duel-option")

    assert near is not None and far is not None
    assert near[1] > far[1]


def test_nothing_holds_the_option_once_the_focusing_is_over(panel):
    panel.refresh(_with_option(P1, step=DuelStep.REVEAL), viewer=P1)

    assert panel.canvas.bbox("duel-option") is None


def _unit(duelist, attached=()) -> DuelView:
    """A focusing duel whose near side is ``duelist`` carrying ``attached``."""
    return _duel(challenger=_side(P1, duelist=duelist, attached=attached, total=3))


def test_a_duelist_is_drawn_with_the_cards_attached_to_him(panel):
    # A duel is fought by the unit, so what is attached has to be on the panel and has to be
    # hit-testable, not just the Personality.
    blade = personality("blade", owner=P1)
    panel.refresh(_unit(personality("hida", owner=P1), [blade]), viewer=P1)

    assert panel.canvas.bbox("duel:hida") is not None
    assert panel.canvas.bbox("duel:blade") is not None


def test_an_attachment_rides_clear_of_the_personality_it_is_on(panel):
    # Each card's title bar has to clear the one it rides, which is the whole point of the tower.
    panel.refresh(_unit(personality("hida", owner=P1), [personality("blade", owner=P1)]), viewer=P1)

    leader = panel.canvas.bbox("duel:hida")
    attached = panel.canvas.bbox("duel:blade")

    assert leader is not None and attached is not None
    assert attached[1] < leader[1]


def test_the_far_duelists_attachments_stay_on_the_panel(panel):
    # The far side's stack grows toward the top edge, so it is anchored by its top rather than by
    # the Personality: anchored the other way it climbs off the panel as the unit grows.
    far = _side(
        P2,
        duelist=personality("rival", owner=P2),
        attached=[personality(f"att{index}", owner=P2) for index in range(4)],
    )
    panel.refresh(_duel(challenged=far), viewer=P1)

    tops = [panel.canvas.bbox(f"duel:att{index}") for index in range(4)]

    assert all(box is not None for box in tops)
    assert min(box[1] for box in tops) >= 0
