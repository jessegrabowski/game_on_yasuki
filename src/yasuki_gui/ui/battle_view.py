import tkinter as tk
from collections.abc import Callable
from dataclasses import dataclass
from typing import NamedTuple

from yasuki_core.engine.players import PlayerId
from yasuki_core.engine.rules.modifiers import Stat
from yasuki_core.engine.rules.projection import AttackView, BattlefieldView, UnitView
from yasuki_core import ruleset
from yasuki_core.engine.rules.state import BattleOutcome, BattleSegment
from yasuki_gui import theme
from yasuki_gui.constants import CARD_H, CARD_W
from yasuki_gui.labels import BATTLE_SEGMENT_CHIPS
from yasuki_gui.layout import COLUMN_STEP, centered_row, unit_tower_positions
from yasuki_gui.ui.floating_panel import BORDER, FloatingPanel, TITLEBAR_H
from yasuki_gui.ui.geometry import widget_size
from yasuki_gui.visuals.cardface import RenderCard, to_render_card
from yasuki_gui.visuals.sprite import CardSpriteVisual

# What a unit's sprite is tagged with here, and what a right-click reads back off it.
_CARD_TAG = "battle:"
# The Defender's Province card, tagged apart because it is not a unit: it belongs to the seat
# being attacked, and nothing the player can do to a unit applies to it.
_PROVINCE_TAG = "province:"
# The lane's own army total, tagged apart from the per-card stamps so a reader — and a test —
# can tell an army's Force from the Force of one card standing in it.
_ARMY_FORCE_TAG = "army-force"
# The lane's Battle Sequence strip. Every cell carries the strip's own tag and a second naming its
# segment, the way a card's sprite carries its id — so which cell is lit is a question about the
# canvas rather than about where things landed on it.
_SEQUENCE_TAG = "sequence"
# How wide a lane is once collapsed: enough for its number, and no more.
COLLAPSED_W = 34
LANE_GAP = 6
# The band holding the lane's name and the Province Strength under it, which is the number the
# battle is about. It sits on the Province's own side of the lane, so mirroring moves it to the foot,
# where it stacks above the button rather than displacing it.
HEADER_H = 74
# The strip along the bottom holding the lane's own button, whichever way the lane faces: a control
# that moved with the orientation would be somewhere new every time the seat changed roles.
FOOTER_H = 36
# How far the footer's contents hold off the lane's own edges.
FOOTER_INSET = 8
# What a mirrored lane leaves above its topmost row, standing in for the heading band that is no
# longer up there to space the cards off the panel's edge.
LANE_MARGIN = 10
# How far each side's Force total sits in from the corner it marks.
FORCE_INSET = 12
# The least a lane steps between its rows of cards. The step normally comes out of the height, so
# this only binds on a lane crushed shorter than three cards can be stacked in at all — small enough
# that it does not push the bottom row over the lane's button on any lane worth reading.
MIN_ROW_STEP = 16
# How tall a line of the outcome block is.
OUTCOME_LINE_H = 16
# The tightest a row of units compresses before cards start hiding each other entirely.
MIN_STEP = 22
# The narrowest an open lane goes, however many of them are competing for the width.
MIN_LANE_W = CARD_W + 10
# The size the panel is built at, which is what its canvas asks for before Tk lays it out. What it
# actually opens over is the board's own, decided by whoever shows it.
PANEL_W = 900
PANEL_H = 600


def _sequence_tag(segment: BattleSegment) -> str:
    """The canvas tag every part of ``segment``'s cell in a lane's sequence strip carries."""
    return f"{_SEQUENCE_TAG}:{segment.value}"


@dataclass(frozen=True, slots=True)
class LaneButton:
    """A lane's own button: what it says, and what pressing it does.

    Carried per lane rather than named by the view, because what a battlefield offers depends on
    what the engine is asking — a place to send units during assignment, a battle to fight after.

    Attributes
    ----------
    label : str
        What the button reads.
    press : callable
        Taken with no arguments when the button is clicked.
    enabled : bool
        Whether pressing it does anything. A disabled button is still drawn, so a battlefield the
        player could send units to says so before they have picked any. Default True.
    """

    label: str
    press: Callable[[], None]
    enabled: bool = True


@dataclass(frozen=True, slots=True)
class PendingArmy:
    """Units the player has sent to a battlefield but not yet answered the engine with.

    Attributes
    ----------
    units : tuple of UnitView
        The units standing there, drawn exactly as an assigned one is.
    force : int
        Their Force, totalled the way resolution would, so the lane's number does not jump when the
        assignment is answered and the engine starts counting them itself.
    """

    units: tuple[UnitView, ...]
    force: int


