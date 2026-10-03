import tkinter as tk
from collections.abc import Callable

from yasuki_core.engine.players import PlayerId
from yasuki_core.engine.rules.projection import DuelistView, DuelView
from yasuki_core.engine.rules.vocabulary.modifiers import Stat
from yasuki_core.engine.rules.vocabulary.segments import DuelStep
from yasuki_core.game_pieces.cards import L5RCard
from yasuki_gui import theme
from yasuki_gui.constants import CARD_H, CARD_W
from yasuki_gui.layout import centered_row
from yasuki_gui.ui.card_panel import CardPanel
from yasuki_gui.ui.geometry import widget_size
from yasuki_gui.visuals.cardface import RenderCard, to_render_card

# What a duelist's sprite is tagged with here, and what a right-click reads back off it.
_CARD_TAG = "duel:"
# The side's own number, tagged apart from the per-card stamps so a reader, and a test, can tell a
# side's duel total from the stat printed on one card standing in it.
_TOTAL_TAG = "duel-total"
# The line naming who won, drawn once the duel is decided.
_OUTCOME_TAG = "duel-outcome"
# The button that dismisses a decided duel, tagged so a click can find it and a test can read it.
_CONTINUE_TAG = "duel-continue"
# The line marking which duelist has the option to focus or strike.
_OPTION_TAG = "duel-option"
# How far a side's number sits in from the corner it marks, matching the battle panel's Force.
TOTAL_INSET = 12
# How far below its side's number the option line sits.
OPTION_DROP = 20
# How far a focused card steps from the one before it: half a card, so the stack fans rather than
# hiding itself, and grows wider than the Personality as the count climbs.
FOCUS_STEP = CARD_W // 2
# How far the fan sits outboard of the Personality it lies across: half a card, so it covers the
# outer half and leaves the face below it readable.
FOCUS_OFFSET = CARD_H // 2
# What each side's half of the panel leaves above and below its Personality.
SIDE_MARGIN = 28
# How far the card that created the duel sits in from the panel's own edge.
SOURCE_INSET = 10
# The band along the foot holding the outcome line and the panel's own button.
FOOTER_H = 62
# How wide the button that dismisses a decided duel is, and what it leaves above and below itself
# inside the footer band.
CONTINUE_W = 110
CONTINUE_TOP_GAP = 14
CONTINUE_BOTTOM_GAP = 8
# The size the panel is built at, which is what its canvas asks for before Tk lays it out.
PANEL_W = 560
PANEL_H = 460


