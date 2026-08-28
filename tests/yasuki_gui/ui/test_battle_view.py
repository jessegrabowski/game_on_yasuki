import tkinter as tk

import pytest

from yasuki_core.engine.players import PlayerId
from yasuki_core.engine.rules.projection import AttackView, BattlefieldView, UnitView
from yasuki_core.engine.rules.state import BattleOutcome, Segment
from yasuki_core.engine.table import ZoneKey, ZoneRole
from yasuki_gui.constants import CARD_H, CARD_W
from yasuki_gui.ui.battle_view import (
    BattleView,
    _outcome_lines,
    FOOTER_H,
    LaneButton,
    MIN_ROW_STEP,
    PendingArmy,
    _rows,
)

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


def _battlefield(
    index: int,
    *,
    attacking=(),
    defending=(),
    strength=2,
    fought=False,
    occupant=None,
    outcome=None,
    destroyed_names=(),
):
    return BattlefieldView(
        province=ZoneKey(P2, ZoneRole.PROVINCE, index),
        occupant=occupant,
        strength=strength,
        attacking=attacking,
        defending=defending,
        attacking_force=_force(attacking),
        defending_force=_force(defending),
        fought=fought,
        outcome=outcome,
        destroyed_names=destroyed_names,
    )


def _attack(*battlefields, current=None):
    return AttackView(
        attacker=P1, defender=P2, segment=Segment.FIGHT, current=current, battlefields=battlefields
    )


def _font_size(font: str) -> int:
    """The point size out of a Tk font spec, whose family may or may not come back braced."""
    for token in str(font).replace("{", " ").replace("}", " ").split():
        if token.lstrip("-").isdigit():
            return abs(int(token))
    raise AssertionError(f"no size in font spec {font!r}")


def _text_at(view, text: str) -> tuple[float, float]:
    """Where the canvas item reading ``text`` sits."""
    for item in view.canvas.find_all():
        if view.canvas.type(item) == "text" and view.canvas.itemcget(item, "text") == text:
            return tuple(view.canvas.coords(item))
    raise AssertionError(f"no {text!r} on the canvas; got {_texts(view)}")


def _button(label: str) -> LaneButton:
    """A lane button whose press does nothing, for tests about what a lane shows."""
    return LaneButton(label, lambda: None)


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
    """The Strength stands alone under its label rather than inside a sentence, because it is the
    number the whole battle is measured against."""
    view.refresh(_attack(_battlefield(0, strength=4)))

    texts = _texts(view)
    assert "Battlefield 1" in texts
    assert "PROVINCE STRENGTH" in texts
    assert "4" in texts


def test_the_province_strength_is_the_largest_thing_in_the_lane(view):
    """It is what the attacker has to clear, so it outranks every other figure on the lane."""
    view.refresh(_attack(_battlefield(0, strength=4, attacking=(_unit("akodo", 3),))))

    sizes = {
        view.canvas.itemcget(item, "text"): view.canvas.itemcget(item, "font")
        for item in view.canvas.find_all()
        if view.canvas.type(item) == "text"
    }
    assert _font_size(sizes["4"]) > _font_size(sizes["3"])


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

    texts = _texts(view)
    assert "6" in texts
    assert "8" in texts


def test_each_sides_force_sits_in_the_corner_of_its_own_half(view):
    """A total floating anywhere in the lane says nothing about whose it is."""
    view.refresh(
        _attack(_battlefield(0, attacking=(_unit("akodo", 3),), defending=(_unit("hida", 6),)))
    )

    left, _ = view._lane_spans[0]
    defending = _text_at(view, "6")
    attacking = _text_at(view, "3")
    assert defending[0] < left + CARD_W  # both hug the lane's own edge
    assert attacking[0] < left + CARD_W
    assert defending[1] < attacking[1]  # the defenders hold the top half


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


def test_units_sent_but_not_yet_assigned_already_stand_at_their_battlefield(view):
    """The player has decided where they go; the engine being told on Done assigning is bookkeeping
    they should not have to watch for."""
    pending = PendingArmy(units=(_unit("akodo"), _unit("matsu")), force=4)

    view.refresh(_attack(_battlefield(0), _battlefield(1)), {1: pending})

    x = view.canvas.coords("battle:akodo")[0]
    left, right = view._lane_spans[1]
    assert left <= x <= right


def test_a_pending_army_counts_towards_the_force_its_side_shows(view):
    """Otherwise the total jumps the moment the assignment is answered, for no reason the player
    took any action to cause."""
    view.refresh(
        _attack(_battlefield(0, attacking=(_unit("akodo", 3),))),
        {0: PendingArmy(units=(_unit("matsu", 5),), force=5)},
    )

    assert "8" in _texts(view)


