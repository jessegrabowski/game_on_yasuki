import pytest

from yasuki_core.engine.players import PlayerId
from yasuki_core.engine.rules.projection import DuelistView, DuelView
from yasuki_core.engine.rules.vocabulary.segments import DuelStep
from yasuki_core.engine.redaction import HiddenCard
from yasuki_core.game_pieces.constants import Side
from yasuki_gui.ui.duel_view import _outcome_text, _sides, _source_to_draw

from tests.yasuki_core.engine.builders import personality

P1, P2 = PlayerId.P1, PlayerId.P2


def _side(seat: PlayerId) -> DuelistView:
    return DuelistView(seat=seat, duelist=None, focused=(), duel_stat=3, total=None)


def _duel(
    *,
    step: DuelStep = DuelStep.FOCUSING,
    winners: tuple[PlayerId, ...] = (),
    losers: tuple[PlayerId, ...] = (),
    decided: bool = False,
) -> DuelView:
    return DuelView(
        challenger=_side(P1),
        challenged=_side(P2),
        step=step,
        option=None,
        source_name="Sanctioned Duel",
        source=None,
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
    duel = _duel()
    challenger = DuelistView(seat=P1, duelist=duelist, focused=(), duel_stat=3, total=3)
    return DuelView(
        challenger=challenger,
        challenged=duel.challenged,
        step=duel.step,
        option=None,
        source_name="whatever",
        source=source,
        winners=(),
        losers=(),
        decided=False,
    )