class _Army(NamedTuple):
    """One side of a battlefield as the lane draws it.

    Attributes
    ----------
    units : tuple of UnitView
        The units standing there, whether the engine has been told about them or not.
    force : int
        Their Force, totalled the way resolution would.
    """

    units: tuple[UnitView, ...]
    force: int


def _armies(
    view: BattlefieldView, sent: PendingArmy | None, *, viewer_defends: bool
) -> tuple[_Army, _Army]:
    """The two sides of ``view``, with anything sent but not yet assigned already standing in.

    A player sends only their own units, so what is waiting joins the side they are on.

    Parameters
    ----------
    view : BattlefieldView
        The battlefield as the engine reports it.
    sent : PendingArmy or None
        Units picked for this battlefield and not yet answered for. None when there are none.
    viewer_defends : bool
        Whether the seat being played is the one under attack, which is whose units ``sent`` holds.

    Returns
    -------
    defence : _Army
        The Defender's side.
    offence : _Army
        The Attacker's side.
    """
    defence = _Army(view.defending, view.defending_force)
    offence = _Army(view.attacking, view.attacking_force)
    if sent is None:
        return defence, offence
    if viewer_defends:
        return _Army(defence.units + sent.units, defence.force + sent.force), offence
    return defence, _Army(offence.units + sent.units, offence.force + sent.force)


def _bands(height: int, *, mirrored: bool = False) -> tuple[int, int]:
    """The space a lane lays its cards out in: what the heading band and the button band leave.

    The heading belongs beside the Province it names and so changes ends with the lane; the button
    keeps the foot, so a mirrored lane carries both there.

    Parameters
    ----------
    height : int
        The lane's height in pixels.
    mirrored : bool, optional
        Whether the lane is turned over. Default False.

    Returns
    -------
    top : int
        The first row's ceiling.
    bottom : int
        The last row's floor.
    """
    if mirrored:
        return LANE_MARGIN, height - FOOTER_H - HEADER_H
    return HEADER_H, height - FOOTER_H