def test_only_a_lane_with_something_to_offer_shows_a_button(view):
    view.refresh(_attack(_battlefield(0), _battlefield(1)), buttons={1: _button("Fight here")})

    assert [text for text in _texts(view) if text == "Fight here"] == ["Fight here"]


def test_a_lane_button_reads_whatever_it_was_given(view):
    """The label comes from the question the engine is asking — a place to send an army during
    assignment, a battle to fight after."""
    view.refresh(_attack(_battlefield(0)), buttons={0: _button("Assign here")})

    assert "Assign here" in _texts(view)


def test_pressing_a_lane_button_takes_that_lane_action(view):
    """It sits under the battlefield it acts on, so pressing it is picking a place rather than
    reading a label and matching it to one."""
    pressed = []
    view.refresh(
        _attack(_battlefield(0), _battlefield(1)),
        buttons={
            0: LaneButton("Fight here", lambda: pressed.append(0)),
            1: LaneButton("Fight here", lambda: pressed.append(1)),
        },
    )
    left, right = view._lane_spans[1]

    view._on_click(_click((left + right) // 2, view._height() - 4))

    assert pressed == [1]


def test_a_click_under_a_lane_with_no_button_does_nothing(view):
    pressed = []
    view.refresh(
        _attack(_battlefield(0), _battlefield(1)),
        buttons={1: LaneButton("Fight here", lambda: pressed.append(1))},
    )
    left, right = view._lane_spans[0]

    view._on_click(_click((left + right) // 2, view._height() - 4))

    assert pressed == []


def test_the_province_card_stands_at_the_head_of_the_defending_side(view):
    """It is what the Defender's units are standing in front of, and what the attack is for."""
    view.refresh(
        _attack(
            _battlefield(0, defending=(_unit("hida"),), occupant=personality("shrine", owner=P2))
        )
    )

    province_y = view.canvas.coords("province:shrine")[1]
    defender_y = view.canvas.coords("battle:hida")[1]
    assert province_y < defender_y


def test_a_lane_with_the_room_keeps_its_three_rows_clear_of_each_other(view):
    """Given the height, the Province and both armies stand apart rather than stacking."""
    view.refresh(
        _attack(
            _battlefield(
                0,
                occupant=personality("shrine", owner=P2),
                defending=(_unit("hida"),),
                attacking=(_unit("akodo"),),
            )
        )
    )

    province = view.canvas.bbox("province:shrine")
    defending = view.canvas.bbox("battle:hida")
    attacking = view.canvas.bbox("battle:akodo")
    assert province[3] < defending[1]
    assert defending[3] < attacking[1]


def test_a_personality_is_drawn_over_the_cards_attached_to_him(view):
    """The tower fans up behind him, so he has to be the last thing drawn — otherwise a Follower
    covers the face of the Personality carrying it."""
    unit = UnitView(
        leader=personality("hida"),
        attached=(attachment("banner", attachment_type=AttachmentType.FOLLOWER),),
    )
    view.refresh(_attack(_battlefield(0, defending=(unit,))))

    order = view.canvas.find_all()
    assert order.index(view.canvas.find_withtag("battle:hida")[0]) > order.index(
        view.canvas.find_withtag("battle:banner")[0]
    )


def test_a_short_lane_steps_its_rows_closer_rather_than_dropping_one(view):
    """Cards are a fixed size, so a lane too short for three of them has only the spacing to give.
    Each row keeps a strip showing and the bottom row stays clear of the lane's button."""
    province, defending, _divider, attacking = _rows(260)

    assert province < defending < attacking  # still in order, still all three
    assert attacking - defending < CARD_H  # overlapping, which is the give
    assert defending - province >= MIN_ROW_STEP
    assert attacking + CARD_H // 2 <= 260 - FOOTER_H  # the button underneath stays uncovered


def _outcome(winner=P1, destroyed=(), province_destroyed=False, honor=None):
    return BattleOutcome(
        winner=winner,
        destroyed=destroyed,
        province_destroyed=province_destroyed,
        honor=honor or {},
    )


def test_a_lane_says_who_won_the_battle_fought_there(view):
    view.refresh(_attack(_battlefield(0, fought=True, outcome=_outcome(winner=P1))))

    assert "Attacker wins" in _texts(view)


def test_a_lane_says_when_the_defender_held_it(view):
    view.refresh(_attack(_battlefield(0, fought=True, outcome=_outcome(winner=P2))))

    assert "Defender wins" in _texts(view)


def test_a_tied_battle_says_so_rather_than_naming_a_winner(view):
    view.refresh(
        _attack(_battlefield(0, fought=True, outcome=_outcome(winner=None, destroyed=("a", "d"))))
    )

    assert "Tied" in _texts(view)


def test_a_battle_where_nothing_happened_says_that_much(view):
    """Distinct from a tie that destroyed both armies, and from a lane nobody has fought at — a
    lane that reports nothing cannot be told apart from one still to come."""
    view.refresh(_attack(_battlefield(0, fought=True, outcome=_outcome(winner=None))))

    assert "Nothing happened" in _texts(view)


def test_a_lane_reports_the_province_falling(view):
    view.refresh(_attack(_battlefield(0, fought=True, outcome=_outcome(province_destroyed=True))))

    assert "Province destroyed" in _texts(view)


def test_a_lane_names_the_cards_the_battle_destroyed(view):
    view.refresh(
        _attack(
            _battlefield(
                0, fought=True, outcome=_outcome(destroyed=("d",)), destroyed_names=("Hida Kisada",)
            )
        )
    )

    assert "Destroyed: Hida Kisada" in _texts(view)


def test_a_lane_reports_the_honor_that_moved(view):
    view.refresh(_attack(_battlefield(0, fought=True, outcome=_outcome(honor={P1: 4, P2: -2}))))

    texts = _texts(view)
    assert "P1 honor +4" in texts
    assert "P2 honor -2" in texts


def test_an_outcome_is_drawn_in_the_lane_it_belongs_to(view):
    """Every lane keeps its result for the rest of the phase, so a block on the wrong lane reports
    one battlefield's battle as another's."""
    view.refresh(
        _attack(_battlefield(0), _battlefield(1, fought=True, outcome=_outcome(winner=P1)))
    )

    left, right = view._lane_spans[1]
    assert left <= _text_at(view, "Attacker wins")[0] <= right


def test_the_outcome_block_leads_with_the_result_and_ends_with_the_honor():
    """The reading order is the design: who won, then what it cost the Province, then the dead, then
    the honor. Asserted against the lines rather than the canvas, since it is the order that is the
    decision and not where the text landed."""
    lines = _outcome_lines(
        _outcome(winner=P1, destroyed=("d",), province_destroyed=True, honor={P1: 4}),
        destroyed_names=("Hida Kisada",),
        attacker=P1,
    )

    assert [line.text for line in lines] == [
        "Attacker wins",
        "Province destroyed",
        "Destroyed: Hida Kisada",
        "P1 honor +4",
    ]


def test_the_outcome_block_shouts_only_the_result_and_the_province():
    """Emphasis is what separates what happened from the accounting of it."""
    lines = _outcome_lines(
        _outcome(winner=P1, destroyed=("d",), province_destroyed=True, honor={P1: 4}),
        destroyed_names=("Hida Kisada",),
        attacker=P1,
    )

    assert [line.emphatic for line in lines] == [True, True, False, False]


def test_a_lane_nobody_has_fought_at_reports_nothing(view):
    view.refresh(_attack(_battlefield(0)))

    assert not [text for text in _texts(view) if "wins" in text or "honor" in text]


def test_an_empty_province_draws_no_card(view):
    view.refresh(_attack(_battlefield(0, defending=(_unit("hida"),))))

    tags = {tag for item in view.canvas.find_all() for tag in view.canvas.gettags(item)}
    assert not [tag for tag in tags if tag.startswith("province:")]


def test_the_province_card_is_not_a_card_the_player_can_act_on(view):
    """It is the Defender's, and it is not a unit — offering the army menu on it lets a Holding be
    gathered into an army and shipped to the engine as part of the assignment."""
    asked = []
    view.on_card_menu = asked.append
    view.refresh(
        _attack(
            _battlefield(0, occupant=personality("shrine", owner=P2), defending=(_unit("hida"),))
        )
    )
    # By where the Province row is drawn rather than by its tag, so the test still asks about the
    # card under the pointer if the tagging changes.
    left, right = view._lane_spans[0]
    province_y = _rows(view._height())[0]

    view._on_context_click(_click((left + right) // 2, province_y))

    assert asked == []


def test_a_unit_in_a_lane_is_a_card_the_player_can_act_on(view):
    """The other half of the same rule: the lane is the only place a sent unit is drawn, so its menu
    has to be reachable there."""
    asked = []
    view.on_card_menu = asked.append
    view.refresh(_attack(_battlefield(0, defending=(_unit("hida"),))))
    left, top, right, bottom = view.canvas.bbox("battle:hida")

    view._on_context_click(_click((left + right) // 2, (top + bottom) // 2))

    assert asked == ["hida"]


def test_a_collapsed_lane_does_not_answer_the_button_it_is_not_showing(view):
    """Collapsing hides the button; a strip that still took the click would fight a battle at a
    battlefield the player cannot see."""
    pressed = []
    view.refresh(
        _attack(_battlefield(0), _battlefield(1)),
        buttons={0: LaneButton("Fight here", lambda: pressed.append(0))},
    )
    view.toggle_lane(0)
    left, right = view._lane_spans[0]

    view._on_click(_click((left + right) // 2, view._height() - 4))

    assert pressed == []


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
