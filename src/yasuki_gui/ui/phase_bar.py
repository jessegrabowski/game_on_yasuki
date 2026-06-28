import tkinter as tk
from collections.abc import Callable, Iterable

from yasuki_core.engine.rules.projection import GameView
from yasuki_core.engine.rules.state import Phase, TURN_PHASES
from yasuki_core.engine.session import LegalAction
from yasuki_gui import theme

_PHASE_LABELS: dict[Phase, str] = {
    Phase.ACTION: "Action",
    Phase.ATTACK: "Attack",
    Phase.DYNASTY: "Dynasty",
}

_ACTION_LABELS: dict[LegalAction, str] = {
    LegalAction.PASS: "Pass",
}


class PhaseBar(tk.Frame):
    """The bottom strip: the turn number, whose turn it is, the three phases with the current one
    highlighted, and a button for each action the player may take now. ``on_action`` is called with
    the chosen :class:`LegalAction`; the caller drives the engine and calls :meth:`refresh`."""

    def __init__(self, master: tk.Misc, on_action: Callable[[LegalAction], None]):
        super().__init__(master, bg=theme.PANEL)
        self._on_action = on_action
        self._turn = tk.Label(self, bg=theme.PANEL, fg=theme.INK, font=theme.serif(12, "bold"))
        self._turn.pack(side="left", padx=12, pady=4)
        self._whose = tk.Label(self, bg=theme.PANEL, fg=theme.GOLD, font=theme.serif(11))
        self._whose.pack(side="left", padx=4, pady=4)
        self._chips: dict[Phase, tk.Label] = {}
        for phase in TURN_PHASES:
            chip = tk.Label(self, text=_PHASE_LABELS[phase], bg=theme.PANEL, padx=10, pady=4)
            chip.pack(side="left", padx=2)
            self._chips[phase] = chip
        self._actions = tk.Frame(self, bg=theme.PANEL)
        self._actions.pack(side="right", padx=12, pady=4)

    def refresh(self, view: GameView, actions: Iterable[LegalAction]) -> None:
        """Sync the bar with ``view``: turn number, whose turn, the highlighted phase, and a button
        for each currently legal action (none while it is the opponent's turn or a decision is
        owed)."""
        self._turn.configure(text=f"Turn {view.turn}")
        self._whose.configure(text="Your turn" if view.active is view.viewer else "Opponent's turn")
        for phase, chip in self._chips.items():
            active = phase is view.phase
            chip.configure(
                fg=theme.GOLD if active else theme.INK_DIM,
                font=theme.serif(11, "bold") if active else theme.serif(11),
            )
        for child in self._actions.winfo_children():
            child.destroy()
        for action in actions:
            button = tk.Button(
                self._actions,
                text=_ACTION_LABELS[action],
                command=lambda chosen=action: self._on_action(chosen),
            )
            button.pack(side="left", padx=4)