def _rows(height: int, *, mirrored: bool = False) -> tuple[int, int, int, int]:
    """Where a lane's three rows of cards sit, and where the divider between the sides goes.

    The Province, the Defender's units and the Attacker's fill the space :func:`_bands` leaves. A
    lane with room for all three spreads them apart; a shorter one steps them closer until they
    overlap, each row keeping enough of itself showing to be read, rather than pushing the last row
    out of sight. Cards are a fixed size, so the rows moving is the only give there is.

    Parameters
    ----------
    height : int
        The lane's height in pixels.
    mirrored : bool, optional
        Whether to reflect the rows so the Defender's side is the lower one. Default False, which
        puts the Province at the head of the lane.

    Returns
    -------
    province : int
        The centre line of the Province's own card.
    defending : int
        The centre line of the Defender's units.
    divider : int
        Where the line between the two sides is drawn.
    attacking : int
        The centre line of the Attacker's units.
    """
    top, bottom = _bands(height, mirrored=mirrored)
    step = max((bottom - top - CARD_H) // 2, MIN_ROW_STEP)
    province = top + CARD_H // 2
    defending = province + step
    divider, attacking = defending + step // 2, defending + step
    if not mirrored:
        return province, defending, divider, attacking
    band = top + bottom
    return band - province, band - defending, band - divider, band - attacking


class _OutcomeLine(NamedTuple):
    """One line of the outcome block, and whether it is the kind that gets the loud type."""

    text: str
    emphatic: bool


def _outcome_lines(
    outcome: BattleOutcome, destroyed_names: tuple[str, ...], attacker: PlayerId
) -> list[_OutcomeLine]:
    """What the outcome block says, one line at a time, each flagged as emphatic or not.

    A battle where nothing happened still says so — a lane that reports nothing is one the player
    cannot tell from a lane that has not been fought at.
    """
    if outcome.winner is None:
        headline = "Tied" if outcome.destroyed else "Nothing happened"
    else:
        headline = "Attacker wins" if outcome.winner is attacker else "Defender wins"
    lines = [_OutcomeLine(headline, True)]
    if outcome.province_destroyed:
        lines.append(_OutcomeLine("Province destroyed", True))
    if destroyed_names:
        lines.append(_OutcomeLine(f"Destroyed: {', '.join(destroyed_names)}", False))
    for seat, delta in sorted(outcome.honor.items(), key=lambda item: item[0].name):
        lines.append(_OutcomeLine(f"{seat.name} honor {delta:+d}", False))
    return lines


class BattleView(FloatingPanel):
    """The attack in progress, drawn as one vertical lane per battlefield.

    The board draws two whole tableaux and cannot show four battlefields legibly, so this is where
    an attack is read: each lane leads with the Province Strength the attackers have to clear, marks
    each side's Force in its own corner, and draws the units standing there with the same sprites the
    board uses. A lane collapses to a strip when the player wants to concentrate on one battlefield.

    A window inside the game rather than one the desktop puts beside it: it floats over the board,
    and the player drags it clear of whatever they want to look at underneath.
    """

    def __init__(self, master: tk.Misc):
        super().__init__(master, "Attack", width=PANEL_W, height=PANEL_H)
        # Sized to the panel it fills, so the layout it computes before Tk maps it is the one it
        # ends up with.
        self.canvas = tk.Canvas(
            self.body,
            bg=theme.SURFACE,
            highlightthickness=0,
            width=PANEL_W - 2 * BORDER,
            height=PANEL_H - TITLEBAR_H - 2 * BORDER,
        )
        self.canvas.pack(fill="both", expand=True)
        # A unit in a lane is still the player's to recall, and the lane is now the only place it
        # is drawn — so the picking and the menu the board gives its cards are reachable here too.
        self.on_card_menu: Callable[[str], None] | None = None
        self.on_card_click: Callable[[str], None] | None = None
        self._collapsed: set[int] = set()
        self._attack: AttackView | None = None
        self._pending: dict[int, PendingArmy] = {}
        self._selected: frozenset[str] = frozenset()
        self._stats: dict[str, dict[Stat, int]] = {}
        # Whose side of the lane is the near one, following the board's habit of drawing the
        # seat being played at the bottom. None outside a seated game, where the Attacker is near.
        self._viewer: PlayerId | None = None
        self._buttons: dict[int, LaneButton] = {}
        self._lane_spans: dict[int, tuple[int, int]] = {}
        self.canvas.bind("<Configure>", lambda _event: self._redraw())
        self.canvas.bind("<Button-1>", self._on_click)
        # Aqua reports a right-click as Button-2, X11 and Windows as Button-3, as on the board.
        self.canvas.bind("<Button-2>", self._on_context_click)
        self.canvas.bind("<Button-3>", self._on_context_click)

    def refresh(
        self,
        attack: AttackView | None,
        pending: dict[int, PendingArmy] | None = None,
        buttons: dict[int, LaneButton] | None = None,
        selected: frozenset[str] = frozenset(),
        stats: dict[str, dict[Stat, int]] | None = None,
        viewer: PlayerId | None = None,
    ) -> None:
        """Redraw for ``attack``, or empty the view when there is none.

        Parameters
        ----------
        attack : AttackView, optional
            The attack in progress, or None outside one.
        pending : dict mapping int to PendingArmy, optional
            Units sent to a battlefield but not yet assigned, by battlefield. They draw at the
            battlefield like any assigned unit. Default None.
        buttons : dict mapping int to LaneButton, optional
            What each battlefield offers the player right now. Only these lanes show a button.
            Default None.
        selected : frozenset of str, optional
            The ids of the cards the player has picked, drawn with a selection ring. Default empty.
        stats : dict mapping str to dict, optional
            :attr:`GameView.stats`, so a unit in a lane reports the same Force the lane's total was
            built from. Default None.
        viewer : PlayerId, optional
            The seat being played, whose side of every lane is drawn as the near one. Default None,
            which draws the Attacker near.
        """
        self._attack = attack
        self._pending = pending or {}
        self._buttons = buttons or {}
        self._selected = selected
        self._stats = stats or {}
        self._viewer = viewer
        if attack is not None:
            self._collapsed &= set(range(len(attack.battlefields)))
        self._redraw()

    def toggle_lane(self, index: int) -> None:
        """Collapse ``index``'s lane to a strip, or open it back up."""
        self._collapsed ^= {index}
        self._redraw()

    def lane_at(self, x: int) -> int | None:
        """Which lane the canvas x-coordinate ``x`` falls in, or None between lanes."""
        for index, (left, right) in self._lane_spans.items():
            if left <= x < right:
                return index
        return None

    def _viewer_defends(self) -> bool:
        """Whether the seat being played is the one under attack, which decides both which way its
        lanes face and which army the units it has sent join."""
        return (
            self._attack is not None
            and self._viewer is not None
            and self._viewer is not self._attack.attacker
        )

    def _on_click(self, event: tk.Event) -> None:
        """Route a click to the lane it landed in: its heading collapses it, its button resolves it.

        The button keeps the foot of the lane, but the heading changes ends with it, so a mirrored
        lane is collapsed from the band just above the button rather than from the top.
        """
        index = self.lane_at(event.x)
        if index is None:
            return
        height = self._height()
        button = self._buttons.get(index)
        if button is not None and event.y >= height - FOOTER_H:
            # A collapsed lane draws no button, and a strip that answered one anyway would fight a
            # battle at a battlefield the player cannot see.
            if button.enabled and index not in self._collapsed:
                button.press()
            return
        heading_top = height - FOOTER_H - HEADER_H if self._viewer_defends() else 0
        if heading_top <= event.y <= heading_top + HEADER_H:
            self.toggle_lane(index)
            return
        if index in self._collapsed:
            return
        card_id = self._card_at(event)
        if card_id is not None and self.on_card_click:
            self.on_card_click(card_id)

    def _on_context_click(self, event: tk.Event) -> None:
        """Offer the card menu for a unit standing in a lane, so one sent here can be brought back."""
        card_id = self._card_at(event)
        if card_id is not None and self.on_card_menu:
            self.on_card_menu(card_id)

    def _card_at(self, event: tk.Event) -> str | None:
        """The id of the unit card under the pointer, or None on bare lane or the Province card.

        Topmost first, because a unit is drawn as a tower: taking the bottommost would answer a
        click on a Personality with the Follower fanned out behind him.
        """
        for item in reversed(self.canvas.find_overlapping(event.x, event.y, event.x, event.y)):
            for tag in self.canvas.gettags(item):
                if tag.startswith(_CARD_TAG):
                    return tag[len(_CARD_TAG) :]
        return None

    def _redraw(self) -> None:
        self.canvas.delete("all")
        self._lane_spans = {}
        if self._attack is None:
            return
        attack = self._attack
        for index, span in self._lane_layout(len(attack.battlefields)).items():
            self._lane_spans[index] = span
            self._draw_lane(
                index,
                attack.battlefields[index],
                span,
                current=index == attack.current,
                attacker=attack.attacker,
            )

    def _lane_layout(self, count: int) -> dict[int, tuple[int, int]]:
        """Each of ``count`` battlefields' left and right edge. Collapsed lanes take a fixed strip
        and the open ones share what is left, so opening one never pushes another off the canvas."""
        width, _ = widget_size(self.canvas)
        open_lanes = [index for index in range(count) if index not in self._collapsed]
        spare = width - LANE_GAP * (count + 1) - COLLAPSED_W * (count - len(open_lanes))
        each = max(spare // len(open_lanes), MIN_LANE_W) if open_lanes else 0
        spans, x = {}, LANE_GAP
        for index in range(count):
            lane_w = COLLAPSED_W if index in self._collapsed else each
            spans[index] = (x, x + lane_w)
            x += lane_w + LANE_GAP
        return spans

    def _height(self) -> int:
        """The canvas height to lay out into."""
        return widget_size(self.canvas)[1]

    def _draw_lane(
        self,
        index: int,
        view: BattlefieldView,
        span: tuple[int, int],
        *,
        current: bool,
        attacker: PlayerId,
    ) -> None:
        """One lane: its panel, its heading, the two armies facing each other across a divider, and
        the button that fights the battle here. ``current`` picks out the battlefield a battle is
        being fought at; ``attacker`` is which side an outcome's winner was."""
        left, right = span
        height = self._height()
        self.canvas.create_rectangle(
            left,
            0,
            right,
            height,
            fill=theme.PANEL,
            outline=theme.GOLD if current else theme.PANEL,
            width=2,
        )
        # The seat being played holds the lower half, the way the board puts its own units below
        # the divider. Defending it therefore turns the whole lane over, bands included.
        mirrored = self._viewer_defends()
        if index in self._collapsed:
            self._draw_collapsed(index, span, height, mirrored=mirrored)
            return
        self._draw_header(index, view, span, height, mirrored=mirrored)

        defence, offence = _armies(view, self._pending.get(index), viewer_defends=mirrored)
        top, bottom = _bands(height, mirrored=mirrored)
        province_y, defending_y, divider, attacking_y = _rows(height, mirrored=mirrored)
        if view.occupant is not None:
            # Outermost on the side it belongs to, past the Defender's own units: it is what
            # they are standing in front of.
            self._draw_card(
                to_render_card(view.occupant), ((left + right) // 2, province_y), _PROVINCE_TAG
            )
        # Each army's tower fans away from the divider, so a unit never stacks over the other side.
        self._draw_army(defence.units, span, defending_y, sink=mirrored)
        self.canvas.create_line(left + 6, divider, right - 6, divider, fill=theme.INK_DIM)
        self._draw_army(offence.units, span, attacking_y, sink=not mirrored)
        if view.outcome is not None:
            # Over the rows rather than beside them: the armies have gone home by now, so the space
            # they were drawn in is what the lane has to say what happened in it.
            self._draw_outcome(
                _outcome_lines(view.outcome, view.destroyed_names, attacker), span, divider
            )
        # After the cards, so a crowded army cannot bury the total that says how it is doing. Each
        # total sits in the corner of the half its army holds.
        top_force, bottom_force = (
            (offence.force, defence.force) if mirrored else (defence.force, offence.force)
        )
        self._draw_force(top_force, left + FORCE_INSET, top + FORCE_INSET, "nw")
        self._draw_force(bottom_force, left + FORCE_INSET, bottom - FORCE_INSET, "sw")
        self._draw_footer(index, span, height)

    def _draw_collapsed(
        self, index: int, span: tuple[int, int], height: int, *, mirrored: bool
    ) -> None:
        """A collapsed lane, which is its number and nothing else. It sits where the heading would
        have, so a strip lines up with the lanes still open beside it."""
        left, right = span
        self.canvas.create_text(
            (left + right) // 2,
            height - FOOTER_H - HEADER_H if mirrored else HEADER_H,
            text=str(index + 1),
            fill=theme.INK,
            font=theme.serif(12, "bold"),
        )

    def _draw_header(
        self,
        index: int,
        view: BattlefieldView,
        span: tuple[int, int],
        height: int,
        *,
        mirrored: bool,
    ) -> None:
        """The lane's name and, in the largest type in the lane, the Province Strength the attackers
        have to beat. It names the Province, so it sits at the Province's own end of the lane."""
        left, right = span
        centre = (left + right) // 2

        # Measured in from the band's outer edge, which turns the three lines over with the lane:
        # the name stays outermost, the Strength nearest the Province it belongs to.
        def inset(distance: int) -> int:
            return height - FOOTER_H - distance if mirrored else distance

        heading = f"Battlefield {index + 1}"
        if view.fought:
            heading += "  (fought)"
        self.canvas.create_text(
            centre, inset(14), text=heading, fill=theme.INK_DIM, font=theme.serif(10, "bold")
        )
        self.canvas.create_text(
            centre, inset(32), text="PROVINCE STRENGTH", fill=theme.INK_DIM, font=theme.serif(8)
        )
        self.canvas.create_text(
            centre, inset(56), text=str(view.strength), fill=theme.INK, font=theme.serif(26, "bold")
        )

    def _draw_outcome(self, lines: list[_OutcomeLine], span: tuple[int, int], divider: int) -> None:
        """What the battle fought here did, once one has been. Stays on the lane for the rest of the
        Attack Phase, since a result the player has to catch as it goes past teaches them nothing."""
        left, right = span
        centre = (left + right) // 2
        top = divider - (len(lines) * OUTCOME_LINE_H) // 2
        self.canvas.create_rectangle(
            left + 6,
            top - 8,
            right - 6,
            top + len(lines) * OUTCOME_LINE_H + 2,
            fill=theme.PANEL,
            outline=theme.GOLD,
            width=2,
        )
        for index, line in enumerate(lines):
            self.canvas.create_text(
                centre,
                top + index * OUTCOME_LINE_H + OUTCOME_LINE_H // 2,
                text=line.text,
                fill=theme.INK if line.emphatic else theme.INK_DIM,
                font=theme.serif(11, "bold") if line.emphatic else theme.serif(9),
                width=right - left - 20,
            )

    def _draw_force(self, force: int, x: int, y: int, anchor: str) -> None:
        """One side's Force, in its own corner of the half of the lane that side holds."""
        self.canvas.create_text(
            x,
            y,
            text=str(force),
            anchor=anchor,
            fill=theme.GOLD,
            font=theme.serif(22, "bold"),
            tags=(_ARMY_FORCE_TAG,),
        )

    def _footer_band(self, span: tuple[int, int], height: int) -> tuple[float, float, float, float]:
        """The box the foot of a lane draws in, inset from the lane's own edges."""
        left, right = span
        return left + FOOTER_INSET, height - FOOTER_H + 6, right - FOOTER_INSET, height - 8

    def _draw_footer(self, index: int, span: tuple[int, int], height: int) -> None:
        """The foot of the lane: its own button when this battlefield offers one, the battle's
        sequence while one is being fought.

        The button sits under the battlefield it acts on rather than in the prompt box, so the
        choice is made where it can be seen. It cannot collide with the sequence, because a
        battlefield offers a button only while the phase is asking where to send units or where to
        fight, and neither question is open once a battle has started.
        """
        button = self._buttons.get(index)
        if button is None:
            self._draw_sequence(index, span, height)
            return
        left, top, right, bottom = self._footer_band(span, height)
        self.canvas.create_rectangle(
            left,
            top,
            right,
            bottom,
            fill=theme.GOLD if button.enabled else theme.LINE,
            outline=theme.GOLD_HOVER if button.enabled else theme.LINE,
            width=1,
        )
        self.canvas.create_text(
            (left + right) // 2,
            (top + bottom) // 2,
            text=button.label,
            fill=theme.ON_DARK if button.enabled else theme.INK_DIM,
            font=theme.serif(11, "bold"),
        )

    def _draw_sequence(self, index: int, span: tuple[int, int], height: int) -> None:
        """The CR's Battle Sequence across the foot of the lane, one cell per segment.

        Every lane carries it while a battle is being fought and only the lane it is being fought at
        lights a cell: the sequence says what a battle is doing, and the lit lane says which battle.
        """
        attack = self._attack
        if attack is None or attack.battle_segment is None:
            return
        segments = ruleset.ACTIVE.battle_segments
        left, top, right, bottom = self._footer_band(span, height)
        cell = (right - left) / len(segments)
        for step, segment in enumerate(segments):
            self._draw_sequence_cell(
                (left + step * cell, top, left + (step + 1) * cell, bottom),
                segment,
                current=segment is attack.battle_segment and index == attack.current,
            )

    def _draw_sequence_cell(
        self,
        box: tuple[float, float, float, float],
        segment: BattleSegment,
        *,
        current: bool,
    ) -> None:
        """One cell of the sequence strip, filled when it names the segment being fought."""
        left, top, right, bottom = box
        tags = (_SEQUENCE_TAG, _sequence_tag(segment))
        self.canvas.create_rectangle(
            left,
            top,
            right,
            bottom,
            fill=theme.GOLD if current else theme.PANEL,
            outline=theme.LINE,
            width=1,
            tags=tags,
        )
        self.canvas.create_text(
            (left + right) / 2,
            (top + bottom) / 2,
            text=BATTLE_SEGMENT_CHIPS[segment],
            fill=theme.ON_DARK if current else theme.INK_DIM,
            font=theme.serif(7, "bold") if current else theme.serif(7),
            tags=tags,
        )

    def _draw_army(
        self, army: tuple[UnitView, ...], span: tuple[int, int], y: int, *, sink: bool
    ) -> None:
        """One side's units, in a centred row at the board's own spacing, each stacked as a tower.

        The step tightens when the row is wider than the lane, so a large army overlaps into a fan
        rather than spilling over the lane beside it.
        """
        if not army:
            return
        left, right = span
        usable = right - left - CARD_W - 2 * LANE_GAP
        step = min(COLUMN_STEP, max(usable // max(len(army) - 1, 1), MIN_STEP))
        for x, unit in zip(centered_row((left + right) // 2, len(army), step=step), army):
            leader, attached = unit_tower_positions(x, y, len(unit.attached), sink=sink)
            # Outermost attachment first and the Personality last, so the tower stacks the way it
            # is positioned: each card tucked behind the one in front, and the Personality whole.
            for card, spot in reversed(list(zip(unit.attached, attached))):
                self._draw_card(card, spot)
            self._draw_card(unit.leader, leader)

    def _draw_card(self, card: RenderCard, at: tuple[int, int], tag: str = _CARD_TAG) -> None:
        CardSpriteVisual(card, at[0], at[1], f"{tag}{card.id}", stats=self._stats).draw(
            self.canvas, selected=card.id in self._selected
        )
