import tkinter as tk

from yasuki_core.engine.rules.projection import GameView
from yasuki_core.engine.rules.state import Phase, TURN_PHASES
from yasuki_gui import theme

_PHASE_LABELS: dict[Phase, str] = {
    Phase.ACTION: "Action",
    Phase.ATTACK: "Attack",
    Phase.DYNASTY: "Dynasty",
}


class PhaseBar(tk.Frame):
    """The full-width bottom track of the turn's phases. The three phases split the width evenly and
    the current one is filled and marked, so it reads at a glance like a stepper."""

    def __init__(self, master: tk.Misc):
        super().__init__(master, bg=theme.SURFACE)
        self._chips: dict[Phase, tk.Label] = {}
        for phase in TURN_PHASES:
            chip = tk.Label(self, pady=10)
            chip.pack(side="left", expand=True, fill="both", padx=1)
            self._chips[phase] = chip

    def refresh(self, view: GameView) -> None:
        """Highlight the chip for ``view.phase`` and dim the rest."""
        for phase, chip in self._chips.items():
            active = phase is view.phase
            label = _PHASE_LABELS[phase]
            chip.configure(
                text=f"▶ {label}" if active else label,
                bg=theme.GOLD if active else theme.PANEL,
                fg=theme.ON_DARK if active else theme.INK_DIM,
                font=theme.serif(14, "bold") if active else theme.serif(12),
            )
