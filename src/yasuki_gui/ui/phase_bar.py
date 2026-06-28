import tkinter as tk
from collections.abc import Callable

from yasuki_core.engine.rules.projection import GameView
from yasuki_core.engine.rules.state import Phase, TURN_PHASES
from yasuki_gui import theme

_PHASE_LABELS: dict[Phase, str] = {
    Phase.ACTION: "Action",
    Phase.ATTACK: "Attack",
    Phase.DYNASTY: "Dynasty",
}


class PhaseBar(tk.Frame):
    """A strip showing the turn number and the three phases, with the current one highlighted, plus
    a button that advances the active player's turn. ``on_advance`` is called on each click; the
    caller drives the engine and calls :meth:`refresh` with the new view."""

    def __init__(self, master: tk.Misc, on_advance: Callable[[], None]):
        super().__init__(master, bg=theme.PANEL)
        self._turn = tk.Label(self, bg=theme.PANEL, fg=theme.INK, font=theme.serif(12, "bold"))
        self._turn.pack(side="left", padx=12, pady=4)
        self._chips: dict[Phase, tk.Label] = {}
        for phase in TURN_PHASES:
            chip = tk.Label(self, text=_PHASE_LABELS[phase], bg=theme.PANEL, padx=10, pady=4)
            chip.pack(side="left", padx=2)
            self._chips[phase] = chip
        self._advance = tk.Button(self, command=on_advance)
        self._advance.pack(side="right", padx=12, pady=4)

    def refresh(self, view: GameView) -> None:
        """Sync the bar with ``view``: turn number, the highlighted phase, and the button label."""
        self._turn.configure(text=f"Turn {view.turn}")
        for phase, chip in self._chips.items():
            active = phase is view.phase
            chip.configure(
                fg=theme.GOLD if active else theme.INK_DIM,
                font=theme.serif(11, "bold") if active else theme.serif(11),
            )
        at_last_phase = view.phase is TURN_PHASES[-1]
        self._advance.configure(text="End Turn ⟳" if at_last_phase else "Next Phase ▶")
