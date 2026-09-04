import tkinter as tk
from collections.abc import Callable, Iterable
from typing import Protocol

import yasuki_gui.config as gui_config
from yasuki_gui.config import load_hotkeys
from yasuki_core.engine.players import PlayerId
from yasuki_core.engine.rules.modifiers import Stat
from yasuki_core.engine.rules.projection import AttackView
from yasuki_core.engine.table import TableState
from yasuki_core.game_pieces.cards import L5RCard
from yasuki_gui import theme
from yasuki_gui.field_view import FieldView
from yasuki_gui.layout import divider_y
from yasuki_gui.ui.geometry import widget_size
from yasuki_gui.ui.images import ImageProvider
from yasuki_gui.ui.battle_view import BattleView, LaneButton, PendingArmy
from yasuki_gui.ui.card_preview import CardPreview
from yasuki_gui.ui.card_strip import CardStrip, STRIP_H, STRIP_W
from yasuki_gui.ui.info_box import PlayerInfoBox
from yasuki_gui.ui.menus import build_menubar
from yasuki_gui.ui.phase_bar import PhaseBar
from yasuki_gui.ui.prompt_box import PromptBox

# Where the strip first opens, far enough in that the board still reads behind it.
STRIP_INSET = 40


class ClientBindings(Protocol):
    """What a window wires its widgets to. Declared here rather than imported so the widget layer
    does not depend on the service layer that drives it."""

    def refresh(self) -> None: ...
    def on_card_activated(self, card_id: str, /) -> None: ...
    def on_lane_card_clicked(self, card_id: str, /) -> None: ...
    def on_board_menu(self) -> None: ...
    def load_human_deck(self, path: str, /) -> None: ...
    def load_opponent_deck(self, path: str, /) -> None: ...
    def undo(self, event=None, /) -> None: ...
    def cancel_via_escape(self, event=None, /) -> None: ...


# Flip by hand to play with the debug affordances against a release build of the config.
LOCAL_DEBUG_OVERRIDE = False

SIDEBAR_WIDTH = 190


