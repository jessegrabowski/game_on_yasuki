import tkinter as tk

import pytest

from yasuki_core.engine.players import PlayerId
from yasuki_core.engine.rules.projection import AttackView, BattlefieldView, UnitView
from yasuki_core.engine.rules.state import Segment
from yasuki_core.engine.table import ZoneKey, ZoneRole
from yasuki_gui.constants import CARD_W
from yasuki_gui.ui.battle_view import BattleView

from yasuki_core.game_pieces.constants import AttachmentType

from tests.yasuki_core.engine.builders import attachment, personality

P1, P2 = PlayerId.P1, PlayerId.P2


@pytest.fixture
def view():
    root = tk.Tk()
    root.withdraw()
    battle_view = BattleView(root)
    try:
        yield battle_view
    finally:
        root.destroy()


def _unit(name: str, force: int = 2, attached: tuple = ()) -> UnitView:
    return UnitView(leader=personality(name, force=force), attached=attached)


def _force(army: tuple[UnitView, ...]) -> int:
    return sum(unit.leader.force + sum(card.force for card in unit.attached) for unit in army)


def _battlefield(index: int, *, attacking=(), defending=(), strength=2, fought=False):
    return BattlefieldView(
        province=ZoneKey(P2, ZoneRole.PROVINCE, index),
        strength=strength,
        attacking=attacking,
        defending=defending,
        attacking_force=_force(attacking),
        defending_force=_force(defending),
        fought=fought,
    )


def _attack(*battlefields, current=None):
    return AttackView(
        attacker=P1, defender=P2, segment=Segment.FIGHT, current=current, battlefields=battlefields
    )


def _texts(view) -> list[str]:
    """Every piece of text the canvas is showing."""
    canvas = view.canvas
    return [
        canvas.itemcget(item, "text") for item in canvas.find_all() if canvas.type(item) == "text"
    ]


class _click:
    """The two fields :meth:`BattleView._on_click` reads off a Tk event."""

    def __init__(self, x: int, y: int):
        self.x, self.y = x, y


def _lane_widths(view) -> list[int]:
    """Each lane's width in pixels, in battlefield order."""
    return [right - left for _, (left, right) in sorted(view._lane_spans.items())]


def test_a_lane_is_drawn_per_province(view):
    view.refresh(_attack(_battlefield(0), _battlefield(1), _battlefield(2)))

    assert len(view._lane_spans) == 3


def test_the_lanes_are_side_by_side_and_do_not_overlap(view):
    view.refresh(_attack(_battlefield(0), _battlefield(1), _battlefield(2)))

    spans = [span for _, span in sorted(view._lane_spans.items())]
    assert all(left < right for left, right in spans)
    assert all(spans[i][1] <= spans[i + 1][0] for i in range(len(spans) - 1))


def test_a_lane_names_its_battlefield_and_province_strength(view):
    view.refresh(_attack(_battlefield(0, strength=4)))

    texts = _texts(view)
    assert "Battlefield 1" in texts
    assert "Province Strength 4" in texts


def test_a_lane_totals_the_force_on_each_side(view):
    """The figures are the ones resolution would use, so the view never disagrees with the
    battle it is showing."""
    view.refresh(
        _attack(
            _battlefield(
                0,
                attacking=(_unit("akodo", 3), _unit("matsu", 5)),
                defending=(_unit("hida", 6),),
            )
        )
    )

    assert "6F defending   \u00b7   8F attacking" in _texts(view)


def test_assigned_units_are_drawn_in_their_lane(view):
    """After assigning, a unit is drawn at its battlefield rather than at home — this is where, and
    it is the lane it was sent to rather than merely somewhere on the canvas."""
    view.refresh(_attack(_battlefield(0), _battlefield(1, attacking=(_unit("akodo"),))))

    x = view.canvas.coords("battle:akodo")[0]
    left, right = view._lane_spans[1]
    assert left <= x <= right


def test_collapsing_a_lane_narrows_it_and_widens_the_rest(view):
    view.refresh(_attack(_battlefield(0), _battlefield(1), _battlefield(2)))
    before = _lane_widths(view)

    view.toggle_lane(1)

    after = _lane_widths(view)
    assert after[1] < before[1]
    assert after[0] > before[0] and after[2] > before[2]


def test_reopening_a_lane_puts_it_back(view):
    view.refresh(_attack(_battlefield(0), _battlefield(1)))
    before = _lane_widths(view)

    view.toggle_lane(0)
    view.toggle_lane(0)

    assert _lane_widths(view) == before


