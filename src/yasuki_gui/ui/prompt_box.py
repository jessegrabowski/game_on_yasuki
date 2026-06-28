import tkinter as tk
from collections.abc import Callable, Iterable

from yasuki_core.engine.rules.projection import GameView
from yasuki_core.engine.session import LegalAction
from yasuki_gui import theme

_ACTION_LABELS: dict[LegalAction, str] = {
    LegalAction.PASS: "Pass",
}


class PromptBox(tk.Frame):
    """The prompt panel between the two seats: a status line (turn number and whose turn it is) and
    a button for each action the player may take now. ``on_action`` is called with the chosen
    :class:`LegalAction`; the caller drives the engine and calls :meth:`refresh`."""

    def __init__(self, master: tk.Misc, on_action: Callable[[LegalAction], None]):
        super().__init__(master, bg=theme.PANEL)
        self._on_action = on_action
        self._status = tk.Label(
            self, bg=theme.PANEL, fg=theme.INK, font=theme.serif(12, "bold"), wraplength=180
        )
        self._status.pack(side="top", fill="x", padx=8, pady=(12, 8))
        self._actions = tk.Frame(self, bg=theme.PANEL)
        self._actions.pack(side="top", fill="x", padx=8)

    def refresh(self, view: GameView, actions: Iterable[LegalAction]) -> None:
        """Show whose turn it is and a button per legal action (none while it is the opponent's turn
        or a decision is owed)."""
        whose = "Your turn" if view.active is view.viewer else "Opponent's turn"
        self._status.configure(text=f"Turn {view.turn} — {whose}")
        self._set_buttons(
            (_ACTION_LABELS[action], "normal", lambda chosen=action: self._on_action(chosen))
            for action in actions
        )

    def prompt_discard(
        self, view: GameView, needed: int, selected: int, on_confirm: Callable[[], None]
    ) -> None:
        """Ask the player to discard ``needed`` cards (selected on the board); the Discard button is
        enabled only once exactly that many are chosen."""
        self._status.configure(text=f"Turn {view.turn} — discard {needed} card(s)")
        state = "normal" if selected == needed else "disabled"
        self._set_buttons([("Discard", state, on_confirm)])

    def _set_buttons(self, specs: Iterable[tuple[str, str, Callable[[], None]]]) -> None:
        for child in self._actions.winfo_children():
            child.destroy()
        for text, state, command in specs:
            button = tk.Button(self._actions, text=text, state=state, command=command)
            button.pack(side="top", fill="x", pady=2)
