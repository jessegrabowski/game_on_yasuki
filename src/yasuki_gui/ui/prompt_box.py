import tkinter as tk
from collections.abc import Callable, Iterable

from yasuki_core.engine.rules.projection import GameView
from yasuki_gui import theme

# A button to offer: its label, the callback to run, and whether it is enabled.
ButtonSpec = tuple[str, Callable[[], None], bool]


class PromptBox(tk.Frame):
    """The prompt panel between the two seats: the turn, what is being asked, the gold pool, and a
    button for each offered choice. The host (presenter) builds the status text and the buttons; this
    widget only renders them."""

    def __init__(self, master: tk.Misc):
        super().__init__(master, bg=theme.PANEL)
        self._status = tk.Label(
            self, bg=theme.PANEL, fg=theme.INK, font=theme.serif(12, "bold"), wraplength=180
        )
        self._status.pack(side="top", fill="x", padx=8, pady=(12, 8))
        self._actions = tk.Frame(self, bg=theme.PANEL)
        self._actions.pack(side="top", fill="x", padx=8)

    def show(self, view: GameView, status: str, buttons: Iterable[ButtonSpec]) -> None:
        """Render ``status`` (with the turn and the viewer's gold) and a button per spec."""
        self._status.configure(text=f"Turn {view.turn} — {status}\nGold: {view.gold[view.viewer]}")
        for child in self._actions.winfo_children():
            child.destroy()
        for label, command, enabled in buttons:
            tk.Button(
                self._actions,
                text=label,
                state="normal" if enabled else "disabled",
                command=command,
            ).pack(side="top", fill="x", pady=2)