def test_a_collapsed_lane_still_says_which_battlefield_it_is(view):
    view.refresh(_attack(_battlefield(0), _battlefield(1)))

    view.toggle_lane(1)

    canvas = view.canvas
    labels = {
        canvas.itemcget(item, "text"): canvas.coords(item)[0]
        for item in canvas.find_all()
        if canvas.type(item) == "text"
    }
    left, right = view._lane_spans[1]
    assert left <= labels["2"] <= right


def test_a_fought_battlefield_says_so(view):
    view.refresh(_attack(_battlefield(0, fought=True)))

    assert "Battlefield 1  (fought)" in _texts(view)


def test_units_sent_but_not_yet_assigned_are_named_apart(view):
    """Until the assignment is answered they are an intention, not an army standing there."""
    view.refresh(_attack(_battlefield(0), _battlefield(1)), {1: ("akodo", "matsu")})

    assert "sending akodo, matsu" in _texts(view)


def test_an_ended_attack_empties_the_view(view):
    view.refresh(_attack(_battlefield(0)))

    view.refresh(None)

    assert view.canvas.find_all() == ()


def test_an_army_is_laid_out_in_a_row_at_the_boards_own_spacing(view):
    """Units at a battlefield stand side by side, spaced the way the board spaces a home row —
    the same function lays out both, so improving one improves the other."""
    army = tuple(_unit(name) for name in ("akodo", "matsu", "ikoma"))
    view.refresh(_attack(_battlefield(0, attacking=army)))

    xs = [view.canvas.coords(f"battle:{unit.leader.id}")[0] for unit in army]
    ys = [view.canvas.coords(f"battle:{unit.leader.id}")[1] for unit in army]

    assert xs == sorted(xs) and len(set(xs)) == 3  # a row, not a stack
    assert len(set(ys)) == 1  # all at the same height
    assert xs[1] - xs[0] == xs[2] - xs[1]  # evenly spaced


def test_a_crowded_army_overlaps_rather_than_spilling_out_of_its_lane(view):
    army = tuple(_unit(f"unit{i}", 1) for i in range(8))
    view.refresh(_attack(_battlefield(0, attacking=army), _battlefield(1)))

    left, right = view._lane_spans[0]
    xs = [view.canvas.coords(f"battle:{unit.leader.id}")[0] for unit in army]

    assert min(xs) >= left - CARD_W // 2
    assert max(xs) <= right + CARD_W // 2


def test_a_units_attachments_are_drawn_with_it(view):
    """A Follower contributes to the Force the lane shows, so it has to be visible there too."""
    follower = attachment("banner", attachment_type=AttachmentType.FOLLOWER, force=2)
    view.refresh(_attack(_battlefield(0, attacking=(_unit("akodo", 3, attached=(follower,)),))))

    assert view.canvas.find_withtag("battle:banner")


def test_an_attachment_fans_off_its_personality_in_the_same_column(view):
    follower = attachment("banner", attachment_type=AttachmentType.FOLLOWER, force=2)
    view.refresh(_attack(_battlefield(0, defending=(_unit("hida", 3, attached=(follower,)),))))

    leader_x, leader_y = view.canvas.coords("battle:hida")[:2]
    banner_x, banner_y = view.canvas.coords("battle:banner")[:2]

    assert banner_x == leader_x  # same column
    assert banner_y < leader_y  # fanned up behind him


def test_the_defenders_stand_above_the_attackers(view):
    """Each lane faces the two armies across a divider, the Defender's on top — a lane that drew
    them the other way round would read as the wrong side winning."""
    view.refresh(_attack(_battlefield(0, attacking=(_unit("akodo"),), defending=(_unit("hida"),))))

    defender_y = view.canvas.coords("battle:hida")[1]
    attacker_y = view.canvas.coords("battle:akodo")[1]

    assert defender_y < attacker_y


def test_clicking_a_lane_header_collapses_that_lane(view):
    """The header is the control, so the click has to land on the lane it was aimed at rather than
    on whichever one happens to be first."""
    view.refresh(_attack(_battlefield(0), _battlefield(1), _battlefield(2)))
    left, right = view._lane_spans[2]

    view._on_click(_click(x=(left + right) // 2, y=10))

    assert _lane_widths(view)[2] < _lane_widths(view)[0]


def test_clicking_below_the_header_leaves_the_lanes_alone(view):
    """The cards live below it, and clicking one is not a request to fold the lane away."""
    view.refresh(_attack(_battlefield(0), _battlefield(1)))
    before = _lane_widths(view)
    left, right = view._lane_spans[1]

    view._on_click(_click(x=(left + right) // 2, y=300))

    assert _lane_widths(view) == before