class GameWindow:
    """Every widget the desktop client draws, built in one pass over the table it opens on.

    Construction is total: each attribute below holds a live widget once ``__init__`` returns, so a
    collaborator takes what it needs as an argument and cannot read a widget that does not exist
    yet.

    Renders a game rather than owning one — whoever deals keeps the session, and a deck load
    reassigns ``field.state`` and calls :meth:`relayout_panels` rather than building a new window.

    Attributes
    ----------
    root : tkinter.Tk
        The toplevel window, sized to the screen.
    sidebar : tkinter.Frame
        The fixed-width left column holding the two panels and the prompt.
    content : tkinter.Frame
        The right column holding the board and the phase strip.
    field : FieldView
        The board canvas.
    battle_view : BattleView
        The attack in progress, floating over the board while there is one.
    phase_bar : PhaseBar
        The turn and phase strip along the bottom of the content column.
    prompt_box : PromptBox
        The sidebar prompt, which is what the client asks its questions through.
    opponent_panel : PlayerInfoBox
        The pile counts and honor of the seat the human is not playing.
    human_panel : PlayerInfoBox
        The pile counts and honor of the seat the human is playing.
    menubar : tkinter.Menu
        The application menu, installed on the root.
    debug : bool
        Whether the debug affordances are live, from the config or from
        :data:`LOCAL_DEBUG_OVERRIDE`.
    """

    def __init__(self, table: TableState, seat: PlayerId = PlayerId.P1) -> None:
        """Build every widget over an opening board.

        Parameters
        ----------
        table : TableState
            The board the client opens on. Required rather than optional because a
            :class:`PlayerInfoBox` reads its seat's name as it is constructed.
        seat : PlayerId, optional
            The seat being played, which decides which panel sits at the bottom of the sidebar.
            Default P1.
        """
        self.debug = gui_config.DEBUG_MODE or LOCAL_DEBUG_OVERRIDE
        if self.debug:
            # A local override has to reach the modules that read the flag rather than import it.
            gui_config.DEBUG_MODE = True

        self.root = tk.Tk()
        self.root.title("!! DEBUG DEBUG DEBUG !!" if self.debug else "Game on, Yasuki!")
        self.root.geometry(f"{self.root.winfo_screenwidth()}x{self.root.winfo_screenheight()}+0+0")

        container = tk.Frame(self.root)
        container.pack(fill="both", expand=True)
        self.sidebar = tk.Frame(container, width=SIDEBAR_WIDTH, bg=theme.PANEL)
        self.sidebar.pack(side="left", fill="y")
        self.sidebar.grid_propagate(False)  # hold the fixed width; the prompt row takes the slack
        self.sidebar.grid_columnconfigure(0, weight=1)
        self.sidebar.grid_rowconfigure(0, weight=0)  # top info box (sized to content)
        self.sidebar.grid_rowconfigure(1, weight=1)  # prompt box (fills the middle)
        self.sidebar.grid_rowconfigure(2, weight=0)  # bottom info box (sized to content)
        self.content = tk.Frame(container)
        self.content.pack(side="left", fill="both", expand=True)

        # The geometry above is still pending, so the canvas would size against a 1x1 root without
        # this.
        self.root.update_idletasks()
        canvas_w = max(400, self.root.winfo_width() - SIDEBAR_WIDTH)
        canvas_h = max(300, self.root.winfo_height())

        self.field = FieldView(self.content, width=canvas_w, height=canvas_h)
        self.field.configure_hotkeys(load_hotkeys())
        # The table backs panel and dialog reads; the board itself renders from the redacted
        # projection the client pushes in later.
        self.field.state = table
        self.field.seat = seat
        self.phase_bar = PhaseBar(self.content)
        self.phase_bar.pack(side="bottom", fill="x")
        self.field.pack(side="top", fill="both", expand=True)
        # Floats over the board rather than beside it, so it is built on the same parent and only
        # placed once there is an attack to show.
        self.battle_view = BattleView(self.field)
        # One strip for every pile either player opens, retitled as it is reused, so a player who
        # has moved it finds it where they left it.
        self.card_strip = CardStrip(self.field, ImageProvider(self.field))
        # The same keys the board reads, so a card previews the same way wherever it is looked at.
        self.card_strip.hotkeys = load_hotkeys()
        # Drawn on the window itself, so it floats over the board, the sidebar and every panel.
        # One preview shared by the board and the strip, so neither can hide or clip the other's.
        self.card_preview = CardPreview(self.root, ImageProvider(self.root))
        self.field.preview = self.card_preview
        self.card_strip.preview = self.card_preview

        # A panel reads the board through the FieldView it is handed, so the field is built first.
        self.opponent_panel = PlayerInfoBox(self.sidebar, self.field, PlayerId.P2)
        self.human_panel = PlayerInfoBox(self.sidebar, self.field, PlayerId.P1)
        for panel in (self.opponent_panel, self.human_panel):
            panel.on_inspect = self.show_cards
        self.prompt_box = PromptBox(self.sidebar)
        self.prompt_box.grid(row=1, column=0, sticky="nsew")
        # Spacebar takes the primary offered action (Pass/Pay/Discard), never a secondary like
        # Cancel.
        self.field.bind("<space>", lambda _event: self.prompt_box.invoke_primary())

        self.menubar = build_menubar(self.root, self.field)
        self.root.config(menu=self.menubar)

        self.field.on_local_player_changed = self.relayout_panels
        self.field.apply_profile_to_panels = self.apply_profile_to_panels
        self.relayout_panels()

    def show_cards(self, cards: list[L5RCard], title: str) -> None:
        """Lay a pile out over the board in the strip panel, reusing the one panel for every pile."""
        # Placed before it is filled, so the cards are laid out at the size they will be shown at
        # rather than measured against an unplaced panel and corrected on a later redraw.
        self.card_strip.open_over(STRIP_INSET, STRIP_INSET, STRIP_W, STRIP_H)
        self.card_strip.show(cards, title)

    def show_battle(
        self,
        attack: AttackView | None,
        pending: dict[int, PendingArmy] | None = None,
        buttons: dict[int, LaneButton] | None = None,
        selected: frozenset[str] = frozenset(),
        stats: dict[str, dict[Stat, int]] | None = None,
    ) -> None:
        """Float the battle over the board while ``attack`` is on, and take it away when it ends.

        It opens over the opponent's half and stays wherever the player has since dragged it. The
        arguments are :meth:`BattleView.refresh`'s and are passed straight through.
        """
        if attack is None:
            self.battle_view.close()
            return
        # The opponent's half rather than the middle, so the seat being played can see its own units
        # at home while it decides where to send them. A starting place, not a dock.
        board_w, board_h = widget_size(self.field)
        self.battle_view.open_over(0, 0, board_w, divider_y(board_h))
        self.battle_view.refresh(
            attack, pending, buttons, selected=selected, stats=stats, viewer=self.field.seat
        )

    def relayout_panels(self) -> None:
        """Move the seat being played to the bottom of the sidebar and resync both panels against
        the board. Driven by the debug seat toggle, and by a deck load, which changes the table the
        panels count."""
        self.opponent_panel.grid_forget()
        self.human_panel.grid_forget()
        top, bottom = (
            (self.opponent_panel, self.human_panel)
            if self.field.seat is PlayerId.P1
            else (self.human_panel, self.opponent_panel)
        )
        top.grid(row=0, column=0, sticky="new")
        bottom.grid(row=2, column=0, sticky="sew")
        self.opponent_panel.refresh()
        self.human_panel.refresh()

    def apply_profile_to_panels(self) -> None:
        """Push the player profile stored on the board onto whichever panel is the human's."""
        panel = self.human_panel if self.field.seat is PlayerId.P1 else self.opponent_panel
        panel.set_profile(
            getattr(self.field, "profile_name", None),
            getattr(self.field, "profile_avatar", None),
        )
        self.root.update_idletasks()

    def bind_to(self, presenter: ClientBindings) -> None:
        """Point every widget hook and key binding at ``presenter``.

        Bindings live here rather than at the assembly point because they name widgets, and the
        widgets are all built by the time this can be called — so a hook cannot be attached to one
        that does not exist yet.
        """
        # Re-render (board borders + confirm-button state) as the player toggles candidates.
        self.field.on_selection_changed = presenter.refresh
        self.field.on_card_activated = presenter.on_card_activated
        self.field.on_board_menu = presenter.on_board_menu
        self.field.load_deck_from_file = presenter.load_human_deck
        self.field.load_opponent_deck_from_file = presenter.load_opponent_deck
        self.battle_view.on_card_menu = presenter.on_card_activated
        self.battle_view.on_card_click = presenter.on_lane_card_clicked
        self.root.bind("<Control-z>", presenter.undo)
        self.root.bind("<Escape>", presenter.cancel_via_escape)

    def popup_at_pointer(
        self,
        entries: Iterable[tuple[str, Callable[[], None]] | tuple[str, Callable[[], None], bool]],
    ) -> None:
        """Pop up a menu of labelled commands where the pointer is. No-op when there is nothing to
        offer, so a caller can hand over whatever a click turned up without checking first.

        An entry may carry a third element saying whether it is available. A greyed entry is shown
        rather than hidden: it tells the player the step exists and is not reachable yet, which a
        menu that silently omits it cannot.
        """
        commands = list(entries)
        if not commands:
            return
        menu = tk.Menu(self.root, tearoff=0)
        for entry in commands:
            label, command = entry[0], entry[1]
            enabled = entry[2] if len(entry) > 2 else True
            menu.add_command(
                label=label, command=command, state=tk.NORMAL if enabled else tk.DISABLED
            )
        try:
            menu.tk_popup(self.root.winfo_pointerx(), self.root.winfo_pointery())
        finally:
            menu.grab_release()

    def run(self) -> None:
        """Enter the Tk event loop. Everything is built and presented before this is called."""
        self.root.mainloop()