class DuelPanel(CardPanel):
    """The duel as one board: the two duelists facing each other, each with the cards it focused
    lying across it, and the number the duel compares beside each.

    Named apart from :class:`~yasuki_core.engine.rules.projection.DuelView`, which is the projection
    this draws. A duel inside a battle is still its own panel, drawn over the battle rather than
    inside it, because a duel is not part of the Battle Sequence.
    """

    def __init__(self, master: tk.Misc):
        super().__init__(master, "Duel", width=PANEL_W, height=PANEL_H, tag_prefix=_CARD_TAG)
        self.on_card_menu: Callable[[str], None] | None = None
        self.on_continue: Callable[[], None] | None = None
        self._duel: DuelView | None = None
        self._stats: dict[str, dict[Stat, int]] = {}
        # Whose side is the near one, following the board's habit of drawing the seat being played
        # at the bottom.
        self._viewer: PlayerId | None = None
        self.canvas.bind("<Configure>", lambda _event: self._redraw())
        self.canvas.bind("<Button-1>", self._on_click)
        self.canvas.bind("<Button-2>", self._on_context_click)
        self.canvas.bind("<Button-3>", self._on_context_click)

    def refresh(
        self,
        duel: DuelView | None,
        *,
        stats: dict[str, dict[Stat, int]] | None = None,
        viewer: PlayerId | None = None,
    ) -> None:
        """Redraw for ``duel``, or empty the panel when there is none."""
        self.set_title(_panel_title(duel))
        self._duel = duel
        self._stats = stats or {}
        self._viewer = viewer
        self._redraw()

    def _redraw(self) -> None:
        self.clear()
        duel = self._duel
        if duel is None:
            return
        width, height = widget_size(self.canvas)
        near, far = _sides(duel, self._viewer)
        self._draw_side(far, width, height, near=False)
        self._draw_side(near, width, height, near=True)
        self._draw_source(duel, height)
        self._draw_outcome(duel, width, height)

    def _draw_side(self, side: DuelistView, width: int, height: int, *, near: bool) -> None:
        """One duelist, its focused cards lying across it, and the number it compares."""
        center_x = width // 2
        center_y = (
            height - FOOTER_H - CARD_H // 2 - SIDE_MARGIN if near else CARD_H // 2 + SIDE_MARGIN
        )
        if side.duelist is not None:
            self.draw_card(
                to_render_card(side.duelist),
                center_x,
                center_y,
                stats=self._stats,
                pickable=True,
            )
        # Outboard, so the stack lies across the Personality's outer half rather than hiding it.
        fan_y = center_y - FOCUS_OFFSET if not near else center_y + FOCUS_OFFSET
        for card, x in zip(
            side.focused, centered_row(center_x, len(side.focused), step=FOCUS_STEP), strict=True
        ):
            # Drawn after the Personality and centered on it, so the stack lies across the
            # portrait. A card this viewer can identify while it lies face down is one it alone may
            # read, so it is shown dimmed rather than as a back (CR, Focusing Area).
            peeked = isinstance(card, L5RCard) and not card.face_up
            self.draw_card(
                to_render_card(card), x, fan_y, stats=self._stats, pickable=True, peeked=peeked
            )
        self._draw_total(side, TOTAL_INSET, center_y)
        self._draw_option(side, TOTAL_INSET, center_y + OPTION_DROP)

    def _draw_source(self, duel: DuelView, height: int) -> None:
        """The card that created the duel, drawn beside it.

        A Strategy that created a duel is in its resolution area until the duel is over: out of the
        hand it was played from and not yet in a discard pile. The duel it made is where it belongs
        on screen, and the board no longer draws it in hand.

        A duel created by a Personality's own ability names a duelist as its source, and that card
        is already drawn as one. Drawing it twice would put two sprites under one tag, which is one
        card as far as hit-testing and the sprite cache are concerned.
        """
        source = _source_to_draw(duel)
        if source is None:
            return
        self.draw_card(
            source, SOURCE_INSET + CARD_W // 2, height // 2, stats=self._stats, pickable=True
        )

    def _draw_total(self, side: DuelistView, x: int, y: int) -> None:
        """The number this side compares, which falls back to the bare duel stat where the duel
        reached no total of its own."""
        shown = side.total if side.total is not None else side.duel_stat
        if shown is None:
            return
        self.canvas.create_text(
            x,
            y,
            text=str(shown),
            anchor="w",
            fill=theme.GOLD,
            font=theme.serif(22, "bold"),
            tags=(_TOTAL_TAG,),
        )

    def _draw_option(self, side: DuelistView, x: int, y: int) -> None:
        """Mark the duelist holding the option, which is the one thing a player watching an
        alternating focusing loop cannot read off the cards."""
        duel = self._duel
        if duel is None or duel.step is not DuelStep.FOCUSING or side.seat is not duel.option:
            return
        self.canvas.create_text(
            x,
            y,
            text="the option",
            anchor="w",
            fill=theme.INK,
            font=theme.serif(10),
            tags=(_OPTION_TAG,),
        )

    def _draw_outcome(self, duel: DuelView, width: int, height: int) -> None:
        """How the duel went, once it is past its focusing.

        Shown here rather than in the prompt box, which is the board's own place for what the
        player must answer: winning or losing a duel can raise questions of its own, and they need
        the box.
        """
        if duel.step is DuelStep.FOCUSING:
            return
        self.canvas.create_text(
            width // 2,
            height - FOOTER_H,
            text=_outcome_text(duel, self._viewer),
            fill=theme.INK,
            font=theme.serif(13, "bold"),
            tags=(_OUTCOME_TAG,),
        )
        if duel.step is DuelStep.ENDED:
            self._draw_continue(width, height)

    def _draw_continue(self, width: int, height: int) -> None:
        """The button that takes a finished duel off the screen, once the player has read it."""
        left, right = width // 2 - CONTINUE_W // 2, width // 2 + CONTINUE_W // 2
        top, bottom = height - FOOTER_H + CONTINUE_TOP_GAP, height - CONTINUE_BOTTOM_GAP
        self.canvas.create_rectangle(
            left,
            top,
            right,
            bottom,
            fill=theme.GOLD,
            outline=theme.GOLD_HOVER,
            width=1,
            tags=(_CONTINUE_TAG,),
        )
        self.canvas.create_text(
            (left + right) // 2,
            (top + bottom) // 2,
            text="Continue",
            fill=theme.ON_DARK,
            font=theme.serif(11, "bold"),
            tags=(_CONTINUE_TAG,),
        )

    def _on_click(self, event: tk.Event) -> None:
        """Dismiss the panel when the click lands on Continue. A duel the engine has finished
        stays on screen until then, so the player reads the totals before the board moves on."""
        hit = self.canvas.find_withtag(_CONTINUE_TAG)
        under = self.canvas.find_overlapping(event.x, event.y, event.x, event.y)
        if hit and set(hit) & set(under) and self.on_continue is not None:
            self.on_continue()

    def _on_context_click(self, event: tk.Event) -> None:
        card_id = self.card_at(event)
        if card_id is not None and self.on_card_menu is not None:
            self.on_card_menu(card_id)


def _panel_title(duel: DuelView | None) -> str:
    """The panel's own name, carrying the card that created the duel. A duel whose source has no
    name to read is titled plainly rather than with an empty tail."""
    if duel is None or not duel.source_name:
        return "Duel"
    return f"Duel: {duel.source_name}"


def _source_to_draw(duel: DuelView) -> RenderCard | None:
    """The card that created ``duel``, or None where there is nothing of its own to draw.

    A duel made by a Personality's own ability names a duelist as its source, and that card is
    already on the panel.
    """
    if duel.source is None:
        return None
    source = to_render_card(duel.source)
    duelists = {
        to_render_card(side.duelist).id
        for side in (duel.challenger, duel.challenged)
        if side.duelist is not None
    }
    return None if source.id in duelists else source


def _sides(duel: DuelView, viewer: PlayerId | None) -> tuple[DuelistView, DuelistView]:
    """The near side first. The seat being played is the near one wherever it sits in the duel, so a
    player reads its own Personality in the same place every time. Outside a seated game the
    challenger is near."""
    if viewer is duel.challenged.seat:
        return duel.challenged, duel.challenger
    return duel.challenger, duel.challenged


def _outcome_text(duel: DuelView, viewer: PlayerId | None) -> str:
    """What the foot of the panel says about how the duel went.

    ``winners`` is empty both for a duel nobody won and for one not yet decided, so the reading
    starts from whether the duel reached an outcome at all.
    """
    if not duel.decided:
        return "Focus Effects resolve"
    if not duel.losers:
        return "The duel ended without resolution"
    if not duel.winners:
        return "Both Personalities lose the duel"
    if viewer is not None and viewer in duel.winners:
        return "You win the duel"
    return "Your opponent wins the duel"
