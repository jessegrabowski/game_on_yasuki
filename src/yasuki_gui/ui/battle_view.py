import tkinter as tk

from yasuki_core.engine.rules.projection import AttackView, BattlefieldView, UnitView
from yasuki_gui import theme
from yasuki_gui.constants import CARD_H, CARD_W
from yasuki_gui.layout import COLUMN_STEP, centered_row, unit_tower_positions
from yasuki_gui.ui.floating_panel import BORDER, FloatingPanel, TITLEBAR_H
from yasuki_gui.ui.geometry import widget_size
from yasuki_gui.visuals.cardface import RenderCard
from yasuki_gui.visuals.sprite import CardSpriteVisual

# How wide a lane is once collapsed: enough for its number, and no more.
COLLAPSED_W = 34
LANE_GAP = 6
HEADER_H = 60
# The tightest a row of units compresses before cards start hiding each other entirely.
MIN_STEP = 22
# The narrowest an open lane goes, however many of them are competing for the width.
MIN_LANE_W = CARD_W + 10
# How large the panel opens. The player drags it to whatever suits them from there.
PANEL_W = 900
PANEL_H = 440


class BattleView(FloatingPanel):
    """The attack in progress, drawn as one vertical lane per battlefield.

    The board draws two whole tableaux and cannot show four battlefields legibly, so this is where
    an attack is read: each lane names its Province and Strength, totals the Force on each side, and
    draws the units standing there with the same sprites the board uses. A lane collapses to a strip
    when the player wants to concentrate on one battlefield.

    A window inside the game rather than one the desktop puts beside it: it floats over the board,
    and the player drags it clear of whatever they want to look at underneath. Display only —
    nothing is answered here.
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
        self._collapsed: set[int] = set()
        self._attack: AttackView | None = None
        self._pending: dict[int, tuple[str, ...]] = {}
        self._lane_spans: dict[int, tuple[int, int]] = {}
        self.canvas.bind("<Configure>", lambda _event: self._redraw())
        self.canvas.bind("<Button-1>", self._on_click)

    def refresh(
        self, attack: AttackView | None, pending: dict[int, tuple[str, ...]] | None = None
    ) -> None:
        """Redraw for ``attack``, or empty the view when there is none.

        Parameters
        ----------
        attack : AttackView, optional
            The attack in progress, or None outside one.
        pending : dict mapping int to tuple of str, optional
            Units the player has sent to a battlefield but not yet assigned, by battlefield. Named
            apart from the armies the engine knows about, because until the assignment is answered
            they are an intention rather than a fact. Default None.
        """
        self._attack = attack
        self._pending = pending or {}
        if attack is not None:
            self._collapsed &= set(range(len(attack.battlefields)))
        self._redraw()

    def toggle_lane(self, index: int) -> None:
        """Collapse ``index``'s lane to a strip, or open it back up."""
        self._collapsed ^= {index}
        self._redraw()

    def _on_click(self, event: tk.Event) -> None:
        """Collapse or expand the lane whose header was clicked."""
        if event.y > HEADER_H:
            return
        for index, (left, right) in self._lane_spans.items():
            if left <= event.x < right:
                self.toggle_lane(index)
                return

    def _redraw(self) -> None:
        self.canvas.delete("all")
        self._lane_spans = {}
        if self._attack is None:
            return
        attack = self._attack
        for index, span in self._lane_layout(len(attack.battlefields)).items():
            self._lane_spans[index] = span
            self._draw_lane(
                index, attack.battlefields[index], span, current=index == attack.current
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
        self, index: int, view: BattlefieldView, span: tuple[int, int], *, current: bool
    ) -> None:
        """One lane: its panel, its header, and the two armies facing each other across a divider.
        ``current`` picks out the battlefield a battle is being fought at."""
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
        if index in self._collapsed:
            self.canvas.create_text(
                (left + right) // 2,
                HEADER_H,
                text=str(index + 1),
                fill=theme.INK,
                font=theme.serif(12, "bold"),
            )
            return
        self._draw_header(index, view, span)
        middle = height // 2
        self._draw_army(view.defending, span, middle - CARD_H // 2 - 8, sink=False)
        self.canvas.create_line(left + 6, middle, right - 6, middle, fill=theme.INK_DIM)
        self._draw_army(view.attacking, span, middle + CARD_H // 2 + 8, sink=True)

    def _draw_header(self, index: int, view: BattlefieldView, span: tuple[int, int]) -> None:
        """The lane's name, its Province Strength, and the Force each side brings."""
        left, right = span
        centre = (left + right) // 2
        heading = f"Battlefield {index + 1}"
        if view.fought:
            heading += "  (fought)"
        self.canvas.create_text(
            centre, 12, text=heading, fill=theme.INK, font=theme.serif(11, "bold")
        )
        self.canvas.create_text(
            centre,
            28,
            text=f"Province Strength {view.strength}",
            fill=theme.INK_DIM,
            font=theme.serif(9),
        )
        self.canvas.create_text(
            centre,
            40,
            text=f"{view.defending_force}F defending   \u00b7   {view.attacking_force}F attacking",
            fill=theme.INK_DIM,
            font=theme.serif(9),
        )
        sending = self._pending.get(index, ())
        if sending:
            self.canvas.create_text(
                centre,
                54,
                text=f"sending {', '.join(sending)}",
                fill=theme.GOLD,
                font=theme.serif(9, "bold"),
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
            self._draw_card(unit.leader, leader)
            for card, spot in zip(unit.attached, attached):
                self._draw_card(card, spot)

    def _draw_card(self, card: RenderCard, at: tuple[int, int]) -> None:
        CardSpriteVisual(card, at[0], at[1], f"battle:{card.id}").draw(self.canvas)
